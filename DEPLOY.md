# 点仔动效工具 · 云端部署指南

## 重要说明

部署到公网服务器后，**「美境 Seedance 2.0 / 2.0 mini」模型将无法使用**，因为这两个模型依赖你本地电脑上的美境 CLI 脚本和美团内网环境。

**公网仍可正常使用的模型：**
- 火山方舟 Seedance 2.5
- 即梦 Seedance 2.0 fast VIP
- 阿里云百炼 Happy Horse 1.1
- 可灵 Kling 3.0

## 方案一：Render.com（推荐 · 免费 · 最简单）

[Render](https://render.com) 是一个国外的云托管平台，有免费套餐，支持 Python Flask，不需要备案。

### 步骤

1. **注册 GitHub 账号**（如果没有）：https://github.com/join
2. **新建 GitHub 仓库**并上传本项目代码：
   - 登录 GitHub → 点击右上角 `+` → `New repository`
   - 仓库名填 `dianzai-motion-tool`，选择 `Public` 或 `Private`
   - 记录仓库地址，比如 `https://github.com/你的用户名/dianzai-motion-tool.git`
3. **把本地代码推送到 GitHub**：
   ```bash
   cd ~/Downloads/dianzai-motion-tool
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/你的用户名/dianzai-motion-tool.git
   git push -u origin main
   ```
4. **注册 Render**：https://dashboard.render.com → 用 GitHub 账号登录
5. **创建 Web Service**：
   - Dashboard → `New` → `Web Service`
   - 选择你刚创建的 GitHub 仓库
   - 配置如下：
     - **Name**: `dianzai-motion-tool`
     - **Region**: 选 `Singapore`（亚洲，访问较快）
     - **Runtime**: `Python 3`
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - 点 `Create Web Service`
6. **等待部署完成**（约 2-3 分钟），完成后会给你一个类似 `https://dianzai-motion-tool.onrender.com` 的网址

> **注意**：Render 免费套餐会在 15 分钟无访问后休眠，下次访问需要等 30 秒左右冷启动。如果需要一直在线，可以升级到付费套餐（$7/月）。

---

## 方案二：Railway.app（免费额度）

[Railway](https://railway.app) 与 Render 类似，提供免费额度，部署更简单。

### 步骤

1. **注册 Railway**：https://railway.app → 用 GitHub 登录
2. **新建项目**：`New Project` → `Deploy from GitHub repo`
3. **选择仓库**：选你的 `dianzai-motion-tool` 仓库
4. **自动识别**：Railway 会自动读取 `Procfile` 和 `requirements.txt`，无需额外配置
5. **生成域名**：部署完成后自动生成公网网址

> Railway 免费额度为每月 $5，足够小项目使用。

---

## 方案三：自有服务器（Nginx + Gunicorn）

如果你有自己的云服务器（阿里云 ECS、腾讯云轻量、VPS 等），可以用以下方式部署。

### 前提条件

- 一台 Linux 服务器（Ubuntu 20.04+ 推荐）
- 已安装 Python 3.9+
- 有一个域名（可选，直接用 IP 也可以访问）

### 步骤

1. **服务器上拉取代码**：
   ```bash
   git clone https://github.com/你的用户名/dianzai-motion-tool.git
   cd dianzai-motion-tool
   ```

2. **创建虚拟环境并安装依赖**：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **用 Gunicorn 启动**（测试）：
   ```bash
   gunicorn server:app --bind 0.0.0.0:8000 --workers 2 --timeout 120
   ```
   浏览器访问 `http://你的服务器IP:8000` 测试是否正常。

4. **配置 Systemd 服务**（实现开机自启）：
   ```bash
   sudo nano /etc/systemd/system/dianzai.service
   ```
   写入以下内容：
   ```ini
   [Unit]
   Description=Dianzai Motion Tool
   After=network.target

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/path/to/dianzai-motion-tool
   Environment="PATH=/path/to/dianzai-motion-tool/venv/bin"
   ExecStart=/path/to/dianzai-motion-tool/venv/bin/gunicorn server:app --bind 0.0.0.0:8000 --workers 2 --timeout 120

   [Install]
   WantedBy=multi-user.target
   ```
   注意把 `/path/to/` 替换成实际路径。

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable dianzai
   sudo systemctl start dianzai
   ```

5. **配置 Nginx 反向代理**（推荐，支持域名 + HTTPS）：
   ```bash
   sudo apt install nginx -y
   sudo nano /etc/nginx/sites-available/dianzai
   ```
   写入：
   ```nginx
   server {
       listen 80;
       server_name 你的域名.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       location /static {
           alias /path/to/dianzai-motion-tool/static;
           expires 30d;
       }
   }
   ```

   ```bash
   sudo ln -s /etc/nginx/sites-available/dianzai /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

6. **配置 HTTPS**（可选，推荐）：
   ```bash
   sudo apt install certbot python3-certbot-nginx -y
   sudo certbot --nginx -d 你的域名.com
   ```

---

## 方案四：Docker 部署（任意平台）

如果你熟悉 Docker，可以用以下 Dockerfile：

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
```

构建并运行：
```bash
docker build -t dianzai-motion-tool .
docker run -d -p 8000:8000 --name dianzai dianzai-motion-tool
```

---

## 部署后验证

1. 打开部署后的网址
2. 上传点仔关键帧图片，确认上传成功
3. 选择「即梦 Seedance 2.0 fast VIP」或「火山方舟 Seedance 2.5」，填入 API Key
4. 点击生成，确认任务提交成功

---

## 常见问题

**Q: 部署后图片上传失败？**
A: 检查服务器磁盘空间是否充足，以及上传目录是否有写入权限。

**Q: 生成视频时提示 API 错误？**
A: API Key 仅保存在浏览器本地，不会随代码部署。每个使用者需要自己在页面上填入自己的 API Key。

**Q: 美境模型为什么显示「仅在本地可用」？**
A: 美境 Seedance 2.0 / 2.0 mini 依赖本地 meigen-cli 和内网环境，无法在公网服务器上运行。请使用其他模型。

**Q: 国内访问 Render 很慢？**
A: Render 服务器在国外，国内访问可能较慢。如需国内快速访问，建议使用阿里云 ECS 或腾讯云轻量服务器。
