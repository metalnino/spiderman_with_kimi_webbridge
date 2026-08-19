"""Kimi WebBridge 本地桥服务端（127.0.0.1:10086）—— 纯 Python 标准库，零安装。

背景：
  本机 Chrome/Edge 已装「Kimi WebBridge」扩展（MV3，chrome.debugger 控真实浏览器）。
  扩展是 WS 客户端，会自动连 ws://127.0.0.1:10086/ws（storage 未关时默认开，每 30s 对账重连）。
  爬虫侧（crawl/webbridge_client.py）POST http://127.0.0.1:10086/command 发命令。
  本服务 = 两者之间的桥：HTTP 命令 → WS tool_call → 扩展执行 → tool_result → HTTP 响应。
  「打开 webbridge」= 启动本服务（浏览器扩展自动连上，无需任何安装）。

协议（自扩展 background.js v1.11.5 逆向）：
  扩展→服务: {type:"hello", payload:{extensionVersion}}
  服务→扩展: {type:"tool_call", requestId, payload:{name,args}}
  扩展→服务: {type:"tool_result", responseToRequestId, payload:{data:...}|{error:...}}
  服务→扩展: {type:"ping"} → 扩展回 {type:"pong"}
  HTTP GET  /command            → {"ok":true} 可用性探针
  HTTP POST /command            body {action,args,session} → {"ok":true,"data":...} / {"ok":false,"error":{code,message}}
  HTTP GET  /                   → 状态文本

运行：python scripts/webbridge_server.py（日志重定向建议 *> data/web/webbridge_server.log）
"""
from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("WEBRIDGE_PORT") or 10086)
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TOOL_TIMEOUT = 95  # 客户端 navigate=45s/evaluate=30s/通用=90s；服务端留余量

_clients: list[dict] = []
_clients_lock = threading.Lock()
_pending: dict[str, tuple[threading.Event, dict]] = {}
_pending_lock = threading.Lock()
_tool_lock = threading.Lock()  # 串行化命令（扩展内部标签页状态非线程安全，且反爬纪律要求串行）
_id_gen = itertools.count(1)


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- WS 编解码 ---

def _read_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def _read_frame(conn: socket.socket):
    hdr = _read_exact(conn, 2)
    fin = hdr[0] & 0x80
    opcode = hdr[0] & 0x0F
    masked = hdr[1] & 0x80
    ln = hdr[1] & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", _read_exact(conn, 2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", _read_exact(conn, 8))[0]
    mask = _read_exact(conn, 4) if masked else None
    payload = _read_exact(conn, ln) if ln else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _send_frame(conn: socket.socket, opcode: int, payload: bytes, *, lock: threading.Lock) -> None:
    b0 = bytes([0x80 | opcode])
    ln = len(payload)
    if ln < 126:
        hdr = b0 + bytes([ln])
    elif ln < 65536:
        hdr = b0 + bytes([126]) + struct.pack(">H", ln)
    else:
        hdr = b0 + bytes([127]) + struct.pack(">Q", ln)
    with lock:
        conn.sendall(hdr + payload)


def _send_json(client: dict, obj: dict) -> None:
    _send_frame(client["conn"], 0x1, json.dumps(obj, ensure_ascii=False).encode("utf-8"), lock=client["send_lock"])


# ---------------------------------------------------------------- 工具调用 ---

def _pick_client() -> dict | None:
    with _clients_lock:
        ready = [c for c in _clients if c.get("ready")]
        return ready[0] if ready else None


def _send_tool(name: str, args: dict) -> dict:
    """向扩展发 tool_call 并等 tool_result。抛 RuntimeError(no_extension) / TimeoutError。"""
    with _tool_lock:  # 串行：一条命令一个往返
        client = _pick_client()
        if not client:
            raise RuntimeError("no_extension")
        req_id = str(next(_id_gen))
        evt = threading.Event()
        box: dict = {}
        with _pending_lock:
            _pending[req_id] = (evt, box)
        try:
            _send_json(client, {"type": "tool_call", "requestId": req_id, "payload": {"name": name, "args": args}})
            if not evt.wait(TOOL_TIMEOUT):
                raise TimeoutError(f"tool {name} timeout after {TOOL_TIMEOUT}s")
        finally:
            with _pending_lock:
                _pending.pop(req_id, None)
        if "error" in box:
            return {"error": box["error"]}
        return {"data": box.get("data")}


def _handle_ws_message(client: dict, msg: dict) -> None:
    t = msg.get("type")
    if t == "hello":
        client["version"] = (msg.get("payload") or {}).get("extensionVersion")
        client["ready"] = True
        _send_json(client, {"type": "hello_ack"})
        log(f"extension connected (version={client.get('version')}) total_clients={len(_clients)}")
    elif t == "pong":
        pass
    elif t == "tool_result":
        req_id = msg.get("responseToRequestId")
        payload = msg.get("payload") or {}
        with _pending_lock:
            item = _pending.get(req_id)
        if item:
            evt, box = item
            box.update(payload)
            evt.set()
        else:
            log(f"orphan tool_result {req_id}")
    else:
        log(f"unhandled ws message type={t}")


def _ws_loop(client: dict) -> None:
    conn = client["conn"]
    try:
        while True:
            opcode, payload = _read_frame(conn)
            if opcode == 0x8:  # close
                break
            if opcode == 0x9:  # ping → pong
                _send_frame(conn, 0xA, payload, lock=client["send_lock"])
                continue
            if opcode == 0x1:  # text
                try:
                    _handle_ws_message(client, json.loads(payload.decode("utf-8")))
                except Exception as e:  # noqa: BLE001
                    log(f"ws message error: {e}")
                continue
            if opcode == 0xA:  # pong
                continue
    except ConnectionError:
        pass
    except Exception as e:  # noqa: BLE001
        log(f"ws client error: {e}")
    finally:
        with _clients_lock:
            if client in _clients:
                _clients.remove(client)
        log(f"extension disconnected (version={client.get('version')}) remaining={len(_clients)}")
        try:
            conn.close()
        except Exception:
            pass


def _ws_upgrade(conn: socket.socket, header_bytes: bytes) -> None:
    """从已读到的 HTTP 请求头完成 101 升级。"""
    headers: dict[str, str] = {}
    lines = header_bytes.decode("latin-1").split("\r\n")
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    key = headers.get("sec-websocket-key")
    if not key:
        raise ValueError("missing sec-websocket-key")
    accept = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()
    conn.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        + ("Sec-WebSocket-Accept: " + accept + "\r\n").encode()
        + b"\r\n"
    )


# ---------------------------------------------------------------- HTTP ---

class Handler(BaseHTTPRequestHandler):
    server_version = "WebBridgeLocal/1.0"

    def log_message(self, fmt, *args):  # 静默默认访问日志（状态在 / 页看）
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/command":
            with _clients_lock:
                ready = [c for c in _clients if c.get("ready")]
            self._json({"ok": True, "bridge": "webbridge-local", "extensions_connected": len(ready)})
            return
        if self.path == "/":
            with _clients_lock:
                ready = [c for c in _clients if c.get("ready")]
            self._json({
                "ok": True,
                "service": "Kimi WebBridge local server",
                "hint": "Chrome/Edge 里的 Kimi WebBridge 扩展会自动连上本服务的 /ws",
                "extensions_connected": len(ready),
            })
            return
        self._json({"ok": False, "error": {"code": "not_found", "message": self.path}}, 404)

    def do_POST(self):  # noqa: N802
        if self.path != "/command":
            self._json({"ok": False, "error": {"code": "not_found", "message": self.path}}, 404)
            return
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(ln) if ln else b""
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": {"code": "bad_request", "message": str(e)}}, 400)
            return
        action = str(data.get("action") or "")
        args = dict(data.get("args") or {})
        session = data.get("session")
        if session:
            args["_session"] = str(session)
        if not action:
            self._json({"ok": False, "error": {"code": "bad_request", "message": "action required"}}, 400)
            return
        log(f"tool_call action={action} session={session}")
        try:
            result = _send_tool(action, args)
        except RuntimeError as e:
            self._json({"ok": False, "error": {"code": str(e), "message": "浏览器扩展未连接：请保持 Chrome/Edge 开着（扩展会自动连）"}}, 503)
            return
        except TimeoutError as e:
            self._json({"ok": False, "error": {"code": "tool_timeout", "message": str(e)}}, 504)
            return
        if "error" in result:
            self._json({"ok": False, "error": {"code": "tool_error", "message": str(result["error"])}})
            return
        self._json({"ok": True, "data": result.get("data")})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def get_request(self):
        conn, addr = super().get_request()
        conn.settimeout(None)
        return conn, addr


def main() -> None:
    # /ws 升级必须在 BaseHTTPRequestHandler 解析请求前拦截：包装 handle_one_request
    orig_handle = BaseHTTPRequestHandler.handle_one_request

    def handle_one_request(self):  # noqa: N802
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            # /ws 升级必须在 parse_request 前拦截（否则头已被消费）
            parts = self.raw_requestline.decode("latin-1", "ignore").split()
            if len(parts) >= 2 and parts[1] == "/ws":
                header_bytes = self.raw_requestline
                while True:
                    line = self.rfile.readline(65537)
                    header_bytes += line
                    if line in (b"\r\n", b"\n", b""):
                        break
                conn = self.connection
                try:
                    _ws_upgrade(conn, header_bytes)
                except Exception as e:  # noqa: BLE001
                    log(f"ws upgrade failed: {e}")
                    return
                client = {"conn": conn, "ready": False, "version": None, "send_lock": threading.Lock()}
                with _clients_lock:
                    _clients.append(client)
                _ws_loop(client)
                return
            if not self.parse_request():
                return
            self.close_connection = True  # HTTP/1.0 风格逐请求关闭（简单可靠）
            mname = "do_" + self.command
            if not hasattr(self, mname):
                self.send_error(501)
                return
            method = getattr(self, mname)
            method()
        except socket.timeout:
            log("request timeout")
        except Exception as e:  # noqa: BLE001
            log(f"request error: {e}")

    BaseHTTPRequestHandler.handle_one_request = handle_one_request

    srv = Server((HOST, PORT), Handler)
    pidfile = os.environ.get("WEBRIDGE_PIDFILE")
    if pidfile:
        try:
            Path(pidfile).write_text(str(os.getpid()), encoding="utf-8")
        except Exception:  # noqa: BLE001 —— pidfile 失败不挡启动
            pass
    log(f"webbridge server listening on http://{HOST}:{PORT} (ws /ws)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("shutdown")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
