#!/bin/bash
# Railway 启动脚本
# 1. 安装 LibTV CLI
# 2. 从环境变量恢复 LibTV 凭据
# 3. 启动 Python 服务

set -e

echo "=== Railway 启动脚本 ==="

# 1. 安装 LibTV CLI
if ! command -v libtv &> /dev/null 2>&1; then
    if [ ! -f "$HOME/.libtv/libtv" ]; then
        echo "[1/3] 正在安装 LibTV CLI..."
        curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
    else
        echo "[1/3] LibTV CLI 已存在"
    fi
else
    echo "[1/3] LibTV CLI 已安装"
fi

# 2. 从环境变量恢复 LibTV 凭据
if [ -n "$LIBTV_CREDENTIALS" ]; then
    mkdir -p "$HOME/.libtv"
    echo "$LIBTV_CREDENTIALS" > "$HOME/.libtv/credentials.json"
    echo "[2/3] LibTV 凭据已恢复"
else
    echo "[2/3] 未设置 LIBTV_CREDENTIALS 环境变量，LibTV 模型将不可用"
fi

# 3. 启动服务
echo "[3/3] 启动 Python 服务..."
exec python3 server.py
