"""
web/app.py
Gradio Web 管理界面 —— 连接配置 / SQL 执行 / Schema 浏览 / Tool 测试 / SSE 服务管理
"""
from __future__ import annotations
import os
import sys
import json
import datetime
import decimal
import subprocess
import signal

import gradio as gr
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()


class _JSONEncoder(json.JSONEncoder):
    """处理数据库返回的特殊类型：datetime、date、time、Decimal、bytes"""
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, cls=_JSONEncoder)


# ── 动态连接（根据用户在 UI 中填写的参数建立连接）─────────────────────────────

def _connect_mysql(host, port, user, password, database):
    import pymysql.cursors
    import pymysql
    conn = pymysql.connect(
        host=host, port=int(port), user=user,
        password=password, database=database,
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )
    return conn


def _connect_hive(host, port, username, password, database, auth):
    from pyhive import hive
    kwargs = dict(host=host, port=int(port), username=username,
                  database=database, auth=auth)
    if auth == "CUSTOM":
        kwargs["password"] = password
    return hive.connect(**kwargs)


def _exec_mysql(conn, sql: str) -> tuple[list[dict], str]:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return rows, ""


def _exec_hive(conn, sql: str) -> tuple[list[dict], str]:
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
    return rows, ""


# ── 状态容器（存放当前连接）──────────────────────────────────────────────────

_connections: dict = {}   # {"mysql": conn, "hive": conn}

# ── SSE 进程管理 ───────────────────────────────────────────────────────────────

_BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
_SERVER_SCRIPTS = {
    "mysql": os.path.join(_BASE_DIR, "servers", "mysql_mcp", "server.py"),
    "hive":  os.path.join(_BASE_DIR, "servers", "hive_mcp",  "server.py"),
}
_sse_procs: dict[str, subprocess.Popen] = {}   # {"mysql": proc, "hive": proc}


def _is_running(db_type: str) -> bool:
    proc = _sse_procs.get(db_type)
    return proc is not None and proc.poll() is None


def _status_text(db_type: str, port: int) -> str:
    if _is_running(db_type):
        return (
            f"🟢 运行中\n"
            f"SSE 地址：http://localhost:{port}/sse\n"
            f"Cherry Studio / Cursor 填写此地址即可连接"
        )
    return "⚫ 未启动"


def start_sse(db_type: str, port: int) -> str:
    if _is_running(db_type):
        return _status_text(db_type, port)

    script = _SERVER_SCRIPTS.get(db_type)
    if not script or not os.path.exists(script):
        return f"❌ 找不到 {db_type} server 脚本：{script}"

    # 把当前 .env 中的环境变量传给子进程
    env = {**os.environ}

    try:
        proc = subprocess.Popen(
            [sys.executable, script, "--transport", "sse", "--port", str(port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _sse_procs[db_type] = proc

        # 等 1 秒检查是否启动成功（若立即退出说明有错误）
        import time
        time.sleep(1)
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            return f"❌ 启动失败：\n{err}"

        return _status_text(db_type, port)
    except Exception as e:
        return f"❌ 启动异常：{e}"


def stop_sse(db_type: str, port: int) -> str:
    proc = _sse_procs.get(db_type)
    if proc is None or proc.poll() is not None:
        _sse_procs.pop(db_type, None)
        return "⚫ 未启动"
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    _sse_procs.pop(db_type, None)
    return "⚫ 已停止"


def refresh_sse_status(db_type: str, port: int) -> str:
    return _status_text(db_type, port)


# ── Tab 1：连接配置 ────────────────────────────────────────────────────────────

def test_mysql_connection(host, port, user, password, database):
    try:
        conn = _connect_mysql(host, port, user, password, database)
        _connections["mysql"] = conn
        return "✅ MySQL 连接成功"
    except Exception as e:
        return f"❌ 连接失败: {e}"


def test_hive_connection(host, port, username, password, database, auth):
    try:
        conn = _connect_hive(host, port, username, password, database, auth)
        _connections["hive"] = conn
        return "✅ Hive 连接成功"
    except Exception as e:
        return f"❌ 连接失败: {e}"


# ── Tab 2：SQL 执行 ────────────────────────────────────────────────────────────

def run_sql(db_type: str, sql: str, enable_safety: bool, max_rows: int):
    from shared.sql_validator import validate, SQLValidationError

    if db_type not in _connections:
        return None, f"请先在「连接配置」Tab 中连接 {db_type.upper()}"

    if enable_safety:
        try:
            sql = validate(sql, max_rows=int(max_rows))
        except SQLValidationError as e:
            return None, f"❌ SQL 安全检查未通过: {e}"

    try:
        conn = _connections[db_type]
        if db_type == "mysql":
            rows, err = _exec_mysql(conn, sql)
        else:
            rows, err = _exec_hive(conn, sql)

        if err:
            return None, f"❌ 执行错误: {err}"

        if not rows:
            return gr.DataFrame(value=[]), f"查询成功，返回 0 行"

        headers = list(rows[0].keys())
        data = [[str(r.get(h, "")) for h in headers] for r in rows]
        df_value = {"headers": headers, "data": data}
        return gr.DataFrame(headers=headers, value=data), f"✅ 返回 {len(rows)} 行"

    except Exception as e:
        return None, f"❌ 执行异常: {e}"


# ── Tab 3：Schema 浏览器 ───────────────────────────────────────────────────────

def _mysql_get_schema(conn, table_filter: str) -> str:
    """直接用 pymysql 连接抽取 Schema，不依赖 server.py"""
    with conn.cursor() as cur:
        cur.execute("SELECT DATABASE()")
        db_name = list(cur.fetchone().values())[0]
        cur.execute(
            "SELECT TABLE_NAME as name, TABLE_COMMENT as comment "
            "FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA='{db_name}' ORDER BY TABLE_NAME"
        )
        tables = cur.fetchall()

    if table_filter.strip():
        tables = [t for t in tables if table_filter.strip().lower() in t["name"].lower()]

    lines = [f"数据库: {db_name}", ""]
    for t in tables:
        comment = f"  -- {t['comment']}" if t.get("comment") else ""
        lines.append(f"表: {t['name']}{comment}")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT, IS_NULLABLE "
                "FROM information_schema.COLUMNS "
                f"WHERE TABLE_SCHEMA='{db_name}' AND TABLE_NAME='{t['name']}' "
                "ORDER BY ORDINAL_POSITION"
            )
            for col in cur.fetchall():
                nullable = "" if col["IS_NULLABLE"] == "NO" else ""
                col_comment = f"  -- {col['COLUMN_COMMENT']}" if col.get("COLUMN_COMMENT") else ""
                lines.append(f"  {col['COLUMN_NAME']} {col['COLUMN_TYPE']}{col_comment}")
        lines.append("")
    return "\n".join(lines)


def _hive_get_schema(conn, database: str, table_filter: str) -> str:
    """直接用 pyhive 连接抽取 Schema，不依赖 server.py"""
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    all_tables = [r[0] for r in cursor.fetchall()]

    if table_filter.strip():
        all_tables = [t for t in all_tables if table_filter.strip().lower() in t.lower()]

    lines = [f"数据库: {database}", ""]
    for table in all_tables:
        lines.append(f"表: {table}")
        cursor.execute(f"DESCRIBE {table}")
        for row in cursor.fetchall():
            name = row[0].strip() if row[0] else ""
            if not name or name.startswith("#"):
                break
            col_type = row[1].strip() if len(row) > 1 else ""
            col_comment = f"  -- {row[2].strip()}" if len(row) > 2 and row[2] and row[2].strip() else ""
            lines.append(f"  {name} {col_type}{col_comment}")
        lines.append("")
    return "\n".join(lines)


def browse_schema(db_type: str, table_filter: str):
    if db_type not in _connections:
        return f"请先在「连接配置」Tab 中连接 {db_type.upper()}"

    conn = _connections[db_type]
    try:
        if db_type == "mysql":
            return _mysql_get_schema(conn, table_filter)
        else:
            hive_db = os.getenv("HIVE_DATABASE", "default")
            return _hive_get_schema(conn, hive_db, table_filter)
    except Exception as e:
        return f"❌ 获取 Schema 失败: {e}"


# ── Tab 4：Tool 测试 ───────────────────────────────────────────────────────────

def call_tool(db_type: str, tool_name: str, params_json: str):
    """模拟 MCP Tool 调用，直接走本地逻辑"""
    try:
        params = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError as e:
        return f"❌ 参数 JSON 解析失败: {e}"

    if db_type not in _connections:
        return f"请先连接 {db_type.upper()}"

    try:
        if db_type == "mysql":
            result = _simulate_tool("mysql", tool_name, params)
        else:
            result = _simulate_tool("hive", tool_name, params)
        return _dumps(result)
    except Exception as e:
        return f"❌ Tool 调用失败: {e}"


def _simulate_tool(db_type: str, tool_name: str, params: dict) -> dict:
    conn = _connections[db_type]

    class _Connector:
        def __init__(self, c, dtype):
            self._c = c
            self._dtype = dtype
        def execute_query(self, sql):
            if self._dtype == "mysql":
                with self._c.cursor() as cur:
                    cur.execute(sql)
                    return cur.fetchall() or []
            else:
                cursor = self._c.cursor()
                cursor.execute(sql)
                cols = [d[0] for d in cursor.description] if cursor.description else []
                return [dict(zip(cols, r)) for r in cursor.fetchall()]

    from shared.sql_validator import validate, SQLValidationError
    from shared.query_cache import QueryCache
    cache = QueryCache(ttl=0)  # Web 测试不走缓存

    if tool_name == "execute_query":
        sql = params.get("sql", "")
        try:
            safe_sql = validate(sql, max_rows=100)
        except SQLValidationError as e:
            return {"error": str(e)}
        if db_type == "mysql":
            with conn.cursor() as cur:
                cur.execute(safe_sql)
                rows = cur.fetchall()
        else:
            cursor = conn.cursor()
            cursor.execute(safe_sql)
            cols = [d[0] for d in cursor.description] if cursor.description else []
            rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        return {"data": rows, "row_count": len(rows)}

    elif tool_name == "list_tables":
        if db_type == "mysql":
            with conn.cursor() as cur:
                cur.execute("SELECT DATABASE()")
                db_name = list(cur.fetchone().values())[0]
                cur.execute(
                    "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
                    f"WHERE TABLE_SCHEMA='{db_name}' ORDER BY TABLE_NAME"
                )
                return {"tables": cur.fetchall()}
        else:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            return {"tables": [r[0] for r in cursor.fetchall()]}

    elif tool_name == "get_partitions":
        if db_type != "hive":
            return {"error": "get_partitions 仅支持 Hive"}
        table = params.get("table_name", "")
        cursor = conn.cursor()
        cursor.execute(f"SHOW PARTITIONS {table}")
        parts = [r[0] for r in cursor.fetchall()]
        return {"table": table, "total": len(parts), "latest": sorted(parts, reverse=True)[:20]}

    return {"error": f"未知 Tool: {tool_name}"}


# ── Gradio UI 构建 ─────────────────────────────────────────────────────────────

TOOL_OPTIONS = {
    "mysql": ["execute_query", "get_schema", "list_tables", "explain_query"],
    "hive":  ["execute_query", "get_schema", "list_tables", "explain_query", "get_partitions"],
}

TOOL_PARAM_EXAMPLES = {
    "execute_query":  '{"sql": "SELECT * FROM your_table LIMIT 10"}',
    "get_schema":     '{"table_names": "table1, table2"}',
    "list_tables":    '{}',
    "explain_query":  '{"sql": "SELECT * FROM your_table WHERE id=1"}',
    "get_partitions": '{"table_name": "your_partitioned_table", "limit": 20}',
}


def update_tool_choices(db_type):
    choices = TOOL_OPTIONS.get(db_type, [])
    return gr.Dropdown(choices=choices, value=choices[0] if choices else None)


def update_param_example(tool_name):
    return TOOL_PARAM_EXAMPLES.get(tool_name, "{}")


with gr.Blocks(title="Data Analytics MCP Hub", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🗄️ Data Analytics MCP Hub\n管理和测试 MySQL / Hive MCP Server")

    with gr.Tabs():

        # ── Tab 1：连接配置 ────────────────────────────────────────────────────
        with gr.Tab("🔌 连接配置"):
            gr.Markdown("### MySQL")
            with gr.Row():
                mysql_host = gr.Textbox(label="Host", value=os.getenv("MYSQL_HOST", "localhost"), scale=2)
                mysql_port = gr.Textbox(label="Port", value=os.getenv("MYSQL_PORT", "3306"), scale=1)
            with gr.Row():
                mysql_user = gr.Textbox(label="User", value=os.getenv("MYSQL_USER", "root"), scale=1)
                mysql_pass = gr.Textbox(label="Password", type="password",
                                        value=os.getenv("MYSQL_PASSWORD", ""), scale=1)
                mysql_db   = gr.Textbox(label="Database", value=os.getenv("MYSQL_DATABASE", ""), scale=1)
            mysql_test_btn = gr.Button("测试 MySQL 连接", variant="primary")
            mysql_status   = gr.Textbox(label="状态", interactive=False)
            mysql_test_btn.click(
                test_mysql_connection,
                inputs=[mysql_host, mysql_port, mysql_user, mysql_pass, mysql_db],
                outputs=mysql_status,
            )

            gr.Markdown("---\n### Hive")
            with gr.Row():
                hive_host = gr.Textbox(label="Host", value=os.getenv("HIVE_HOST", "localhost"), scale=2)
                hive_port = gr.Textbox(label="Port", value=os.getenv("HIVE_PORT", "10000"), scale=1)
            with gr.Row():
                hive_user = gr.Textbox(label="Username", value=os.getenv("HIVE_USERNAME", "hive"), scale=1)
                hive_pass = gr.Textbox(label="Password", type="password",
                                       value=os.getenv("HIVE_PASSWORD", ""), scale=1)
                hive_db   = gr.Textbox(label="Database", value=os.getenv("HIVE_DATABASE", "default"), scale=1)
                hive_auth = gr.Dropdown(label="Auth", choices=["NONE", "CUSTOM", "KERBEROS"],
                                        value=os.getenv("HIVE_AUTH", "NONE"), scale=1)
            hive_test_btn = gr.Button("测试 Hive 连接", variant="primary")
            hive_status   = gr.Textbox(label="状态", interactive=False)
            hive_test_btn.click(
                test_hive_connection,
                inputs=[hive_host, hive_port, hive_user, hive_pass, hive_db, hive_auth],
                outputs=hive_status,
            )

        # ── Tab 2：SQL 执行 ────────────────────────────────────────────────────
        with gr.Tab("⚡ SQL 执行"):
            with gr.Row():
                sql_db_type = gr.Dropdown(label="数据库", choices=["mysql", "hive"], value="mysql", scale=1)
                sql_safety  = gr.Checkbox(label="开启安全过滤（推荐）", value=True, scale=1)
                sql_maxrows = gr.Number(label="最大返回行数", value=100, scale=1)
            sql_input  = gr.Code(label="SQL", language="sql",
                                 value="SELECT * FROM your_table LIMIT 10")
            sql_run_btn = gr.Button("执行", variant="primary")
            sql_status  = gr.Textbox(label="状态", interactive=False)
            sql_result  = gr.DataFrame(label="查询结果")
            sql_run_btn.click(
                run_sql,
                inputs=[sql_db_type, sql_input, sql_safety, sql_maxrows],
                outputs=[sql_result, sql_status],
            )

        # ── Tab 3：Schema 浏览器 ───────────────────────────────────────────────
        with gr.Tab("📋 Schema 浏览器"):
            with gr.Row():
                schema_db_type = gr.Dropdown(label="数据库", choices=["mysql", "hive"], value="mysql", scale=1)
                schema_filter  = gr.Textbox(label="表名过滤（模糊匹配）", placeholder="留空显示全部", scale=2)
            schema_btn    = gr.Button("获取 Schema", variant="primary")
            schema_output = gr.Code(label="Schema 信息", language="markdown")
            schema_btn.click(
                browse_schema,
                inputs=[schema_db_type, schema_filter],
                outputs=schema_output,
            )

        # ── Tab 4：Tool 测试 ───────────────────────────────────────────────────
        with gr.Tab("🔧 Tool 测试"):
            gr.Markdown("模拟 MCP Tool 调用，验证 Tool 返回值格式是否正确")
            with gr.Row():
                tool_db_type  = gr.Dropdown(label="数据库", choices=["mysql", "hive"], value="mysql", scale=1)
                tool_name_dd  = gr.Dropdown(label="Tool", choices=TOOL_OPTIONS["mysql"],
                                            value="execute_query", scale=2)
            tool_params   = gr.Code(label="参数 (JSON)", language="json",
                                    value=TOOL_PARAM_EXAMPLES["execute_query"])
            tool_call_btn = gr.Button("调用 Tool", variant="primary")
            tool_output   = gr.Code(label="返回结果 (JSON)", language="json")

            tool_db_type.change(update_tool_choices, inputs=tool_db_type, outputs=tool_name_dd)
            tool_name_dd.change(update_param_example, inputs=tool_name_dd, outputs=tool_params)
            tool_call_btn.click(
                call_tool,
                inputs=[tool_db_type, tool_name_dd, tool_params],
                outputs=tool_output,
            )

        # ── Tab 5：SSE 服务管理 ────────────────────────────────────────────────
        with gr.Tab("🚀 SSE 服务"):
            gr.Markdown(
                "### 一键启动 MCP SSE 服务\n"
                "启动后将 **SSE 地址** 填入 Cherry Studio / Cursor / Claude Desktop 即可连接。"
            )

            with gr.Group():
                gr.Markdown("#### MySQL MCP Server")
                with gr.Row():
                    mysql_sse_port   = gr.Number(label="端口", value=8000, precision=0, scale=1)
                    mysql_sse_status = gr.Textbox(label="状态", value="⚫ 未启动",
                                                  interactive=False, scale=3)
                with gr.Row():
                    mysql_start_btn   = gr.Button("▶ 启动", variant="primary", scale=1)
                    mysql_stop_btn    = gr.Button("⏹ 停止", variant="stop", scale=1)
                    mysql_refresh_btn = gr.Button("↻ 刷新状态", scale=1)

            gr.Markdown("---")

            with gr.Group():
                gr.Markdown("#### Hive MCP Server")
                with gr.Row():
                    hive_sse_port   = gr.Number(label="端口", value=8001, precision=0, scale=1)
                    hive_sse_status = gr.Textbox(label="状态", value="⚫ 未启动",
                                                 interactive=False, scale=3)
                with gr.Row():
                    hive_start_btn   = gr.Button("▶ 启动", variant="primary", scale=1)
                    hive_stop_btn    = gr.Button("⏹ 停止", variant="stop", scale=1)
                    hive_refresh_btn = gr.Button("↻ 刷新状态", scale=1)

            gr.Markdown("---")
            gr.Markdown(
                "#### 客户端配置说明\n"
                "**Cherry Studio：** 设置 → MCP Servers → 添加 → 类型选 `SSE` → 填入上方地址\n\n"
                "**Cursor：** Settings → MCP → 添加 URL，填入上方地址\n\n"
                "**Claude Desktop：** 配置文件中 transport 改为 `sse`，url 填入上方地址"
            )

            # MySQL 事件绑定
            mysql_start_btn.click(
                lambda port: start_sse("mysql", int(port)),
                inputs=mysql_sse_port, outputs=mysql_sse_status,
            )
            mysql_stop_btn.click(
                lambda port: stop_sse("mysql", int(port)),
                inputs=mysql_sse_port, outputs=mysql_sse_status,
            )
            mysql_refresh_btn.click(
                lambda port: refresh_sse_status("mysql", int(port)),
                inputs=mysql_sse_port, outputs=mysql_sse_status,
            )

            # Hive 事件绑定
            hive_start_btn.click(
                lambda port: start_sse("hive", int(port)),
                inputs=hive_sse_port, outputs=hive_sse_status,
            )
            hive_stop_btn.click(
                lambda port: stop_sse("hive", int(port)),
                inputs=hive_sse_port, outputs=hive_sse_status,
            )
            hive_refresh_btn.click(
                lambda port: refresh_sse_status("hive", int(port)),
                inputs=hive_sse_port, outputs=hive_sse_status,
            )

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", 7860))
    demo.launch(server_port=port, share=False)
