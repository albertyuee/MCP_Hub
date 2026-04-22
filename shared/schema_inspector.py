"""
schema_inspector.py
表结构抽取模块 —— 统一接口，供 MySQL / Hive MCP Server 调用
输出格式为 LLM 友好的紧凑文本，减少 context token 消耗
"""
from __future__ import annotations
from typing import Protocol, Any


class DBConnection(Protocol):
    """各 Server 传入自己的连接对象，满足此协议即可"""
    def execute(self, sql: str) -> list[dict]: ...


def get_table_list(conn: DBConnection, database: str) -> list[dict]:
    """返回 [{table_name, comment}]"""
    raise NotImplementedError


class SchemaInspector:
    """
    通用 Schema 抽取器。
    各 Server 子类化并实现 _fetch_tables / _fetch_columns / _fetch_partitions。
    """

    def __init__(self, conn: Any, database: str, max_tables: int = 100):
        self.conn = conn
        self.database = database
        self.max_tables = max_tables

    # ── 子类实现 ──────────────────────────────────────

    def _fetch_tables(self) -> list[dict]:
        """返回 [{name: str, comment: str}]"""
        raise NotImplementedError

    def _fetch_columns(self, table: str) -> list[dict]:
        """返回 [{name, type, comment, nullable}]"""
        raise NotImplementedError

    def _fetch_partitions(self, table: str) -> list[str]:
        """返回分区列名列表，不支持分区的数据库返回 []"""
        return []

    # ── 公共方法 ──────────────────────────────────────

    def get_schema_text(self, tables: list[str] | None = None) -> str:
        """
        生成 LLM 友好的 Schema 描述文本。
        tables=None 时输出全库（最多 max_tables 张表）。
        """
        all_tables = self._fetch_tables()
        if tables:
            all_tables = [t for t in all_tables if t["name"] in tables]
        all_tables = all_tables[: self.max_tables]

        lines = [f"数据库: {self.database}", ""]
        for t in all_tables:
            comment = f"  -- {t['comment']}" if t.get("comment") else ""
            lines.append(f"表: {t['name']}{comment}")
            columns = self._fetch_columns(t["name"])
            for col in columns:
                col_comment = f"  -- {col['comment']}" if col.get("comment") else ""
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                lines.append(f"  {col['name']} {col['type']}{nullable}{col_comment}")
            partitions = self._fetch_partitions(t["name"])
            if partitions:
                lines.append(f"  [分区字段: {', '.join(partitions)}]")
            lines.append("")

        return "\n".join(lines)

    def get_table_names(self) -> list[str]:
        return [t["name"] for t in self._fetch_tables()]
