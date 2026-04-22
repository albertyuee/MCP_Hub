"""
examples/langchain_demo.py
演示如何将 MySQL MCP Server 接入 LangChain Agent（ReAct 链路）
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import Tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SYSTEM_PROMPT = """你是一个数据分析助手，可以通过工具查询数据库回答用户的数据问题。

可用工具:
{tools}

工具名称: {tool_names}

使用格式:
Thought: 思考需要做什么
Action: 工具名称
Action Input: 工具参数
Observation: 工具返回结果
...（可以多轮）
Thought: 我已经得到答案
Final Answer: 最终回答

问题: {input}
{agent_scratchpad}"""


async def build_langchain_tools_from_mcp(server_script: str) -> list[Tool]:
    """启动 MCP Server 进程，将其 Tools 包装为 LangChain Tool"""
    server_params = StdioServerParameters(
        command="python",
        args=[server_script],
    )
    tools = []
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = await session.list_tools()
            for t in mcp_tools.tools:
                # 闭包捕获 tool name
                tool_name = t.name
                async def _call(tool_input: str, _name=tool_name, _sess=session) -> str:
                    import json as _json
                    try:
                        params = _json.loads(tool_input)
                    except Exception:
                        params = {"sql": tool_input}
                    result = await _sess.call_tool(_name, params)
                    return str(result.content)

                tools.append(Tool(
                    name=tool_name,
                    description=t.description or tool_name,
                    func=lambda x, fn=_call: asyncio.get_event_loop().run_until_complete(fn(x)),
                ))
    return tools


def run_demo():
    import asyncio

    mysql_server = os.path.join(os.path.dirname(__file__), "..", "servers", "mysql_mcp", "server.py")

    print("正在连接 MySQL MCP Server...")
    tools = asyncio.run(build_langchain_tools_from_mcp(mysql_server))
    print(f"已加载 {len(tools)} 个 Tool: {[t.name for t in tools]}")

    llm = ChatOpenAI(
        model="qwen-plus",
        base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        temperature=0,
    )

    prompt = PromptTemplate.from_template(SYSTEM_PROMPT)
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=5)

    questions = [
        "数据库里有哪些表？",
        "查询 orders 表最近 5 条记录",
    ]

    for q in questions:
        print(f"\n{'='*50}")
        print(f"问题: {q}")
        print("="*50)
        result = executor.invoke({"input": q})
        print(f"答案: {result['output']}")


if __name__ == "__main__":
    run_demo()
