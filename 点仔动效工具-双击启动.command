#!/bin/bash

# 点仔动效生成工具 - 一键启动脚本
# 双击此文件即可启动服务并打开浏览器

cd "$(dirname "$0")"

echo "=========================================="
echo "  🐼 点仔动效生成工具 - 启动中..."
echo "=========================================="
echo ""

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3，macOS 通常自带。"
    echo "   如果确实没有，请访问 https://www.python.org/downloads/ 安装"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

echo "✅ Python3 已找到"

# 检查 Node.js / npm（meigen-cli 需要）
if ! command -v npm &> /dev/null; then
    echo ""
    echo "⚠️  未找到 Node.js / npm，需要安装才能使用美境模型。"
    echo "   正在为你下载安装 Node.js..."
    echo ""
    
    # 尝试用 brew 安装
    if command -v brew &> /dev/null; then
        brew install node
    else
        echo "📥 正在从官网下载 Node.js..."
        curl -fsSL "https://nodejs.org/dist/v20.11.1/node-v20.11.1.pkg" -o /tmp/nodejs.pkg
        echo "📦 正在安装 Node.js（可能需要输入电脑密码）..."
        sudo installer -pkg /tmp/nodejs.pkg -target /
        rm -f /tmp/nodejs.pkg
    fi
fi

echo "✅ Node.js / npm 已就绪"

# 检查 meigen-cli
if ! command -v meigen &> /dev/null; then
    echo ""
    echo "📦 正在安装美境 CLI 工具（meigen-cli）..."
    npm install -g @meigen/meigen-cli
fi

echo "✅ meigen-cli 已就绪"

# 检查美境登录状态
echo ""
echo "🔐 检查美境登录状态..."
MEIGEN_STATUS=$(meigen status --json 2>/dev/null || echo '{"token_valid":false}')
TOKEN_VALID=$(echo "$MEIGEN_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token_valid', False))")
MIS_ID=$(echo "$MEIGEN_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mis_id', ''))")

if [ "$TOKEN_VALID" != "True" ] && [ "$TOKEN_VALID" != "true" ]; then
    echo ""
    echo "⚠️  你还没有登录美境，需要进行一次登录授权。"
    echo ""
    echo "   即将运行: meigen login"
    echo "   你可能需要在大象 App 中点击确认授权。"
    echo ""
    read -n 1 -s -r -p "按任意键开始登录..."
    echo ""
    meigen login
    
    # 再次检查
    MEIGEN_STATUS=$(meigen status --json 2>/dev/null || echo '{"token_valid":false}')
    TOKEN_VALID=$(echo "$MEIGEN_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token_valid', False))")
    MIS_ID=$(echo "$MEIGEN_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mis_id', ''))")
    
    if [ "$TOKEN_VALID" != "True" ] && [ "$TOKEN_VALID" != "true" ]; then
        echo ""
        echo "❌ 登录似乎失败了，请检查大象 App 是否有授权提示。"
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi
fi

echo "✅ 美境已登录 ($MIS_ID)"

# 启动服务
echo ""
echo "🚀 正在启动服务..."
echo ""

# 查找可用端口
PORT=5000
while lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; do
    PORT=$((PORT + 1))
done

# 启动 Python 服务（后台运行）
python3 server.py &
SERVER_PID=$!

# 等待服务启动
echo "⏳ 等待服务启动..."
for i in {1..30}; do
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/" | grep -q "200"; then
        break
    fi
    sleep 0.5
done

echo ""
echo "=========================================="
echo "  ✅ 服务已启动！"
echo ""
echo "  🌐 浏览器即将自动打开..."
echo "  📍 如果未自动打开，请手动访问:"
echo "     http://localhost:$PORT/"
echo ""
echo "  ⚠️  使用期间请勿关闭此窗口"
echo "=========================================="
echo ""

# 自动打开浏览器
sleep 1
open "http://localhost:$PORT/"

# 保持窗口打开，服务在后台运行
wait $SERVER_PID
