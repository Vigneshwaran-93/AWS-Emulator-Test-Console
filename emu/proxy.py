"""Logging reverse proxy: plain HTTP on 127.0.0.1:<proxy_port> -> HTTPS emulator.

Forwards the request byte-for-byte (including the original Host header, so the SigV4 signature stays valid)
and records the raw request/response. External tools (aws cli, curl, other SDKs) can use it too:
    aws --endpoint-url http://127.0.0.1:9390 s3 ls
"""
import http.client
import os
import re
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import docker_ctl
from .state import STATE
from .trace import STORE, body_text

_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
        "transfer-encoding", "upgrade", "x-emu-trace"}
_server = None


def _service_op(method, path, headers, body):
    auth = headers.get("Authorization", "")
    m = re.search(r"Credential=[^/]+/\d+/[^/]+/([^/]+)/aws4_request", auth)
    service = m.group(1) if m else "unknown"
    target = headers.get("X-Amz-Target")
    if target:
        return service, target.split(".")[-1]
    sp = urlsplit(path)
    q = parse_qs(sp.query)
    if "Action" in q:
        return service, q["Action"][0]
    if method == "POST" and body and b"Action=" in body[:4000]:
        m2 = re.search(rb"(?:^|&)Action=([A-Za-z0-9]+)", body)
        if m2:
            return service, m2.group(1).decode()
    return service, f"{method} {sp.path}"


def _decode_chunked(rfile):
    out = b""
    while True:
        line = rfile.readline().strip()
        if not line:
            break
        size = int(line.split(b";")[0], 16)
        if size == 0:
            while rfile.readline().strip():  # trailers
                pass
            break
        out += rfile.read(size)
        rfile.readline()
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _handle(self):
        t0 = time.time()
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            body = _decode_chunked(self.rfile)
        else:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
        req_headers = {k: v for k, v in self.headers.items()}
        link = req_headers.get("X-Emu-Trace")
        service, op = _service_op(self.command, self.path, self.headers, body)
        wire_req = {"line": f"{self.command} {self.path} HTTP/1.1", "headers": req_headers, "body": body_text(body)}

        tid = None
        if not link:
            t = STORE.add(source="proxy", service=service, operation=op, label="via proxy", method=self.command,
                          url=f"http://{self.headers.get('Host')}{self.path}", status=None, ok=None, ms=None,
                          req={"headers": req_headers, "body": body_text(body)}, resp={}, error=None, wire=None)
            tid = t["id"]

        status, rheaders, rbody, err = 502, {}, b"", None
        try:
            ctx = ssl.create_default_context()
            creds = docker_ctl.load_creds()
            if creds and os.path.exists(creds["ca"]):
                ctx.load_verify_locations(creds["ca"])
            else:
                ctx.verify_mode = ssl.CERT_NONE
            ctx.check_hostname = False
            conn = http.client.HTTPSConnection("127.0.0.1", STATE.port, context=ctx, timeout=120)
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for k, v in self.headers.items():
                if k.lower() in _HOP or k.lower() in ("content-length", "expect"):
                    continue
                conn.putheader(k, v)
            if body or self.command in ("POST", "PUT", "PATCH"):
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            r = conn.getresponse()
            rbody = r.read()
            status = r.status
            rheaders = {k: v for k, v in r.getheaders()}
            conn.close()
        except Exception as e:  # noqa
            err = f"proxy upstream error: {type(e).__name__}: {e}"
            rbody = err.encode()

        wire_resp = {"line": f"HTTP/1.1 {status}", "headers": rheaders, "body": body_text(rbody)}
        ms = int((time.time() - t0) * 1000)
        if tid:
            e2 = err
            if not err and status >= 400:
                m = re.search(r'"(?:__type|code|Code)"\s*:\s*"([^"]+)"|<Code>([^<]+)</Code>', wire_resp["body"])
                e2 = (m.group(1) or m.group(2)) if m else f"HTTP {status}"
            STORE.update(tid, status=status, ok=status < 400, ms=ms, resp={"headers": rheaders, "body": wire_resp["body"]}, error=e2)
        elif link and link.isdigit():
            STORE.update(int(link), wire={"request": wire_req, "response": wire_resp, "proxy_ms": ms})

        self.send_response(status)
        for k, v in rheaders.items():
            if k.lower() in _HOP or k.lower() == "content-length":
                continue
            self.send_header(k, v)
        orig_cl = next((v for k, v in rheaders.items() if k.lower() == "content-length"), None)
        self.send_header("Content-Length", orig_cl if (self.command == "HEAD" and orig_cl) else str(len(rbody)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(rbody)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = do_OPTIONS = _handle


def start_proxy():
    global _server
    if _server:
        return True
    try:
        _server = ThreadingHTTPServer(("127.0.0.1", STATE.proxy_port), Handler)
    except OSError as e:
        print(f"[proxy] could not bind port {STATE.proxy_port}: {e}")
        return False
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return True
