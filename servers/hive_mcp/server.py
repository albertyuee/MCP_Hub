"""
Hive MCP Server —— server.py
"""
from __future__ import annotations
import os
import sys
import yaml
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.query_cache import QueryCache
from shared.schema_inspector import SchemaInspector

load_dotenv()


def _load_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(cfg_path) as f:
        raw = yaml.safe_load(f)

    def _resolve(val):
        if not isinstance(val, str):
            return val
        import re
        m = re.match(r'^\$\{(\w+)(?::(.*))?\}$', val)
        if m:
            env_key, default = m.group(1), m.group(2) or ""
            return os.getenv(env_key, default)
        return val

    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return _resolve(obj)

    return _walk(raw)


# ── Hive 连接封装 ──────────────────────────────────────────────────────────────

class HiveConnector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            from pyhive import hive
            auth = self.cfg.get("auth", "NONE")
            connect_kwargs = dict(
                host=self.cfg["host"],
                port=int(self.cfg["port"]),
                username=self.cfg["username"],
                database=self.cfg["database"],
                auth=auth,
            )
            if auth == "CUSTOM":
                connect_kwargs["password"] = self.cfg.get("password", "")
            self._conn = hive.connect(**connect_kwargs)
        return self._conn

    def execute_query(self, sql: str) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ── Hive Schema Inspector ──────────────────────────────────────────────────────

class HiveSchemaInspector(SchemaInspector):
    def __init__(self, db: HiveConnector, database: str):
        super().__init__(conn=db, database=database)

    def _fetch_tables(self) -> list[dict]:
        rows = self.conn.execute_query("SHOW TABLES")
        return [{"name": list(r.values())[0], "comment": ""} for r in rows]

    def _fetch_columns(self, table: str) -> list[dict]:
        """
        Hive DESCRIBE 返回三列：col_name, data_type, comment
        分区列在空行之后，需要区分
        """
        rows = self.conn.execute_query(f"DESCRIBE {table}")
        columns = []
        for r in rows:
            vals = list(r.values())
            name = vals[0].strip() if vals[0] else ""
            if not name or name.startswith("#"):
                break   # 空行或分区标记行后停止
            columns.append({
                "name": name,
                "type": vals[1].strip() if len(vals) > 1 else "",
                "comment": vals[2].strip() if len(vals) > 2 else "",
                "nullable": True,
            })
        return columns

    def _fetch_partitions(self, table: str) -> list[str]:
        """返回分区列名（从 DESCRIBE EXTENDED 解析）"""
        try:
            rows = self.conn.execute_query(f"DESCRIBE {table}")
            partition_cols = []
            in_partition = False
            for r in rows:
                vals = list(r.values())
                name = vals[0].strip() if vals[0] else ""
                if "# Partition Information" in name or "# col_name" in name:
                    in_partition = True
                    continue
                if in_partition and name and not name.startswith("#"):
                    partition_cols.append(name)
            return partition_cols
        except Exception:
            return []


# ── MCP Server 主体 ───────────────────────────────────────────────────────────

class HiveMCPServer:
    def __init__(self, transport: str = "stdio", port: int = 8001):
        self.config = _load_config()
        self.db = HiveConnector(self.config["hive"])
        self.cache = QueryCache(
            ttl=int(self.config["cache"]["ttl"]),
            max_size=int(self.config["cache"]["max_size"]),
        )
        self.inspector = HiveSchemaInspector(
            db=self.db,
            database=self.config["hive"]["database"],
        )
        self.mcp = FastMCP(
            name="hive-mcp",
            instructions="Hive 数据分析 MCP Server —— 支持 HiveQL 查询、Schema 抽取、分区信息获取",
            host="127.0.0.1",
            port=port,
        )
        try:
            from .tools import register_tools
        except ImportError:
            sys.path.insert(0, os.path.dirname(__file__))
            from tools import register_tools
        register_tools(self)

    def run(self, transport: str = "stdio", port: int = 8001):
        self.mcp.run(transport=transport)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    HiveMCPServer(transport=args.transport, port=args.port).run(transport=args.transport)
