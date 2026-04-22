"""
MySQL MCP Server —— tools.py
定义所有暴露给 LLM 的 Tool，每个函数对应一个 MCP Tool。
"""
from __future__ import annotations
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import MySQLMCPServer


def register_tools(server: "MySQLMCPServer") -> None:
    """将所有 Tool 注册到 MCP Server 实例上"""
    mcp = server.mcp
    db = server.db
    cache = server.cache
    cfg = server.config

    # ── 1. execute_query ──────────────────────────────────────────────────────

    @mcp.tool()
    def execute_query(sql: str) -> str:
        """
        执行 SELECT 查询并返回结果（JSON 格式）。
        仅允许 SELECT，自动注入 LIMIT 防止超量返回。
        """
        from shared.sql_validator import validate, SQLValidationError

        try:
            safe_sql = validate(sql, max_rows=cfg["safety"]["max_rows"])
        except SQLValidationError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        # 命中缓存
        cached = cache.get(safe_sql, db=cfg["mysql"]["database"])
        if cached is not None:
            return json.dumps({"data": cached, "cached": True}, ensure_ascii=False)

        try:
            rows = db.execute_query(safe_sql)
            cache.set(safe_sql, rows, db=cfg["mysql"]["database"])
            return json.dumps({"data": rows, "row_count": len(rows)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 2. get_schema ─────────────────────────────────────────────────────────

    @mcp.tool()
    def get_schema(table_names: str = "") -> str:
        """
        获取表结构（字段名、类型、注释）。
        table_names: 逗号分隔的表名，为空则返回全库结构摘要。
        """
        tables = [t.strip() for t in table_names.split(",") if t.strip()] or None
        try:
            return server.inspector.get_schema_text(tables=tables)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 3. list_tables ────────────────────────────────────────────────────────

    @mcp.tool()
    def list_tables() -> str:
        """
        列出当前数据库所有表名及表注释，帮助 LLM 选择正确的表。
        """
        try:
            rows = db.execute_query(
                "SELECT TABLE_NAME, TABLE_COMMENT "
                "FROM information_schema.TABLES "
                f"WHERE TABLE_SCHEMA = '{cfg['mysql']['database']}' "
                "ORDER BY TABLE_NAME"
            )
            return json.dumps({"tables": rows}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 4. explain_query ──────────────────────────────────────────────────────

    @mcp.tool()
    def explain_query(sql: str) -> str:
        """
        分析 SQL 执行计划（EXPLAIN），帮助判断是否走索引、是否有全表扫描。
        """
        from shared.sql_validator import SQLValidationError
        # EXPLAIN 本身是安全的，但要防止注入，确保 sql 是 SELECT
        sql = sql.strip().rstrip(";")
        if not sql.upper().startswith("SELECT"):
            return json.dumps({"error": "explain_query 仅支持 SELECT 语句"}, ensure_ascii=False)
        try:
            rows = db.execute_query(f"EXPLAIN {sql}")
            return json.dumps({"explain": rows}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
