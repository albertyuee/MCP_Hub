#!/bin/bash
# 一键启动 Data Analytics MCP Hub Web 界面

set -e

cd "$(dirname "$0")"

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 Python3，请先安装：https://www.python.org/downloads/"
    exit 1
fi

# 检查 .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  已自动创建 .env 文件，请先填写数据库连接信息："
    echo "   用文本编辑器打开 $(pwd)/.env"
    echo "   填写 MYSQL_HOST / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE"
    echo ""
    echo "填写完成后重新运行此脚本。"
    exit 0
fi

# 检查依赖
if ! python3 -c "import mcp" &>/dev/null || ! python3 -c "import gradio" &>/dev/null; then
    echo "📦 正在安装依赖（首次运行需要1-3分钟）..."
    pip3 install -r requirements-mysql.txt -q
fi

echo ""
echo "🚀 启动 Web 管理界面..."
echo "   浏览器打开：http://localhost:7860"
echo "   按 Ctrl+C 停止"
echo ""
python3 web/app.py
