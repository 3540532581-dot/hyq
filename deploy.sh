#!/bin/bash
set -e

echo "=========================================="
echo "  点仔动效工具 - 一键部署脚本"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查是否在 Ubuntu/Debian 系统上
if ! command -v apt &> /dev/null; then
    echo -e "${RED}错误：这个脚本只支持 Ubuntu/Debian 系统${NC}"
    echo "请在购买服务器时选择 Ubuntu 22.04 LTS 镜像"
    exit 1
fi

# 更新系统
echo -e "${YELLOW}[1/8] 正在更新系统...${NC}"
sudo apt update -qq

# 安装必要软件
echo -e "${YELLOW}[2/8] 正在安装必要软件（Python、Git、Nginx 等）...${NC}"
sudo apt install -y -qq python3 python3-pip python3-venv git nginx curl ufw

# 确保 pip 可用
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}pip3 安装失败，请检查网络连接${NC}"
    exit 1
fi

# 克隆项目
echo -e "${YELLOW}[3/8] 正在下载项目代码...${NC}"
cd ~
if [ -d "hyq" ]; then
    echo "检测到已有 hyq 目录，正在更新..."
    cd hyq && git pull || true
else
    git clone https://github.com/3540532581-dot/hyq.git
    cd hyq
fi

# 安装 Python 依赖
echo -e "${YELLOW}[4/8] 正在安装 Python 依赖...${NC}"
pip3 install --user -r requirements.txt

# 安装 gunicorn（如果 requirements.txt 里没有）
pip3 install --user gunicorn

# 安装 LibTV CLI
echo -e "${YELLOW}[5/8] 正在安装 LibTV CLI...${NC}"
if ! command -v libtv &> /dev/null; then
    curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
    # 确保 libtv 在 PATH 中
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "LibTV CLI 已安装，跳过"
fi

# 获取服务器公网 IP
SERVER_IP=$(curl -s -4 ifconfig.me || curl -s -4 icanhazip.com || echo "你的服务器IP")

# 创建 systemd 服务
echo -e "${YELLOW}[6/8] 正在创建后台服务...${NC}"
sudo tee /etc/systemd/system/dianzai.service > /dev/null <<EOF
[Unit]
Description=点仔动效工具后端服务
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/hyq
Environment="PATH=$HOME/.local/bin:$HOME/.libtv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$HOME/.local/bin/gunicorn server:app --bind 0.0.0.0:5000 --workers 2 --timeout 120 --access-logfile - --error-logfile -
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 重新加载 systemd 并启动服务
sudo systemctl daemon-reload
sudo systemctl enable dianzai.service

# 停止旧服务（如果存在）
sudo systemctl stop dianzai.service 2>/dev/null || true

# 启动新服务
sudo systemctl start dianzai.service

# 等待服务启动
sleep 3

# 检查服务状态
if sudo systemctl is-active --quiet dianzai.service; then
    echo -e "${GREEN}[7/8] 后端服务启动成功！${NC}"
else
    echo -e "${RED}[7/8] 后端服务启动失败，请检查日志：${NC}"
    echo "  sudo journalctl -u dianzai -n 50"
    exit 1
fi

# 配置防火墙
echo -e "${YELLOW}[8/8] 正在配置防火墙...${NC}"
sudo ufw allow 5000/tcp 2>/dev/null || true
sudo ufw allow 80/tcp 2>/dev/null || true
sudo ufw allow 22/tcp 2>/dev/null || true
sudo ufw --force enable 2>/dev/null || true

echo ""
echo "=========================================="
echo -e "${GREEN}     部署完成！${NC}"
echo "=========================================="
echo ""
echo "你的后端地址："
echo -e "  ${GREEN}http://$SERVER_IP:5000/${NC}"
echo ""
echo "常用命令："
echo "  查看状态：sudo systemctl status dianzai"
echo "  查看日志：sudo journalctl -u dianzai -f"
echo "  重启服务：sudo systemctl restart dianzai"
echo "  停止服务：sudo systemctl stop dianzai"
echo ""
echo -e "${YELLOW}重要提醒：${NC}"
echo "1. 请在腾讯云/阿里云控制台开放 5000 端口"
echo "2. 首次使用需要在服务器上登录 LibTV："
echo "     ssh ubuntu@$SERVER_IP"
echo "     libtv login web"
echo "3. 前端页面需要把 API 地址改成："
echo "     http://$SERVER_IP:5000"
echo ""
