"""
examples/quickstart.py
快速验证 MySQL / Hive MCP Server 是否能正常工作
运行前确保 .env 中填写了正确的连接信息
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()


def test_mysql():
    print("=" * 40)
    print("测试 MySQL MCP Server")
    print("=" * 40)

    from servers.mysql_mcp.server import MySQLMCPServer
    srv = MySQLMCPServer()

    # list_tables
    print("\n[list_tables]")
    result = srv.db.execute_query(
        f"SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA='{srv.config['mysql']['database']}' LIMIT 5"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # get_schema
    print("\n[get_schema - 全库摘要]")
    print(srv.inspector.get_schema_text())

    # sql validator
    print("\n[SQL 安全检查]")
    from shared.sql_validator import is_safe
    tests = [
        "SELECT * FROM orders",
        "DROP TABLE orders",
        "SELECT id FROM users",
    ]
    for sql in tests:
        ok, reason = is_safe(sql)
        print(f"  {'✅' if ok else '❌'}  {sql!r:45s}  {reason}")

    print("\nMySQL 测试完成")


def test_hive():
    print("\n" + "=" * 40)
    print("测试 Hive MCP Server（需要 Hive 环境）")
    print("=" * 40)

    try:
        from servers.hive_mcp.server import HiveMCPServer
        srv = HiveMCPServer()

        print("\n[list_tables]")
        rows = srv.db.execute_query("SHOW TABLES")
        print(rows[:5])

        print("\n[get_schema]")
        print(srv.inspector.get_schema_text())

        print("\nHive 测试完成")
    except Exception as e:
        print(f"⚠️  Hive 测试跳过（无法连接）: {e}")


if __name__ == "__main__":
    test_mysql()
    test_hive()
