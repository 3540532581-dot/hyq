#!/bin/bash

# 点仔动效生成工具 - 一键启动脚本
# 双击此文件即可启动服务并打开浏览器

cd "$(dirname "$0")"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "  🐼 点仔动效生成工具 - 启动中..."
echo "=========================================="
echo ""

# ─── 第 1 步：检查 Python3 ──────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未找到 Python3，macOS 通常自带。${NC}"
    echo "   如果确实没有，请访问 https://www.python.org/downloads/ 安装"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi
echo -e "${GREEN}✅ Python3 已找到${NC}"

# ─── 第 2 步：安装 Python 依赖 ──────────────────────────────────
echo ""
echo -e "${YELLOW}[2/6] 检查 Python 依赖...${NC}"
pip3 install --user -r requirements.txt -q 2>/dev/null || pip3 install -r requirements.txt -q 2>/dev/null || {
    echo -e "${YELLOW}尝试用 --break-system-packages 安装...${NC}"
    pip3 install --user --break-system-packages -r requirements.txt -q
}
echo -e "${GREEN}✅ Python 依赖已就绪${NC}"

# ─── 第 3 步：安装 LibTV CLI ────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/6] 检查 LibTV CLI...${NC}"

# 确保 PATH 包含可能的 libtv 安装位置
export PATH="$HOME/.local/bin:$HOME/.libtv:$PATH"

if ! command -v libtv &> /dev/null; then
    echo "   LibTV CLI 未安装，正在自动安装..."
    curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
    # 刷新 PATH
    export PATH="$HOME/.local/bin:$HOME/.libtv:$PATH"
    
    if ! command -v libtv &> /dev/null; then
        echo -e "${RED}❌ LibTV CLI 安装失败${NC}"
        echo "   请手动执行: curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash"
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi
fi
echo -e "${GREEN}✅ LibTV CLI 已就绪: $(libtv --version 2>/dev/null || echo '已安装')${NC}"

# ─── 第 4 步：检查 LibTV 登录状态 ───────────────────────────────
echo ""
echo -e "${YELLOW}[4/6] 检查 LibTV 登录状态...${NC}"

LIBTV_LOGGED_IN=false
LIBTV_OUTPUT=$(libtv account info 2>&1)
if echo "$LIBTV_OUTPUT" | grep -q '"user"'; then
    LIBTV_LOGGED_IN=true
    LIBTV_USER=$(echo "$LIBTV_OUTPUT" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data.get('user',{}).get('nickname','未知'))" 2>/dev/null || echo "未知")
    echo -e "${GREEN}✅ LibTV 已登录 ($LIBTV_USER)${NC}"
else
    echo -e "${YELLOW}⚠️  你还没有登录 LibTV，需要登录后才能生成视频。${NC}"
    echo ""
    echo "   即将打开浏览器，请在浏览器中完成 LibTV 登录。"
    echo ""
    read -n 1 -s -r -p "按任意键开始登录..."
    echo ""
    
    libtv login web --open
    
    # 再次检查
    LIBTV_OUTPUT=$(libtv account info 2>&1)
    if echo "$LIBTV_OUTPUT" | grep -q '"user"'; then
        LIBTV_USER=$(echo "$LIBTV_OUTPUT" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data.get('user',{}).get('nickname','未知'))" 2>/dev/null || echo "未知")
        echo -e "${GREEN}✅ LibTV 登录成功 ($LIBTV_USER)${NC}"
    else
        echo -e "${RED}❌ LibTV 登录似乎失败了。${NC}"
        echo "   你可以稍后手动执行: libtv login web"
        echo "   现在仍可启动工具，但 LibTV 模型将无法使用。"
        read -n 1 -s -r -p "按任意键继续启动..."
    fi
fi

# ─── 第 5 步：查找可用端口 ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[5/6] 正在启动服务...${NC}"

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

# ─── 第 6 步：打开浏览器 ────────────────────────────────────────
echo ""
echo "=========================================="
echo -e "  ${GREEN}✅ 服务已启动！${NC}"
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
