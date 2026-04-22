"""
Hive MCP Server —— tools.py
在 MySQL 4 个 Tool 基础上，额外新增 get_partitions。
"""
from __future__ import annotations
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import HiveMCPServer


def register_tools(server: "HiveMCPServer") -> None:
    mcp = server.mcp
    db = server.db
    cache = server.cache
    cfg = server.config

    # ── 1. execute_query ──────────────────────────────────────────────────────

    @mcp.tool()
    def execute_query(sql: str) -> str:
        """
        执行 HiveQL SELECT 查询并返回结果（JSON 格式）。
        自动注入 LIMIT 防止超量返回。
        """
        from shared.sql_validator import validate, SQLValidationError

        try:
            safe_sql = validate(sql, max_rows=cfg["safety"]["max_rows"])
        except SQLValidationError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        cached = cache.get(safe_sql, db=cfg["hive"]["database"])
        if cached is not None:
            return json.dumps({"data": cached, "cached": True}, ensure_ascii=False)

        try:
            rows = db.execute_query(safe_sql)
            cache.set(safe_sql, rows, db=cfg["hive"]["database"])
            return json.dumps({"data": rows, "row_count": len(rows)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 2. get_schema ─────────────────────────────────────────────────────────

    @mcp.tool()
    def get_schema(table_names: str = "") -> str:
        """
        获取 Hive 表结构（字段名、类型、注释、分区字段）。
        table_names: 逗号分隔的表名，为空则返回全库摘要。
        """
        tables = [t.strip() for t in table_names.split(",") if t.strip()] or None
        try:
            return server.inspector.get_schema_text(tables=tables)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 3. list_tables ────────────────────────────────────────────────────────

    @mcp.tool()
    def list_tables() -> str:
        """列出当前 Hive 数据库所有表名。"""
        try:
            rows = db.execute_query("SHOW TABLES")
            # Hive SHOW TABLES 返回单列，列名因版本而异
            table_names = [list(r.values())[0] for r in rows]
            return json.dumps({"tables": table_names}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 4. explain_query ──────────────────────────────────────────────────────

    @mcp.tool()
    def explain_query(sql: str) -> str:
        """
        分析 HiveQL 执行计划（EXPLAIN），查看 MapReduce / Tez 执行阶段。
        """
        sql = sql.strip().rstrip(";")
        if not sql.upper().startswith("SELECT"):
            return json.dumps({"error": "explain_query 仅支持 SELECT 语句"}, ensure_ascii=False)
        try:
            rows = db.execute_query(f"EXPLAIN {sql}")
            plan_text = "\n".join(list(r.values())[0] for r in rows)
            return json.dumps({"explain": plan_text}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 5. get_partitions（Hive 专属）────────────────────────────────────────

    @mcp.tool()
    def get_partitions(table_name: str, limit: int = 20) -> str:
        """
        获取 Hive 分区表的分区列表（最新 limit 条）。
        用于查询前确认分区键值，避免全表扫描。
        """
        try:
            rows = db.execute_query(f"SHOW PARTITIONS {table_name}")
            partitions = [list(r.values())[0] for r in rows]
            # 按字典序倒序取最新的
            partitions_sorted = sorted(partitions, reverse=True)[:limit]
            return json.dumps({
                "table": table_name,
                "total": len(partitions),
                "latest": partitions_sorted,
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
