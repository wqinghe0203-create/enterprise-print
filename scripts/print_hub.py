"""WorkBuddy client for the company Print Hub. Requires Python 3.9+ only."""

import argparse
import base64
from datetime import date
import getpass
import hashlib
import hmac
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import ssl
import sys
from urllib.parse import urlencode
import uuid
import webbrowser


HOST = "10.0.249.200"
PORT = 8086
BASE_URL = f"https://{HOST}:{PORT}"
# This leaf fingerprint was confirmed by the user for this endpoint.
APPROVED_CERTS = {
    ("10.0.249.200", 8086): "df7eb514b9f05941d6f85bc6aaf3e2d50b88b24188502088a96ee8acdaaafe6a",
}
VIEWS = ("history", "overview", "devices", "queue", "new-print")
DUPLEX = {
    "auto": "按打印机默认设置", "simplex": "单面",
    "duplex_long": "长边双面", "duplex_short": "短边双面",
}
STATUS = {
    "queued": "已排队，等待发送到打印机。", "converting": "正在转换文档。",
    "sending": "正在发送到打印机。", "submitted": "已提交，等待设备确认。",
    "printing": "设备正在打印。", "completed": "设备已确认完成。",
    "failed": "打印失败。", "canceled": "任务已取消。", "paused": "任务已暂停。",
    "unknown": "打印结果暂未确认。", "unconfirmed": "打印结果尚未核实。",
}


class HubError(Exception):
    def __init__(self, message, *, code="error", uncertain=False, request_id=None):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain
        self.request_id = request_id


def auth_headers(admin):
    username = os.getenv("PRINT_HUB_BASIC_USER", "")
    password = os.getenv("PRINT_HUB_BASIC_PASSWORD", "")
    headers = {"Accept": "application/json"}
    if username or password:
        if not username or not password or ":" in username:
            raise HubError("请配置完整的 Print Hub 后台登录账号和密码。", code="auth_config")
        encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    token = os.getenv("PRINT_HUB_API_TOKEN")
    admin_token = os.getenv("PRINT_HUB_ADMIN_TOKEN")
    if token:
        headers["X-Print-Hub-Token"] = token
    if admin and admin_token:
        headers["X-Print-Hub-Admin-Token"] = admin_token
    return headers


def connect(timeout):
    ca_file = os.getenv("PRINT_HUB_CA_FILE")
    override = os.getenv("PRINT_HUB_CERT_SHA256", "").strip()
    if override:
        pin = override.replace(":", "").lower()
    else:
        pin = None if ca_file else APPROVED_CERTS.get((HOST, PORT))
    if override and not re.fullmatch(r"[a-f0-9]{64}", pin):
        raise HubError("PRINT_HUB_CERT_SHA256 应填写管理员提供的证书 SHA-256 指纹。", code="tls_config")
    if pin:
        # In pin mode the leaf certificate is checked before sending any HTTP data.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        context = ssl.create_default_context(cafile=ca_file or None)
    connection = http.client.HTTPSConnection(HOST, PORT, timeout=timeout, context=context)
    try:
        connection.connect()
        if pin:
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(pin, actual):
                raise HubError("后台证书与已确认的指纹不符。请向管理员核对是否换证，再更新指纹配置。", code="tls_pin_mismatch")
        return connection
    except BaseException:
        connection.close()
        raise


def api(path, *, params=None, method="GET", body=None, content_type=None, admin=False):
    headers = auth_headers(admin)
    if content_type:
        headers["Content-Type"] = content_type
    if params:
        path += "?" + urlencode({key: value for key, value in params.items() if value is not None})
    try:
        connection = connect(timeout=60 if body is not None else 20)
    except ssl.SSLCertVerificationError as exc:
        raise HubError("无法验证后台证书，请配置公司 CA 或管理员提供的证书指纹。", code="tls_untrusted") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise HubError(f"无法连接 Print Hub：{exc}", code="connect_failed") from exc

    write = method != "GET"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise HubError(f"未取得后台响应：{exc}", code="no_response", uncertain=write) from exc
    finally:
        connection.close()

    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        result = None
    error = result.get("error") if isinstance(result, dict) else None
    if response.status == 401:
        challenge = response.getheader("WWW-Authenticate", "")
        message = "请在 WorkBuddy 执行环境配置后台登录账号和密码。" if "basic" in challenge.lower() else "请检查 Print Hub API 访问令牌。"
        raise HubError(message, code="unauthorized")
    if response.status == 403:
        raise HubError(error or "当前账号无权执行该操作，请核对后台权限或管理员令牌。", code="forbidden")
    if not 200 <= response.status < 300:
        uncertain = write and (response.status >= 500 or response.status == 408 or 300 <= response.status < 400)
        raise HubError(error or f"后台返回 HTTP {response.status}。", code=f"http_{response.status}", uncertain=uncertain)
    if not isinstance(result, (dict, list)):
        raise HubError("后台没有返回可识别的 JSON。", code="invalid_response", uncertain=write)
    if isinstance(result, dict) and result.get("success") is False:
        raise HubError(error or "后台拒绝了该操作。", code="rejected")
    return result


def printer_id(keyword):
    if not keyword:
        return None
    key = keyword.strip().casefold()
    cluster = api("/api/cluster")
    if not isinstance(cluster, list):
        raise HubError("后台返回了无法识别的设备列表。", code="invalid_response")
    for field in ("id", "name"):
        exact = [p for p in cluster if str(p.get(field, "")).casefold() == key]
        if len(exact) == 1:
            return exact[0]["id"]
    matches = [p for p in cluster if any(key in str(p.get(f, "")).casefold() for f in ("name", "location", "model"))]
    if len(matches) == 1:
        return matches[0]["id"]
    if matches:
        choices = "、".join(f"{p.get('name')}（{p.get('location')}，{p['id']}）" for p in matches)
        raise HubError(f"设备名称有多个匹配，请指定设备 ID。匹配结果为 {choices}。", code="ambiguous_printer")
    raise HubError(f"未找到打印机 {keyword}。", code="printer_not_found")


def multipart(fields, filename, content, mime_type):
    boundary = uuid.uuid4().hex
    safe_name = re.sub(r'[\x00-\x1f\x7f"/\\]', "_", filename)
    chunks = []
    for name, value in fields.items():
        if value is not None:
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
                   f"Content-Type: {mime_type}\r\n\r\n").encode("utf-8"))
    chunks.extend((content, f"\r\n--{boundary}--\r\n".encode("ascii")))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def job_result(result):
    if not isinstance(result, dict):
        raise HubError("后台没有返回可识别的任务记录。", code="invalid_response")
    job = result.get("job")
    if not isinstance(job, dict) or not job.get("id"):
        return {"job": None}
    status = job.get("status")
    if status == "completed" and job.get("completion_verified") is not True:
        status = "unconfirmed"
    display = {"status_zh": STATUS.get(status, STATUS["unconfirmed"]),
               "duplex_zh": DUPLEX.get(job.get("duplex"))}
    fields = ("id", "request_id", "filename", "printer_id", "printer_name", "printer_location", "user", "copies",
              "pages", "page_count", "duplex", "priority", "status", "completion_verified", "error_msg")
    return {"job": {key: job[key] for key in fields if key in job}, "display": display}


def task(job_id=None, request_id=None, verify=False):
    params = {"request_id": request_id} if request_id else {"job_id": job_id}
    if verify:
        params["verify"] = 1
    return job_result(api("/api/task", params=params))


def submit(args):
    if args.command == "print-text":
        text = Path(args.text_file).read_bytes().decode("utf-8-sig") if args.text_file else sys.stdin.buffer.read().decode("utf-8-sig")
        if not text.strip():
            raise HubError("请提供要打印的正文。", code="empty_text")
        filename = args.title if args.title.lower().endswith(".txt") else args.title + ".txt"
        content, mime_type = text.encode("utf-8"), "text/plain; charset=utf-8"
    else:
        file = Path(args.file)
        filename, content = file.name, file.read_bytes()
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if not content:
            raise HubError("打印文件为空。", code="empty_file")

    if args.request_id:
        previous = task(request_id=args.request_id)
        if previous["job"]:
            return {"request_id": args.request_id, **previous}
    request_id = args.request_id or uuid.uuid4().hex
    user = args.user or os.getenv("PRINT_HUB_DEFAULT_USER") or getpass.getuser()
    fields = {"request_id": request_id, "printer": printer_id(args.printer), "user": user,
              "copies": args.copies, "duplex": args.duplex, "priority": args.priority}
    body, content_type = multipart(fields, filename, content, mime_type)
    try:
        response = api("/api/upload_print", method="POST", body=body, content_type=content_type)
        result = job_result(response)
        if not result["job"]:
            raise HubError("后台未返回任务编号。", code="missing_job", uncertain=True)
        return {"request_id": request_id, **result}
    except HubError as exc:
        if exc.code == "invalid_response":
            exc.uncertain = True
        if exc.uncertain:
            try:
                result = task(request_id=request_id)
                if result["job"]:
                    return {"request_id": request_id, **result}
            except HubError:
                pass
            exc.request_id = request_id
        raise


def number(minimum, maximum=None):
    def validate(value):
        try:
            result = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("必须为整数。") from exc
        if result < minimum or (maximum is not None and result > maximum):
            raise argparse.ArgumentTypeError(f"须大于等于 {minimum}。" if maximum is None else f"须在 {minimum} 到 {maximum} 之间。")
        return result
    return validate


def valid_request_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise argparse.ArgumentTypeError("提交标识应为 1–100 个英文字母、数字、横线或下划线。")
    return value


def parser():
    root = argparse.ArgumentParser(description="WorkBuddy Print Hub 客户端")
    commands = root.add_subparsers(dest="command", required=True)
    browser = commands.add_parser("open", help="获取或打开后台页面")
    browser.add_argument("--page", choices=VIEWS, default="history")
    browser.add_argument("--browser", action="store_true", help="请求系统默认浏览器打开页面")
    commands.add_parser("printers", help="列出设备")
    commands.add_parser("converter", help="查看文档转换服务")
    for name in ("status", "queue", "diag"):
        query = commands.add_parser(name)
        query.add_argument("--printer")
    history = commands.add_parser("history")
    history.add_argument("--printer")
    history.add_argument("--search")
    history.add_argument("--user")
    history.add_argument("--status", choices=tuple(STATUS))
    history.add_argument("--start", type=date.fromisoformat)
    history.add_argument("--end", type=date.fromisoformat)
    history.add_argument("--page", type=number(1), default=1)
    history.add_argument("--size", type=int, choices=(5, 10, 20), default=5)
    for name in ("print-file", "print-text"):
        job = commands.add_parser(name)
        if name == "print-file":
            job.add_argument("--file", required=True)
        else:
            job.add_argument("--text-file", help="UTF-8 文本文件，省略时从标准输入读取 UTF-8")
            job.add_argument("--title", default="对话文本", help="任务记录中的文件名")
        job.add_argument("--printer")
        job.add_argument("--user")
        job.add_argument("--copies", type=number(1, 99), default=1)
        job.add_argument("--duplex", choices=tuple(DUPLEX), default="auto")
        job.add_argument("--priority", type=number(1, 100), default=50)
        job.add_argument("--request-id", type=valid_request_id)
    detail = commands.add_parser("task")
    identity = detail.add_mutually_exclusive_group(required=True)
    identity.add_argument("--job-id", type=number(1))
    identity.add_argument("--request-id", type=valid_request_id)
    detail.add_argument("--verify", action="store_true")
    for name in ("cancel", "priority", "cut-in"):
        action = commands.add_parser(name)
        action.add_argument("--job-id", type=number(1), required=True)
        if name == "priority":
            action.add_argument("--priority", type=number(1, 100), required=True)
    commands.add_parser("set-default").add_argument("--printer", required=True)
    return root


def run(args):
    name = args.command
    if name == "open":
        url = f"{BASE_URL}/#{args.page}"
        return {"url": url, "browser_open_requested": webbrowser.open(url) if args.browser else False}
    if name in ("print-file", "print-text"):
        return submit(args)
    if name == "task":
        return task(args.job_id, args.request_id, args.verify)
    if name in ("printers", "converter"):
        path = "/api/cluster" if name == "printers" else "/api/converter-status"
        return {name: api(path)}
    if name == "history":
        if args.start and args.end and args.start > args.end:
            raise HubError("开始日期须早于或等于结束日期。", code="invalid_date_range")
        filters = {key: getattr(args, key) for key in ("search", "user", "status", "start", "end", "page", "size")}
        filters["printer_id"] = printer_id(args.printer)
        return api("/api/history", params=filters)
    if name in ("status", "queue", "diag", "set-default"):
        params = {"printer_id": printer_id(args.printer)}
        if name == "diag":
            return api("/api/diag", params=params)
        if name == "set-default":
            if not params["printer_id"]:
                raise HubError("请指定要设为默认的打印机。")
            return api("/api/default-printer", params=params, method="POST", admin=True)
        data = api("/api/dashboard", params=params)
        fields = ["printer", "active_printing"]
        if name == "queue":
            fields.extend(("virtual_queue", "hw_active_jobs"))
        return {key: data.get(key) for key in fields}
    params = {"job_id": args.job_id}
    if name == "priority":
        params["priority"] = args.priority
    if name == "cancel":
        params["is_hw"] = "false"
    return api("/api/" + name.replace("-", "_"), params=params, method="POST")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    try:
        result = {"success": True, **run(args)}
    except HubError as exc:
        result = {"success": False, "code": exc.code, "error": str(exc), "uncertain": exc.uncertain}
        if exc.request_id:
            result["request_id"] = exc.request_id
    except UnicodeDecodeError:
        result = {"success": False, "error": "正文文件须使用 UTF-8 编码。"}
    except (OSError, ValueError) as exc:
        result = {"success": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
