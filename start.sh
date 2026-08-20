#!/bin/bash
# Railway 启动脚本
# 1. 安装 LibTV CLI（用 Python 下载，因为容器里没有 curl）
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
    python3 -c "
import urllib.request, zipfile, os, shutil

url = 'https://liblibai-web-static.liblib.cloud/cli/1.0.2/libtv-linux-x64.zip'
zip_path = '/tmp/libtv.zip'
extract_dir = '/tmp/libtv_extract'

print('Downloading LibTV CLI...')
urllib.request.urlretrieve(url, zip_path)
print('Downloaded.')

with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall(extract_dir)
print('Extracted.')

libtv_bin = None
for root, dirs, files in os.walk(extract_dir):
    for f in files:
        if f == 'libtv':
            libtv_bin = os.path.join(root, f)
            break
    if libtv_bin:
        break

if not libtv_bin:
    print('ERROR: libtv binary not found in zip')
    exit(1)

install_dir = os.path.expanduser('~/.libtv')
os.makedirs(install_dir, exist_ok=True)
dest = os.path.join(install_dir, 'libtv')
shutil.copy2(libtv_bin, dest)
os.chmod(dest, 0o755)
print(f'Installed to: {dest}')

# Also copy to /usr/local/bin for global access
usr_local = '/usr/local/bin/libtv'
shutil.copy2(libtv_bin, usr_local)
os.chmod(usr_local, 0o755)
print(f'Also installed to: {usr_local}')
"
    echo "   ✅ LibTV CLI 安装成功"
fi

# 添加到 PATH
export PATH="$HOME/.libtv:/usr/local/bin:$PATH"

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
