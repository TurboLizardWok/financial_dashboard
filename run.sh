#!/bin/bash
# Global Financial Dashboard - 一键启动脚本
# 用法: sh run.sh

cd "$(dirname "$0")"

VENV_DIR="/Users/jinbaiyu/.workbuddy/binaries/python/envs/dashboard"
STREAMLIT="$VENV_DIR/bin/streamlit"

# 1) 首次创建 venv
if [ ! -f "$STREAMLIT" ]; then
    echo ">>> 首次运行，正在创建虚拟环境..."
    /Users/jinbaiyu/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m venv "$VENV_DIR"
fi

# 2) 每次都同步依赖（增量安装，新加的包自动补上）
echo ">>> 同步依赖..."
"$VENV_DIR/bin/pip" install -q -r requirements.txt

# 3) 启动
echo ""
echo ">>> 启动 Dashboard..."
echo "    浏览器会自动打开，如果没有请手动访问 http://localhost:8501"
echo "    按 Ctrl+C 停止"
echo ""

exec "$STREAMLIT" run app.py
