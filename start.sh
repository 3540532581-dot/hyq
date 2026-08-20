#!/bin/bash
# Railway 启动脚本
# 1. 安装 LibTV CLI
# 2. 从环境变量恢复 LibTV 凭据
# 3. 启动 Python 服务

set -e

echo "=== Railway 启动脚本 ==="

# 1. 安装 LibTV CLI
LIBTV_BIN="$HOME/.libtv/libtv"

if [ -f "$LIBTV_BIN" ]; then
    echo "[1/3] LibTV CLI 已存在: $LIBTV_BIN"
else
    echo "[1/3] 正在安装 LibTV CLI..."
    curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
    
    # 安装脚本可能把 libtv 放到不同位置，搜索并建立符号链接
    FOUND_LIBTV=""
    for path in "$HOME/.local/bin/libtv" "$HOME/.libtv/libtv" "/usr/local/bin/libtv" "/usr/bin/libtv"; do
        if [ -f "$path" ]; then
            FOUND_LIBTV="$path"
            break
        fi
    done
    
    if [ -n "$FOUND_LIBTV" ] && [ "$FOUND_LIBTV" != "$LIBTV_BIN" ]; then
        mkdir -p "$(dirname "$LIBTV_BIN")"
        ln -sf "$FOUND_LIBTV" "$LIBTV_BIN"
        echo "   已链接: $FOUND_LIBTV -> $LIBTV_BIN"
    fi
    
    if [ ! -f "$LIBTV_BIN" ]; then
        echo "   ⚠️ 警告: LibTV CLI 安装后仍未找到，LibTV 模型将不可用"
    else
        echo "   ✅ LibTV CLI 安装成功"
    fi
fi

# 添加到 PATH
export PATH="$HOME/.libtv:$HOME/.local/bin:$PATH"

# 2. 从环境变量恢复 LibTV 凭据
if [ -n "$LIBTV_CREDENTIALS" ]; then
    mkdir -p "$HOME/.libtv"
    echo "$LIBTV_CREDENTIALS" > "$HOME/.libtv/credentials.json"
    echo "[2/3] LibTV 凭据已恢复"
    
    # 验证凭据
    if [ -f "$LIBTV_BIN" ]; then
        echo "   验证 LibTV 登录状态..."
        libtv account info 2>/dev/null || echo "   ⚠️ 凭据验证失败，可能需要重新登录"
    fi
else
    echo "[2/3] 未设置 LIBTV_CREDENTIALS 环境变量，LibTV 模型将不可用"
fi

# 3. 启动服务
echo "[3/3] 启动 Python 服务..."
exec python3 server.py
