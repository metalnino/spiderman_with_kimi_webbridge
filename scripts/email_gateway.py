"""邮件网关（Gmail）：SMTP 发信 + IMAP 收信 + 短信验证码提取。

凭据：项目 .env 的 GMAIL_USER + GMAIL_APP_PASSWORD（SMTP 发信）与
GMAIL_IMAP_PASSWORD（IMAP 收信，缺省回退发信密码；Gmail 需开启 IMAP）；
默认收件人 EMAIL_TO（缺省 279152260@qq.com）。

代理：Python 的 smtplib/imaplib 不走系统代理，国内直连 Gmail 不稳定。本网关支持
HTTP CONNECT 隧道：代理取 .env EMAIL_PROXY > 环境变量 SPIDER_PROXY > 系统代理设置
（urllib getproxies，如 Clash/Ikuuu 的 127.0.0.1:63009）；无代理则直连。
安全：凭据只放 .env（已 gitignore）；收信只按主题 tag 过滤，不读无关邮件。
"""
from __future__ import annotations

import email
import imaplib
import re
import smtplib
import socket
import ssl
import sys
import unicodedata
import urllib.request
from email.header import decode_header
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import load_env  # noqa: E402


def creds() -> tuple[str, str]:
    """SMTP 发信凭据（.env GMAIL_USER / GMAIL_APP_PASSWORD）。"""
    env = load_env()
    return (env.get("GMAIL_USER") or "").strip(), (env.get("GMAIL_APP_PASSWORD") or "").strip()


def imap_creds() -> tuple[str, str]:
    """IMAP 收信凭据（.env GMAIL_USER / GMAIL_IMAP_PASSWORD，缺省回退 GMAIL_APP_PASSWORD）。"""
    env = load_env()
    user = (env.get("GMAIL_USER") or "").strip()
    pw = (env.get("GMAIL_IMAP_PASSWORD") or env.get("GMAIL_APP_PASSWORD") or "").strip()
    return user, pw


def qq_creds() -> tuple[str, str]:
    """QQ 邮箱凭据（.env EMAIL_USER 缺省 279152260@qq.com / EMAIL_PASSWORD=QQ 授权码）。"""
    env = load_env()
    user = (env.get("EMAIL_USER") or "279152260@qq.com").strip()
    pw = (env.get("EMAIL_PASSWORD") or "").strip()
    return user, pw


def provider() -> str:
    """EMAIL_PROVIDER：qq|gmail，默认 gmail；qq 用于 Gmail 被网络封锁的环境。"""
    return (load_env().get("EMAIL_PROVIDER") or "gmail").strip().lower()


def _endpoints(p: str) -> dict:
    if p == "qq":
        return {"smtp_host": "smtp.qq.com", "smtp_port": 465, "imap_host": "imap.qq.com", "imap_port": 993}
    return {"smtp_host": "smtp.gmail.com", "smtp_port": 465, "imap_host": "imap.gmail.com", "imap_port": 993}


def default_to() -> str:
    return (load_env().get("EMAIL_TO") or "279152260@qq.com").strip()


def proxy() -> str | None:
    """http://host:port 代理串；优先级 .env EMAIL_PROXY > env SPIDER_PROXY > 系统代理。"""
    import os

    val = load_env().get("EMAIL_PROXY") or os.environ.get("SPIDER_PROXY")
    if val:
        return val.strip()
    try:
        sys_proxy = urllib.request.getproxies().get("http") or urllib.request.getproxies().get("https")
    except Exception:
        sys_proxy = None
    return (sys_proxy or "").strip() or None


def _tunnel_raw_socket(target_host: str, target_port: int, timeout: int = 30) -> socket.socket:
    """HTTP CONNECT 隧道：经代理建到目标主机的裸 TCP 通道（返回未加 TLS 的 socket）。"""
    from urllib.parse import urlparse

    p = proxy()
    if not p:
        raise RuntimeError("no_proxy")
    parsed = urlparse(p if "://" in p else f"http://{p}")
    ph, pp = parsed.hostname, parsed.port or 80
    s = socket.create_connection((ph, pp), timeout=timeout)
    s.sendall(f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n\r\n".encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            s.close()
            raise RuntimeError("proxy_closed_during_connect")
        buf += chunk
    head = buf.split(b"\r\n\r\n", 1)[0]
    status = head.split(b" ")[1] if len(head.split(b" ")) > 1 else b""
    if status != b"200":
        s.close()
        raise RuntimeError(f"proxy_connect_failed: {head[:160]!r}")
    return s


class _TunneledSMTP_SSL(smtplib.SMTP_SSL):
    """经 HTTP CONNECT 隧道建连的 SMTP_SSL。"""

    def _get_socket(self, host, port, timeout):
        return _tunnel_raw_socket(host, port, timeout)


class _TunneledIMAP4_SSL(imaplib.IMAP4_SSL):
    """经 HTTP CONNECT 隧道建连的 IMAP4_SSL。"""

    def _create_socket(self, timeout):
        raw = _tunnel_raw_socket(self.host, int(self.port), timeout)
        ctx = ssl.create_default_context()
        return ctx.wrap_socket(raw, server_hostname=self.host)


def _smpt_attempt(host: str, port: int, user: str, app_pw: str, msg, use_tunnel: bool | None = None) -> tuple[bool, str]:
    if use_tunnel is None:
        use_tunnel = port == 465 and bool(proxy())
    cls = _TunneledSMTP_SSL if use_tunnel else smtplib.SMTP_SSL
    with cls(host, port, timeout=30) as s:
        s.login(user, app_pw)
        s.send_message(msg)
    return True, f"{host}:{port}" + ("(proxy)" if use_tunnel else "")


def _resolve_sender(p: str) -> tuple[tuple[str, str], str]:
    """发件凭据 + 缺凭据时的提示 key（.env 里应填哪个）。"""
    if p == "qq":
        return qq_creds(), "EMAIL_USER/EMAIL_PASSWORD(QQ 授权码)"
    return creds(), "GMAIL_USER/GMAIL_APP_PASSWORD"


def _build_message(user: str, to: str, subject: str, body_text: str | None, body_html: str | None):
    """构造邮件：纯文本 / HTML / 两者兼有（multipart/alternative）。"""
    msg = email.message.EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    if body_html:
        if body_text:
            msg.set_content(body_text)
            msg.add_alternative(body_html, subtype="html")
        else:
            msg.set_content(body_html, subtype="html")
    else:
        msg.set_content(body_text or "")
    return msg


def _send_message(user: str, app_pw: str, ep: dict, msg) -> dict:
    """SMTP 发信：有代理先走代理隧道，失败回退直连。返回 {ok, host|error}。"""
    host, port = ep["smtp_host"], ep["smtp_port"]
    attempts: list[tuple[str, int, bool]] = []
    if proxy():
        attempts.append((host, port, True))  # 代理 CONNECT 隧道
    attempts.append((host, port, False))  # 直连兜底
    last = ""
    for h, p, use_tunnel in attempts:
        try:
            ok, label = _smpt_attempt(h, p, user, app_pw, msg, use_tunnel=use_tunnel)
            if ok:
                return {"ok": True, "host": label}
        except Exception as e:  # noqa: BLE001
            last = str(e)[:200]
    return {"ok": False, "error": last}


def send_mime(to: str, subject: str, *, body_text: str | None = None, body_html: str | None = None) -> dict:
    """发信通用入口：body_text / body_html 至少其一。返回 {ok, host|error}。"""
    p = provider()
    ep = _endpoints(p)
    (user, app_pw), key = _resolve_sender(p)
    if not user or not app_pw:
        return {"ok": False, "error": f"no_credentials: .env 缺 {key}"}
    msg = _build_message(user, to, subject, body_text, body_html)
    return _send_message(user, app_pw, ep, msg)


def send(to: str, subject: str, body_text: str) -> dict:
    """纯文本发信（兼容旧接口）。返回 {ok, host|error}。"""
    return send_mime(to, subject, body_text=body_text)


def send_html(to: str, subject: str, body_html: str, body_text: str | None = None) -> dict:
    """HTML 发信（可附纯文本回退）。返回 {ok, host|error}。"""
    return send_mime(to, subject, body_text=body_text, body_html=body_html)


def _imap_session():
    p = provider()
    ep = _endpoints(p)
    user, app_pw = qq_creds() if p == "qq" else imap_creds()
    if not user or not app_pw:
        raise RuntimeError("no_credentials")
    cls = _TunneledIMAP4_SSL if proxy() else imaplib.IMAP4_SSL
    m = cls(ep["imap_host"], ep["imap_port"], timeout=30)
    m.login(user, app_pw)
    m.select("INBOX")
    return m


def imap_status() -> dict:
    """IMAP 连通性/健康检查：返回 {ok, total(收件箱邮件数)|error}。"""
    try:
        m = _imap_session()
        _, data = m.select("INBOX")
        total = int(data[0]) if data and data[0] else 0
        m.logout()
        return {"ok": True, "total": total}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def _dec(v: str | None) -> str:
    if not v:
        return ""
    out = ""
    for part, enc in decode_header(v):
        out += part.decode(enc or "utf-8", "ignore") if isinstance(part, bytes) else part
    return out


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "ignore")
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", "ignore")
    return ""


def poll_replies(subject_tag: str, *, max_mails: int = 20) -> list[dict]:
    """IMAP 拉取主题含 tag 的未读回复（列表，新→旧）。失败返回 []（如实，不炸调用方）。"""
    if not subject_tag:
        return []
    out: list[dict] = []
    try:
        m = _imap_session()
        _, data = m.search(None, "UNSEEN")
        ids = (data[0].split() if data and data[0] else [])[-max_mails:]
        for i in ids:
            _, msg_data = m.fetch(i, "(RFC822)")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            if subject_tag not in _dec(msg.get("Subject")):
                continue
            out.append({
                "uid": i.decode() if isinstance(i, bytes) else str(i),
                "subject": _dec(msg.get("Subject")),
                "from": _dec(msg.get("From")),
                "date": _dec(msg.get("Date")),
                "body": _body_text(msg),
            })
        m.logout()
    except Exception:  # noqa: BLE001 —— IMAP 不通不冒充成功
        return out
    return out


def mark_seen(uids: list[str]) -> None:
    """把已尝试过的回复标为已读（同一封回复绝不重复用于登录重放）。"""
    uids = [u for u in uids if u]
    if not uids:
        return
    try:
        m = _imap_session()
        for uid in uids:
            try:
                m.store(uid, "+FLAGS", "\\Seen")
            except Exception:  # noqa: BLE001
                continue
        m.logout()
    except Exception:  # noqa: BLE001
        return


def extract_code(*texts: str) -> str | None:
    """从主题/正文里提取 4~6 位验证码（NFKC 归一全角数字；跳过 19xx/20xx 年份）。"""
    full = unicodedata.normalize("NFKC", " ".join(t for t in texts if t))
    for m in re.finditer(r"(?<!\d)(\d{4,6})(?!\d)", full):
        code = m.group(1)
        if len(code) == 4 and (code.startswith("19") or code.startswith("20")):
            continue  # 年份不是验证码
        return code
    return None
