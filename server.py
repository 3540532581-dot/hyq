#!/usr/bin/env python3
"""
点仔动效生成工具 - 本地后端服务
代理美境 Seedance 视频生成 + 阿里云百炼 Happy Horse 1.1 视频生成
提供上传、提交、轮询 API

运行: python3 server.py
访问: http://localhost:5000
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)  # 允许跨域

# ─── 配置 ────────────────────────────────────────────────────────
UPLOAD_FOLDER = tempfile.mkdtemp(prefix="dianzai_")
# 本地美境脚本目录（仅本地开发时有效，云端部署时不存在）
_LOCAL_SCRIPT_DIR = Path("/Users/huangyeqing/.catpaw/skills/skills-market/meigen-designer/scripts")
SCRIPT_DIR = _LOCAL_SCRIPT_DIR if _LOCAL_SCRIPT_DIR.exists() else None
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
VIDEO_DIR = Path(__file__).parent / "static" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

UPLOADED_FILES: dict[str, str] = {}


# ─── 视频下载工具 ─────────────────────────────────────────────────

def download_video_file(video_url: str, filename: str) -> Path | None:
    """从视频 URL 下载到本地 static/videos/ 目录，返回本地路径。"""
    if not video_url:
        return None
    local_path = VIDEO_DIR / filename
    try:
        req = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as resp:
            with open(local_path, "wb") as f:
                f.write(resp.read())
        return local_path
    except Exception as e:
        print(f"下载视频失败: {e}")
        return None

# 阿里云百炼 DashScope 端点（Happy Horse 1.1 官方 API）
DASHSCOPE_VIDEO_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
DASHSCOPE_TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks"

# Happy Horse 1.1 支持的画面比例
DASHSCOPE_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"}

# 可灵 Kling 3.0（快手）端点
KLING_VIDEO_ENDPOINT = "https://api-beijing.klingai.com/v1/videos/image2video"
KLING_TASK_ENDPOINT = "https://api-beijing.klingai.com/v1/videos/image2video"

# 火山方舟（火山引擎 Ark）端点 —— 即梦 Seedance 2.5 走这里
ARK_VIDEO_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
ARK_TASK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

# 可灵 / 火山方舟 支持的画面比例
KLING_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "4:5", "5:4", "21:9", "9:21"}
ARK_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9"}

# SSL 上下文（放宽校验，兼容内网环境）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# 记录上传过的文件：{filename: local_path}，供 DashScope 生成时取回本地文件
UPLOADED_FILES: dict[str, str] = {}


# ─── 工具函数 ────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def run_script(cmd: list[str], timeout: int = 120) -> tuple[list[dict], list[str], int]:
    """
    运行脚本，流式读取 stdout（JSON Lines），同时收集 stderr。
    返回: (json_lines, stderr_lines, returncode)
    """
    if SCRIPT_DIR is None:
        return [], ["美境功能仅在本地开发环境可用"], -1
    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(SCRIPT_DIR),
    )

    json_lines: list[dict] = []
    stderr_lines: list[str] = []

    def read_stdout():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                json_lines.append(obj)
            except json.JSONDecodeError:
                pass

    def read_stderr():
        for line in proc.stderr:
            stderr_lines.append(line.strip())

    t_out = threading.Thread(target=read_stdout)
    t_err = threading.Thread(target=read_stderr)
    t_out.start()
    t_err.start()

    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        returncode = -1

    t_out.join(timeout=5)
    t_err.join(timeout=5)
    return json_lines, stderr_lines, returncode


def upload_to_s3(local_path: str) -> str | None:
    """上传本地文件到美境 S3，成功返回 URL，失败返回 None。"""
    if SCRIPT_DIR is None:
        return None
    cmd = [sys.executable, str(SCRIPT_DIR / "upload-to-s3.py"), local_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    if url.startswith("ERROR:"):
        return None
    return url


# 美境 sessionId 持久化文件路径（generate.py 内部读取）
_MEIGEN_SESSION_FILE = Path.home() / ".meigen-cli" / "meigen-designer" / "session_id"


def generate_task(prompt: str, model: str | None = None) -> dict:
    """提交美境生成任务，每次新建项目（删除旧 sessionId 文件），返回 submitted 结果或失败信息。"""
    if SCRIPT_DIR is None:
        return {"success": False, "error": "美境模型仅在本地开发环境可用，云端部署请使用 Seedance 2.5 / Jimeng / Happy Horse 1.1 / Kling 等模型。", "logs": []}
    # 强制新建美境会话（项目）
    if _MEIGEN_SESSION_FILE.exists():
        try:
            _MEIGEN_SESSION_FILE.unlink()
        except OSError:
            pass

    cmd = [sys.executable, str(SCRIPT_DIR / "generate.py"), prompt]
    if model:
        cmd.extend(["--model", model])

    print(f"[MEIGEN] 启动生成任务: model={model}, prompt_len={len(prompt)}")
    try:
        json_lines, stderr_lines, rc = run_script(cmd, timeout=120)
    except Exception as e:
        print(f"[MEIGEN] run_script 异常: {e}")
        return {"success": False, "error": f"内部错误: {e}", "logs": []}

    print(f"[MEIGEN] 脚本退出码: {rc}, JSON行数: {len(json_lines)}, stderr行数: {len(stderr_lines)}")
    for line in stderr_lines:
        print(f"[MEIGEN stderr] {line}")

    for obj in json_lines:
        action = obj.get("_action")
        if action == "submitted":
            print(f"[MEIGEN] 提交成功: sessionId={obj.get('sessionId')}")
            return {
                "success": True,
                "sessionId": obj.get("sessionId"),
                "userMessageId": obj.get("userMessageId"),
                "assistantMessageId": obj.get("assistantMessageId"),
                "logs": [o.get("content", "") for o in json_lines if o.get("_action") == "display"],
            }
        if action == "failed":
            print(f"[MEIGEN] 提交失败: {obj.get('msg')}")
            return {"success": False, "error": obj.get("msg", "生成任务提交失败"), "logs": []}

    error_msg = "未收到提交成功信号"
    if stderr_lines:
        error_msg += "；stderr: " + " | ".join(stderr_lines[-3:])
    print(f"[MEIGEN] {error_msg}")
    return {"success": False, "error": error_msg, "logs": []}


def poll_video(session_id: int, assistant_message_id: int) -> dict:
    """轮询美境视频生成状态，返回 wait_video 结果或超时/失败。"""
    if SCRIPT_DIR is None:
        return {"success": False, "error": "美境模型仅在本地开发环境可用。", "logs": []}
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "poll.py"),
        str(session_id),
        str(assistant_message_id),
        "--video",
    ]
    json_lines, stderr_lines, rc = run_script(cmd, timeout=660)  # 11分钟

    for obj in json_lines:
        action = obj.get("_action")
        if action == "wait_video":
            return {
                "success": True,
                "status": "video_generating",
                "url": obj.get("url", ""),
                "message": obj.get("content", "视频开始生成，请前往 web 端查看。"),
                "logs": [o.get("content", "") for o in json_lines if o.get("_action") == "display"],
            }
        if action == "failed":
            return {"success": False, "error": obj.get("msg", "轮询失败"), "logs": []}

    error_msg = "轮询超时或未完成"
    if stderr_lines:
        error_msg += "；stderr: " + " | ".join(stderr_lines[-3:])
    return {"success": False, "error": error_msg, "logs": []}


# ─── DashScope（阿里云百炼）相关 ──────────────────────────────────

def _dashscope_request(url: str, api_key: str, method: str = "GET", body=None, headers: dict | None = None, timeout: int = 60):
    """发起 DashScope HTTP 请求，返回 (status, parsed_json, raw_text)。"""
    hdrs = {"Authorization": f"Bearer {api_key}"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        if isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        status = e.code

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    return status, parsed, raw


def dashscope_upload_file(api_key: str, local_path: str) -> str | None:
    """上传本地文件到 DashScope，返回公网可访问的 URL。"""
    filename = os.path.basename(local_path)
    mime = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    with open(local_path, "rb") as f:
        content = f.read()

    boundary = f"----DashScopeBoundary{uuid.uuid4().hex[:16]}"

    def field(name: str, value: str) -> bytes:
        return (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n").encode("utf-8")

    body = b""
    body += field("model", "happyhorse-1.1")
    body += (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
    body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")

    status, parsed, raw = _dashscope_request(
        DASHSCOPE_UPLOAD_ENDPOINT, api_key, method="POST", body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    if status not in (200, 201):
        return None

    # 兼容不同版本的返回结构
    data = parsed.get("data") or {}
    uploaded = data.get("uploaded_files") or []
    if uploaded:
        first = uploaded[0]
        return first.get("file_url") or first.get("url") or first.get("oss_url")
    # 直接给 url 字段的情况
    if data.get("url"):
        return data["url"]
    if data.get("file_url"):
        return data["file_url"]
    return None


def dashscope_submit_video(api_key: str, prompt: str, local_paths: list[str], ratio: str, duration: int) -> dict:
    """提交 Happy Horse 1.1 视频生成任务，返回 task_id 或错误。"""
    if not api_key:
        return {"success": False, "error": "未提供阿里云百炼 API Key"}

    if not local_paths:
        return {"success": False, "error": "没有可用的关键帧图片"}

    # 1. 上传每张本地图片到 DashScope，获取公网 URL
    urls: list[str] = []
    for p in local_paths:
        if not os.path.exists(p):
            return {"success": False, "error": f"本地图片不存在: {p}"}
        url = dashscope_upload_file(api_key, p)
        if not url:
            return {"success": False, "error": "关键帧上传到阿里云百炼失败（请检查 API Key 是否有效）"}
        urls.append(url)

    # 2. 根据图片数量自动选择模型与 media 类型
    #    1 张 → i2v（首帧图生视频）；多张 → r2v（多参考图保持 IP 一致）
    if len(urls) == 1:
        model = "happyhorse-1.1-i2v"
        media = [{"type": "first_frame", "url": urls[0]}]
    else:
        model = "happyhorse-1.1-r2v"
        media = [{"type": "reference_image", "url": u} for u in urls]

    # 3. 组装请求体
    if ratio not in DASHSCOPE_RATIOS:
        ratio = "1:1"
    body = {
        "model": model,
        "input": {
            "prompt": prompt,
            "media": media,
        },
        "parameters": {
            "resolution": "720P",
            "ratio": ratio,
            "duration": duration,
            "watermark": False,
        },
    }

    status, parsed, raw = _dashscope_request(
        DASHSCOPE_VIDEO_ENDPOINT, api_key, method="POST", body=body,
        headers={"X-DashScope-Async": "enable"},
    )

    if status not in (200, 201, 202):
        msg = parsed.get("message") or parsed.get("msg") or raw[:300] or f"HTTP {status}"
        return {"success": False, "error": f"提交任务失败: {msg}"}

    output = parsed.get("output") or {}
    task_id = output.get("task_id")
    if not task_id:
        return {"success": False, "error": f"未获取到 task_id: {raw[:300]}"}

    return {"success": True, "task_id": task_id, "model": model}


def dashscope_poll_task(api_key: str, task_id: str) -> dict:
    """轮询 DashScope 任务状态，返回结果或失败。"""
    url = f"{DASHSCOPE_TASK_ENDPOINT}/{task_id}"
    status, parsed, raw = _dashscope_request(url, api_key, method="GET")

    output = parsed.get("output") or {}
    task_status = output.get("task_status", "").upper()

    if status == 200 and task_status in ("SUCCEEDED",):
        video_url = output.get("video_url") or ""
        return {"success": True, "status": "succeeded", "video_url": video_url}

    if task_status in ("FAILED", "CANCELED"):
        msg = parsed.get("message") or raw[:300] or "任务失败"
        return {"success": False, "error": msg, "status": task_status.lower()}

    # PENDING / RUNNING → 继续等待
    return {"success": True, "status": "running", "task_status": task_status}


# ─── 通用 HTTP 工具 ──────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    """Base64 URL-safe 编码（去掉 padding）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _http_request(url: str, headers: dict, method: str = "GET", body=None, timeout: int = 60):
    """通用 HTTP 请求，返回 (status, parsed_json, raw_text)。"""
    data = None
    if body is not None:
        if isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        status = e.code
    except urllib.error.URLError as e:
        return 0, {}, f"网络错误: {e.reason}"

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    return status, parsed, raw


def local_file_to_data_uri(local_path: str) -> str | None:
    """读取本地图片并转为 data URI（base64），供无法访问内网 URL 的服务使用。"""
    if not os.path.exists(local_path):
        return None
    mime = mimetypes.guess_type(local_path)[0] or "image/png"
    with open(local_path, "rb") as f:
        content = f.read()
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ─── 可灵 Kling 3.0 相关 ─────────────────────────────────────────

def kling_jwt(access_key: str, secret_key: str) -> str:
    """用 AccessKey + SecretKey 生成可灵 JWT（HS256，纯标准库实现）。"""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": access_key, "exp": now + 1800, "nbf": now - 5}
    seg1 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    seg2 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{seg1}.{seg2}".encode("utf-8")
    sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    seg3 = _b64url(sig)
    return f"{seg1}.{seg2}.{seg3}"


def kling_submit_video(access_key: str, secret_key: str, prompt: str, local_paths: list[str], ratio: str, duration: int) -> dict:
    """提交可灵 Kling 3.0 图生视频任务，返回 task_id 或错误。"""
    if not access_key or not secret_key:
        return {"success": False, "error": "未提供可灵 AccessKey / SecretKey（两个都需要）"}
    if not local_paths:
        return {"success": False, "error": "没有可用的关键帧图片"}

    image_uri = local_file_to_data_uri(local_paths[0])
    if not image_uri:
        return {"success": False, "error": f"无法读取本地图片: {local_paths[0]}"}

    if ratio not in KLING_RATIOS:
        ratio = "1:1"

    body = {
        "model_name": "kling-v3",
        "image": image_uri,
        "prompt": prompt,
        "mode": "std",
        "duration": str(duration),
        "aspect_ratio": ratio,
        "cfg_scale": 0.5,
    }

    # 两张及以上 → 用最后一张作为尾帧（首尾帧控制）
    if len(local_paths) >= 2:
        tail_uri = local_file_to_data_uri(local_paths[-1])
        if tail_uri:
            body["image_tail"] = tail_uri

    token = kling_jwt(access_key, secret_key)
    status, parsed, raw = _http_request(
        KLING_VIDEO_ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST", body=body,
    )

    if status not in (200, 201, 202):
        msg = parsed.get("message") or raw[:300] or f"HTTP {status}"
        return {"success": False, "error": f"提交任务失败: {msg}"}

    data = parsed.get("data") or {}
    task_id = data.get("task_id") or parsed.get("task_id")
    if not task_id:
        return {"success": False, "error": f"未获取到 task_id: {raw[:300]}"}

    return {"success": True, "task_id": task_id, "model": "kling-v3"}


def kling_poll_task(access_key: str, secret_key: str, task_id: str) -> dict:
    """轮询可灵任务状态。"""
    url = f"{KLING_TASK_ENDPOINT}/{task_id}"
    token = kling_jwt(access_key, secret_key)
    status, parsed, raw = _http_request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET",
    )

    data = parsed.get("data") or {}
    item = data[0] if isinstance(data, list) and data else data
    task_status = (item.get("task_status") or item.get("status") or "").lower()

    if task_status == "succeed":
        result = item.get("task_result") or {}
        videos = result.get("videos") or []
        video_url = videos[0].get("url", "") if videos else (result.get("url") or "")
        return {"success": True, "status": "succeeded", "video_url": video_url}

    if task_status in ("failed", "canceled"):
        msg = item.get("task_status_msg") or raw[:300] or "任务失败"
        return {"success": False, "error": msg, "status": task_status}

    return {"success": True, "status": "running", "task_status": task_status or "processing"}


# ─── 火山方舟（即梦 Seedance 2.5）相关 ────────────────────────────

def ark_submit_video(api_key: str, model_id: str, prompt: str, local_paths: list[str], ratio: str, duration: int) -> dict:
    """提交火山方舟 Seedance 图生视频任务，返回 task_id 或错误。"""
    if not api_key:
        return {"success": False, "error": "未提供火山方舟 API Key"}
    if not local_paths:
        return {"success": False, "error": "没有可用的关键帧图片"}

    if ratio not in ARK_RATIOS:
        ratio = "1:1"

    image_uri = local_file_to_data_uri(local_paths[0])
    if not image_uri:
        return {"success": False, "error": f"无法读取本地图片: {local_paths[0]}"}

    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_uri}, "role": "first_frame"},
    ]
    # 两张及以上 → 加尾帧
    if len(local_paths) >= 2:
        tail_uri = local_file_to_data_uri(local_paths[-1])
        if tail_uri:
            content.append({"type": "image_url", "image_url": {"url": tail_uri}, "role": "last_frame"})

    body = {
        "model": model_id or "Doubao-Seedance-2.5",
        "content": content,
        "resolution": "720p",
        "ratio": ratio,
        "duration": duration,
    }

    status, parsed, raw = _http_request(
        ARK_VIDEO_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST", body=body,
    )

    if status not in (200, 201, 202):
        err = parsed.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code") or raw[:300]
        else:
            msg = parsed.get("message") or raw[:300] or f"HTTP {status}"
        return {"success": False, "error": f"提交任务失败: {msg}"}

    task_id = parsed.get("id") or parsed.get("task_id")
    if not task_id:
        return {"success": False, "error": f"未获取到 task_id: {raw[:300]}"}

    return {"success": True, "task_id": task_id, "model": model_id or "Doubao-Seedance-2.5"}


def ark_poll_task(api_key: str, task_id: str) -> dict:
    """轮询火山方舟任务状态。"""
    url = f"{ARK_TASK_ENDPOINT}/{task_id}"
    status, parsed, raw = _http_request(
        url, headers={"Authorization": f"Bearer {api_key}"}, method="GET",
    )

    ark_status = (parsed.get("status") or "").lower()

    if ark_status in ("succeeded", "success"):
        content = parsed.get("content") or {}
        video_url = content.get("video_url") or content.get("url") or ""
        if not video_url:
            urls = content.get("video_urls") or []
            video_url = urls[0] if urls else ""
        return {"success": True, "status": "succeeded", "video_url": video_url}

    if ark_status in ("failed", "cancelled", "canceled"):
        err = parsed.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else (raw[:300] or "任务失败")
        return {"success": False, "error": msg, "status": ark_status}

    return {"success": True, "status": "running", "task_status": ark_status or "queued"}


# ─── LibTV 相关 ──────────────────────────────────────────────────
# LibTV 是 LiblibAI 推出的 AI 视频创作平台，通过 CLI 调用
# 安装方式: curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash

LIBTV_CLI_PATH = os.path.expanduser("~/.libtv/libtv")
LIBTV_CONFIG_DIR = os.path.expanduser("~/.libtv")
LIBTV_PROJECT_UUID = "2c1fc2023fc44504b4b62987567b0692"  # "点仔动效自动生成"画布
LIBTV_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9"}


def check_libtv_available() -> dict:
    """检查 libtv CLI 是否可用、是否已登录"""
    result = {"available": False, "logged_in": False, "error": None, "nickname": None}
    if not os.path.isfile(LIBTV_CLI_PATH):
        result["error"] = "libtv CLI 未安装"
        return result
    result["available"] = True
    # 检查登录状态
    try:
        env = os.environ.copy()
        env["PATH"] = f"{os.path.dirname(LIBTV_CLI_PATH)}:{env.get('PATH', '')}"
        env["LIBTV_CONFIG_DIR"] = LIBTV_CONFIG_DIR
        proc = subprocess.run(
            [LIBTV_CLI_PATH, "account", "info"],
            capture_output=True, text=True, timeout=15, env=env
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            result["logged_in"] = True
            result["nickname"] = data.get("user", {}).get("nickname", "")
        else:
            result["error"] = f"登录状态异常: {proc.stderr[:200]}"
    except Exception as e:
        result["error"] = str(e)
    return result


def install_libtv_cli() -> dict:
    """安装 libtv CLI"""
    try:
        # 运行官方安装脚本
        proc = subprocess.run(
            ["bash", "-c", "curl -fsSL https://liblibai-web-static.liblib.cloud/cli/latest/install-libtv-cli.sh | bash"],
            capture_output=True, text=True, timeout=60
        )
        if proc.returncode == 0 and os.path.isfile(LIBTV_CLI_PATH):
            return {"success": True, "message": "libtv CLI 安装成功"}
        return {"success": False, "error": f"安装失败: {proc.stderr[:300]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def libtv_submit_video(prompt: str, local_paths: list[str], ratio: str, duration: int, model: str = "Seedance 2.5") -> dict:
    """调用 libtv CLI 提交视频生成任务，返回 video_url 或错误"""
    if not os.path.isfile(LIBTV_CLI_PATH):
        return {"success": False, "error": "libtv CLI 未安装，请联系管理员"}
    if not local_paths:
        return {"success": False, "error": "没有可用的关键帧图片"}

    env = os.environ.copy()
    env["PATH"] = f"{os.path.dirname(LIBTV_CLI_PATH)}:{env.get('PATH', '')}"
    env["LIBTV_CONFIG_DIR"] = LIBTV_CONFIG_DIR

    if ratio not in LIBTV_RATIOS:
        ratio = "1:1"

    try:
        # 1. 上传所有关键帧到 LibTV
        frame_names = []
        for i, path in enumerate(local_paths):
            if not os.path.exists(path):
                return {"success": False, "error": f"本地图片不存在: {path}"}
            frame_name = f"帧{i + 1}"
            upload_cmd = [
                LIBTV_CLI_PATH, "upload", frame_name, "-t", "image",
                "--resource", path, "-p", LIBTV_PROJECT_UUID
            ]
            proc = subprocess.run(upload_cmd, capture_output=True, text=True, timeout=60, env=env)
            if proc.returncode != 0:
                return {"success": False, "error": f"上传帧{i+1}失败: {proc.stderr[:300]}"}
            frame_names.append(frame_name)

        # 2. 确定生成模式
        if len(frame_names) == 1:
            mode_type = "singleImage2video"
        elif len(frame_names) == 2:
            mode_type = "frames2video"
        else:
            mode_type = "mixed2video"

        # 3. 创建视频节点
        node_name = f"dianzai-{int(time.time() * 1000)}"
        create_cmd = [
            LIBTV_CLI_PATH, "node", "create", node_name, "-t", "video",
            "-p", LIBTV_PROJECT_UUID,
            "-s", f"model={model}",
            "-s", f"modeType={mode_type}",
            "-s", f"ratio={ratio}",
            "-s", f"duration={duration}",
            "--prompt", prompt
        ]
        proc = subprocess.run(create_cmd, capture_output=True, text=True, timeout=30, env=env)
        if proc.returncode != 0:
            return {"success": False, "error": f"创建视频节点失败: {proc.stderr[:300]}"}

        # 4. 将图片节点连到视频节点左侧
        if frame_names:
            left_args = []
            for fn in frame_names:
                left_args.extend(["--left", fn])
            link_cmd = [LIBTV_CLI_PATH, "node", node_name] + left_args + ["-p", LIBTV_PROJECT_UUID]
            proc = subprocess.run(link_cmd, capture_output=True, text=True, timeout=30, env=env)
            if proc.returncode != 0:
                return {"success": False, "error": f"连边失败: {proc.stderr[:300]}"}

        # 5. 触发生成（同步等待，约 2-5 分钟）
        run_cmd = [LIBTV_CLI_PATH, "node", node_name, "--run", "-p", LIBTV_PROJECT_UUID]
        proc = subprocess.run(run_cmd, capture_output=True, text=True, timeout=600, env=env)
        if proc.returncode != 0:
            return {"success": False, "error": f"生成失败: {proc.stderr[:300]}"}

        # 6. 解析结果
        result = json.loads(proc.stdout)
        video_url = result.get("data", {}).get("url", [None])[0]
        if not video_url:
            return {"success": False, "error": "生成完成但未获取到视频 URL"}

        return {"success": True, "video_url": video_url, "model": model, "node_name": node_name}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "LibTV 生成超时（超过 10 分钟）"}
    except Exception as e:
        return {"success": False, "error": f"LibTV 生成异常: {str(e)}"}


# ─── 即梦（Jimeng）fast VIP 相关 ─────────────────────────────────
# 即梦 fast VIP 走火山方舟平台（和 Seedance 2.5 同一套接口），只需 API Key
JIMENG_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9"}


def jimeng_submit_video(api_key: str, model_id: str, prompt: str, local_paths: list[str], ratio: str, duration: int) -> dict:
    """提交即梦 fast VIP 图生视频任务（复用方舟接口），返回 task_id 或错误。"""
    if not api_key:
        return {"success": False, "error": "未提供即梦 API Key"}
    if not local_paths:
        return {"success": False, "error": "没有可用的关键帧图片"}

    if ratio not in JIMENG_RATIOS:
        ratio = "1:1"

    image_uri = local_file_to_data_uri(local_paths[0])
    if not image_uri:
        return {"success": False, "error": f"无法读取本地图片: {local_paths[0]}"}

    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_uri}, "role": "first_frame"},
    ]
    if len(local_paths) >= 2:
        tail_uri = local_file_to_data_uri(local_paths[-1])
        if tail_uri:
            content.append({"type": "image_url", "image_url": {"url": tail_uri}, "role": "last_frame"})

    body = {
        "model": model_id or "Doubao-Seedance-2.0-fast",
        "content": content,
        "resolution": "720p",
        "ratio": ratio,
        "duration": duration,
    }

    status, parsed, raw = _http_request(
        ARK_VIDEO_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST", body=body,
    )

    if status not in (200, 201, 202):
        err = parsed.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code") or raw[:300]
        else:
            msg = parsed.get("message") or raw[:300] or f"HTTP {status}"
        return {"success": False, "error": f"提交任务失败: {msg}"}

    task_id = parsed.get("id") or parsed.get("task_id")
    if not task_id:
        return {"success": False, "error": f"未获取到 task_id: {raw[:300]}"}

    return {"success": True, "task_id": task_id, "model": model_id or "Doubao-Seedance-2.0-fast"}


def jimeng_poll_task(api_key: str, task_id: str) -> dict:
    """轮询即梦 fast VIP 任务状态（复用方舟接口）。"""
    url = f"{ARK_TASK_ENDPOINT}/{task_id}"
    status, parsed, raw = _http_request(
        url, headers={"Authorization": f"Bearer {api_key}"}, method="GET",
    )

    jimeng_status = (parsed.get("status") or "").lower()

    if jimeng_status in ("succeeded", "success"):
        content = parsed.get("content") or {}
        video_url = content.get("video_url") or content.get("url") or ""
        if not video_url:
            urls = content.get("video_urls") or []
            video_url = urls[0] if urls else ""
        return {"success": True, "status": "succeeded", "video_url": video_url}

    if jimeng_status in ("failed", "cancelled", "canceled"):
        err = parsed.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else (raw[:300] or "任务失败")
        return {"success": False, "error": msg, "status": jimeng_status}

    return {"success": True, "status": "running", "task_status": jimeng_status or "queued"}


# ─── API 路由 ────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "dianzai-motion-tool.html")


@app.route("/intro")
def intro():
    return send_from_directory(".", "dianzai-motion-intro.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    print(f"[UPLOAD] 收到上传请求 from {request.remote_addr}")
    if "file" not in request.files:
        print("[UPLOAD] 错误: 未提供文件")
        return jsonify({"success": False, "error": "未提供文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        print("[UPLOAD] 错误: 文件名为空")
        return jsonify({"success": False, "error": "文件名为空"}), 400

    if not allowed_file(file.filename):
        print(f"[UPLOAD] 错误: 不支持的格式 {file.filename}")
        return jsonify({"success": False, "error": "仅支持 PNG/JPG 格式"}), 400

    filename = secure_filename(file.filename)
    local_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(local_path)
    # 记录本地路径，供 DashScope / Kling / Ark 生成时取回
    UPLOADED_FILES[filename] = local_path
    print(f"[UPLOAD] 文件已保存: {local_path}")

    # 尝试上传到美境 S3（仅 Seedance 美境模型需要）
    # 失败不阻塞，前端使用非美境模型时不需要 remote_url
    remote_url = None
    try:
        remote_url = upload_to_s3(local_path)
        if remote_url:
            print(f"[UPLOAD] 美境 S3 上传成功: {remote_url[:80]}...")
        else:
            print("[UPLOAD] 美境 S3 上传失败（未登录或网络异常），但本地文件已保存，非美境模型仍可正常使用")
    except Exception as e:
        print(f"[UPLOAD] 美境 S3 上传异常: {e}")

    return jsonify({"success": True, "url": remote_url, "filename": filename})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """美境 Seedance 视频生成（原有逻辑）。"""
    print(f"[GENERATE] 收到生成请求 from {request.remote_addr}")
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    model = data.get("model", "doubao-seedance-2.0")
    print(f"[GENERATE] model={model}, prompt_len={len(prompt)}")

    if not prompt:
        print("[GENERATE] 错误: prompt 为空")
        return jsonify({"success": False, "error": "prompt 不能为空"}), 400

    result = generate_task(prompt, model=model)
    print(f"[GENERATE] 结果: success={result.get('success')}, error={result.get('error', '')}")
    return jsonify(result)


@app.route("/api/meigen-status")
def api_meigen_status():
    """查询本机 meigen-cli 登录状态，供前端判断美境模型是否可用。"""
    try:
        proc = subprocess.run(
            ["meigen", "status", "--json"],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(proc.stdout)
        return jsonify({
            "success": True,
            "logged_in": bool(data.get("token_valid")),
            "mis_id": data.get("mis_id", ""),
        })
    except Exception as e:
        return jsonify({"success": False, "logged_in": False, "error": str(e)})


@app.route("/api/poll/<int:session_id>/<int:assistant_message_id>")
def api_poll(session_id: int, assistant_message_id: int):
    result = poll_video(session_id, assistant_message_id)
    return jsonify(result)


@app.route("/api/generate-dashscope", methods=["POST"])
def api_generate_dashscope():
    """阿里云百炼 Happy Horse 1.1 视频生成。"""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    api_key = data.get("api_key", "").strip()
    filenames = data.get("filenames", [])  # 前端传来的文件名列表
    ratio = data.get("ratio", "1:1")
    duration = int(data.get("duration", 5))

    if not prompt:
        return jsonify({"success": False, "error": "prompt 不能为空"}), 400
    if not api_key:
        return jsonify({"success": False, "error": "请先在页面填入阿里云百炼 API Key"}), 400

    # 根据文件名找回本地路径
    local_paths = []
    for fn in filenames:
        lp = UPLOADED_FILES.get(fn)
        if lp:
            local_paths.append(lp)

    if not local_paths:
        return jsonify({"success": False, "error": "未找到已上传的关键帧，请重新上传后再试"}), 400

    result = dashscope_submit_video(api_key, prompt, local_paths, ratio, duration)
    return jsonify(result)


@app.route("/api/poll-dashscope/<task_id>")
def api_poll_dashscope(task_id: str):
    api_key = request.args.get("api_key", "").strip()
    if not api_key:
        return jsonify({"success": False, "error": "缺少 API Key"}), 400
    result = dashscope_poll_task(api_key, task_id)
    return jsonify(result)


@app.route("/api/generate-kling", methods=["POST"])
def api_generate_kling():
    """可灵 Kling 3.0 视频生成。"""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    access_key = data.get("access_key", "").strip()
    secret_key = data.get("secret_key", "").strip()
    filenames = data.get("filenames", [])
    ratio = data.get("ratio", "1:1")
    duration = int(data.get("duration", 5))

    if not prompt:
        return jsonify({"success": False, "error": "prompt 不能为空"}), 400
    if not access_key or not secret_key:
        return jsonify({"success": False, "error": "请先在页面填入可灵 AccessKey 和 SecretKey"}), 400

    local_paths = [UPLOADED_FILES[fn] for fn in filenames if UPLOADED_FILES.get(fn)]
    if not local_paths:
        return jsonify({"success": False, "error": "未找到已上传的关键帧，请重新上传后再试"}), 400

    result = kling_submit_video(access_key, secret_key, prompt, local_paths, ratio, duration)
    return jsonify(result)


@app.route("/api/poll-kling/<task_id>")
def api_poll_kling(task_id: str):
    access_key = request.args.get("access_key", "").strip()
    secret_key = request.args.get("secret_key", "").strip()
    if not access_key or not secret_key:
        return jsonify({"success": False, "error": "缺少可灵密钥"}), 400
    result = kling_poll_task(access_key, secret_key, task_id)
    return jsonify(result)


@app.route("/api/generate-ark", methods=["POST"])
def api_generate_ark():
    """火山方舟即梦 Seedance 2.5 视频生成。"""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    api_key = data.get("api_key", "").strip()
    model_id = data.get("model_id", "Doubao-Seedance-2.5").strip()
    filenames = data.get("filenames", [])
    ratio = data.get("ratio", "1:1")
    duration = int(data.get("duration", 5))

    if not prompt:
        return jsonify({"success": False, "error": "prompt 不能为空"}), 400
    if not api_key:
        return jsonify({"success": False, "error": "请先在页面填入火山方舟 API Key"}), 400

    local_paths = [UPLOADED_FILES[fn] for fn in filenames if UPLOADED_FILES.get(fn)]
    if not local_paths:
        return jsonify({"success": False, "error": "未找到已上传的关键帧，请重新上传后再试"}), 400

    result = ark_submit_video(api_key, model_id, prompt, local_paths, ratio, duration)
    return jsonify(result)


@app.route("/api/poll-ark/<task_id>")
def api_poll_ark(task_id: str):
    api_key = request.args.get("api_key", "").strip()
    if not api_key:
        return jsonify({"success": False, "error": "缺少 API Key"}), 400
    result = ark_poll_task(api_key, task_id)
    return jsonify(result)


@app.route("/api/generate-jimeng", methods=["POST"])
def api_generate_jimeng():
    """即梦 Jimeng Seedance 2.0 fast VIP 视频生成（火山方舟平台）。"""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    api_key = data.get("api_key", "").strip()
    model_id = data.get("model_id", "").strip()
    filenames = data.get("filenames", [])
    ratio = data.get("ratio", "1:1")
    duration = int(data.get("duration", 5))

    if not prompt:
        return jsonify({"success": False, "error": "prompt 不能为空"}), 400
    if not api_key:
        return jsonify({"success": False, "error": "请先在页面填入即梦 API Key"}), 400

    local_paths = [UPLOADED_FILES[fn] for fn in filenames if UPLOADED_FILES.get(fn)]
    if not local_paths:
        return jsonify({"success": False, "error": "未找到已上传的关键帧，请重新上传后再试"}), 400

    result = jimeng_submit_video(api_key, model_id, prompt, local_paths, ratio, duration)
    return jsonify(result)


@app.route("/api/poll-jimeng/<task_id>")
def api_poll_jimeng(task_id: str):
    api_key = request.args.get("api_key", "").strip()
    if not api_key:
        return jsonify({"success": False, "error": "缺少 API Key"}), 400
    result = jimeng_poll_task(api_key, task_id)
    return jsonify(result)


@app.route("/api/download-video", methods=["POST"])
def api_download_video():
    """从视频 URL 下载到本地 static/videos/ 目录，返回本地可访问路径。"""
    data = request.get_json(force=True)
    video_url = data.get("video_url", "").strip()
    if not video_url:
        return jsonify({"success": False, "error": "缺少 video_url"}), 400

    # 生成唯一文件名
    ext = os.path.splitext(video_url.split("?")[0])[-1] or ".mp4"
    if ext not in (".mp4", ".mov", ".avi", ".webm"):
        ext = ".mp4"
    filename = f"video_{uuid.uuid4().hex[:8]}_{int(time.time())}{ext}"

    local_path = download_video_file(video_url, filename)
    if not local_path:
        return jsonify({"success": False, "error": "视频下载失败，请检查 URL 是否有效"}), 500

    return jsonify({
        "success": True,
        "local_url": f"/static/videos/{filename}",
        "filename": filename,
    })


# ─── LibTV API 路由 ──────────────────────────────────────────────

@app.route("/api/libtv-status")
def api_libtv_status():
    """查询 libtv CLI 安装和登录状态"""
    return jsonify(check_libtv_available())


@app.route("/api/libtv-install", methods=["POST"])
def api_libtv_install():
    """安装 libtv CLI"""
    if os.path.isfile(LIBTV_CLI_PATH):
        return jsonify({"success": True, "message": "libtv CLI 已存在"})
    result = install_libtv_cli()
    return jsonify(result)


@app.route("/api/generate-libtv", methods=["POST"])
def api_generate_libtv():
    """LibTV 视频生成。"""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    filenames = data.get("filenames", [])
    ratio = data.get("ratio", "1:1")
    duration = int(data.get("duration", 5))
    model = data.get("model", "Seedance 2.5")

    if not prompt:
        return jsonify({"success": False, "error": "prompt 不能为空"}), 400

    # 根据文件名找回本地路径
    local_paths = [UPLOADED_FILES[fn] for fn in filenames if UPLOADED_FILES.get(fn)]
    if not local_paths:
        return jsonify({"success": False, "error": "未找到已上传的关键帧，请重新上传后再试"}), 400

    result = libtv_submit_video(prompt, local_paths, ratio, duration, model)
    return jsonify(result)


# ─── 主入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  点仔动效生成工具 - 本地服务")
    print("  访问地址: http://localhost:5000")
    print("=" * 60)
    print()
    print("已接入 LibTV（LiblibAI 视频创作平台），请在 Railway 上完成安装与登录。")
    print("首次使用 meigen-cli 可能需要在大象中确认授权。")
    print("使用 Happy Horse 1.1 需在页面填入阿里云百炼 API Key。")
    print("使用可灵 Kling 3.0 需填入 AccessKey + SecretKey；即梦 fast VIP 需火山引擎 AccessKey + SecretKey；Seedance 2.5 需火山方舟 API Key。")
    print()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
