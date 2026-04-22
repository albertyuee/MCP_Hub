"""
MySQL MCP Server —— server.py
入口文件，负责：连接管理、Schema 抽取、注册 Tools、启动 MCP Server
"""
from __future__ import annotations
import os
import sys
import yaml
import pymysql
import pymysql.cursors
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# 把项目根目录加入 sys.path，确保 shared 可以 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.query_cache import QueryCache
from shared.schema_inspector import SchemaInspector

# 无论从哪个目录启动，都能找到项目根目录的 .env
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(_ROOT, ".env"))

# ── 配置加载 ──────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(cfg_path) as f:
        raw = yaml.safe_load(f)

    def _resolve(val):
        """替换 ${ENV:default} 占位符"""
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


# ── DB 连接封装 ────────────────────────────────────────────────────────────────

class MySQLConnector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._conn: pymysql.Connection | None = None

    def _get_conn(self) -> pymysql.Connection:
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(
                host=self.cfg["host"],
                port=int(self.cfg["port"]),
                user=self.cfg["user"],
                password=self.cfg["password"],
                database=self.cfg["database"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=int(self.cfg.get("connect_timeout", 10)),
            )
        return self._conn

    def execute_query(self, sql: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def close(self):
        if self._conn and self._conn.open:
            self._conn.close()


# ── MySQL Schema Inspector ─────────────────────────────────────────────────────

class MySQLSchemaInspector(SchemaInspector):
    def __init__(self, db: MySQLConnector, database: str):
        super().__init__(conn=db, database=database)

    def _fetch_tables(self) -> list[dict]:
        rows = self.conn.execute_query(
            "SELECT TABLE_NAME as name, TABLE_COMMENT as comment "
            "FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA = '{self.database}' ORDER BY TABLE_NAME"
        )
        return rows

    def _fetch_columns(self, table: str) -> list[dict]:
        rows = self.conn.execute_query(
            "SELECT COLUMN_NAME as name, COLUMN_TYPE as type, "
            "COLUMN_COMMENT as comment, IS_NULLABLE as nullable "
            f"FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{self.database}' AND TABLE_NAME = '{table}' "
            "ORDER BY ORDINAL_POSITION"
        )
        for r in rows:
            r["nullable"] = r.get("nullable", "YES") == "YES"
        return rows


# ── MCP Server 主体 ───────────────────────────────────────────────────────────

class MySQLMCPServer:
    def __init__(self, transport: str = "stdio", port: int = 8000):
        self.config = _load_config()
        self.db = MySQLConnector(self.config["mysql"])
        self.cache = QueryCache(
            ttl=int(self.config["cache"]["ttl"]),
            max_size=int(self.config["cache"]["max_size"]),
        )
        self.inspector = MySQLSchemaInspector(
            db=self.db,
            database=self.config["mysql"]["database"],
        )
        self.mcp = FastMCP(
            name="mysql-mcp",
            instructions="MySQL 数据分析 MCP Server —— 支持 SQL 查询、Schema 抽取、执行计划分析",
            host="127.0.0.1",
            port=port,
        )
        # 兼容直接运行和包导入两种方式
        try:
            from .tools import register_tools
        except ImportError:
            sys.path.insert(0, os.path.dirname(__file__))
            from tools import register_tools
        register_tools(self)

    def run(self, transport: str = "stdio", port: int = 8000):
        """
        transport: "stdio"（供 Claude Desktop / Cherry Studio stdio 模式）
                   "sse"  （供支持 SSE 的客户端，本地启动后填 http://localhost:PORT/sse）
        """
        self.mcp.run(transport=transport)


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    MySQLMCPServer(transport=args.transport, port=args.port).run(transport=args.transport)
