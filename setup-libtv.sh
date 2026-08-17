#!/bin/bash
# Railway 启动前安装 LibTV CLI
# 此脚本会在 Railway 构建阶段执行

set -e

echo "=== 检查 LibTV CLI ==="
if [ -f "$HOME/.libtv/libtv" ]; then
    echo "LibTV CLI 已存在，跳过安装"
else
    echo "正在安装 LibTV CLI..."
    curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
fi

# 确保 PATH 包含 libtv
export PATH="$HOME/.libtv:$PATH"

# 验证安装
if command -v libtv &> /dev/null; then
    echo "LibTV CLI 安装成功: $(libtv --version)"
else
    echo "警告: LibTV CLI 未在 PATH 中找到"
fi

# 检查凭据目录是否存在
if [ -d "$HOME/.libtv" ]; then
    echo "LibTV 配置目录存在: $HOME/.libtv"
else
    echo "注意: LibTV 配置目录不存在，需要先登录"
fi
