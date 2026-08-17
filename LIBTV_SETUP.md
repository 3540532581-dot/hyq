# LibTV 接入说明（Railway 部署）

## 概述

本项目已接入 LibTV（LiblibAI AI 视频创作平台）作为视频生成渠道之一。LibTV 通过 CLI 调用，无需 API Key，但需要在 Railway 服务器上完成安装与登录。

## 前置条件

1. Railway 项目已部署本项目
2. 有 LibTV 账号（可用手机号注册）

## 部署步骤

### 1. 挂载 Volume（持久化凭据）

Railway 容器重启后文件会丢失，必须将 `~/.libtv` 目录持久化：

1. 打开 [Railway 控制台](https://railway.app/) → 你的 Service
2. 点击 **Settings** → **Volumes**
3. 点击 **Add Volume**
4. Mount Path 填写：`/root/.libtv`
5. 保存并重新部署

### 2. 在 Railway Shell 中登录

1. 打开 Railway 控制台 → 你的 Service → **Shell**
2. 执行以下命令安装 libtv CLI：

```bash
curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
```

3. 设置环境变量：

```bash
export PATH="$HOME/.libtv:$PATH"
```

4. 用手机号发送验证码：

```bash
libtv login phone -p 你的11位手机号
```

5. 收到短信后，填入验证码完成登录：

```bash
libtv login phone -p 你的手机号 -c 收到的6位验证码
```

6. 验证登录状态：

```bash
libtv account info
```

### 3. 验证

1. 打开你的网站首页
2. 选择模型时，应该能看到 **LibTV** 卡片（排在第一位）
3. 选中 LibTV 后，应该显示 "✅ LibTV 已就绪"

## 常见问题

### Q: 提示 "libtv CLI 未安装"

**A:** 在 Railway Shell 中执行安装命令：
```bash
curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash
```

### Q: 提示 "登录状态异常"

**A:** 在 Railway Shell 中重新登录：
```bash
export PATH="$HOME/.libtv:$PATH"
libtv login phone -p 你的手机号
# 收到验证码后
libtv login phone -p 你的手机号 -c 验证码
```

### Q: 容器重启后需要重新登录吗？

**A:** 如果已正确挂载 Volume 到 `/root/.libtv`，则不需要重新登录。凭据文件会持久保存。

### Q: 登录过期了怎么办？

**A:** LibTV 凭据有一定有效期，过期后重新执行登录命令即可。

## 技术细节

- **画布 UUID**: `2c1fc2023fc44504b4b62987567b0692`（"点仔动效自动生成"画布）
- **支持模型**: Seedance 2.5、可灵 Kling 3.0、Wan 2.7、Hailuo 2.3、Vidu Q3 等
- **生成模式**: 1 张图 → 单图生视频；2 张图 → 首尾帧；3 张图 → 多图参考
- **生成耗时**: 约 2-10 分钟
