"""
sql_validator.py
SQL 安全过滤模块 —— 拦截危险操作，限制查询行为
"""
import re
import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL, DML


# 禁止的关键字（写操作 + 危险 DDL）
_FORBIDDEN = {
    "DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE",
    "INSERT", "UPDATE", "GRANT", "REVOKE", "REPLACE",
    "LOAD", "IMPORT", "EXPORT",
}


class SQLValidationError(Exception):
    pass


def validate(sql: str, max_rows: int = 1000) -> str:
    """
    验证 SQL 安全性，并自动注入 LIMIT。
    返回处理后的 SQL；不合法则抛出 SQLValidationError。
    """
    sql = sql.strip().rstrip(";")

    if not sql:
        raise SQLValidationError("SQL 不能为空")

    parsed = sqlparse.parse(sql)
    if not parsed:
        raise SQLValidationError("无法解析 SQL")

    stmt: Statement = parsed[0]

    # 检查禁止关键字
    for token in stmt.flatten():
        upper = token.normalized.upper()
        if token.ttype in (DDL, Keyword) and upper in _FORBIDDEN:
            raise SQLValidationError(f"禁止的操作: {upper}，仅允许 SELECT 查询")

    # 必须是 SELECT
    stmt_type = stmt.get_type()
    if stmt_type and stmt_type.upper() != "SELECT":
        raise SQLValidationError(f"仅允许 SELECT 查询，当前类型: {stmt_type}")

    # 注入 LIMIT（若未包含）
    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper:
        sql = f"{sql} LIMIT {max_rows}"

    return sql


def is_safe(sql: str) -> tuple[bool, str]:
    """返回 (is_safe, reason)，不抛异常，便于 UI 展示"""
    try:
        validate(sql)
        return True, "OK"
    except SQLValidationError as e:
        return False, str(e)
