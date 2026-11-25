"""boto3 client factory + SDK-level trace hooks (capture modes: sdk | proxy | both)."""
import os
import threading
import time

import boto3
from botocore.config import Config

from . import docker_ctl
from .state import STATE
from .trace import CURRENT_LABEL, CURRENT_TRACE, STORE, body_text

_cache = {}
_lock = threading.Lock()


class NotRunning(Exception):
    pass


def _config():
    kw = dict(retries={"max_attempts": 1}, inject_host_prefix=False, connect_timeout=5, read_timeout=90,
              s3={"addressing_style": "path"})
    try:
        return Config(request_checksum_calculation="when_required",
                      response_checksum_validation="when_required", **kw)
    except TypeError:
        return Config(**kw)


# ----------------------------------------------------------------- hooks
def _before_call(model, params, context, **kw):
    svc = model.service_model
    t = STORE.add(source="sdk", service=svc.service_name, operation=model.name,
                  label=CURRENT_LABEL.get(), method=params.get("method"), url=None,
                  status=None, ok=None, ms=None, req={}, resp={}, error=None, wire=None)
    CURRENT_TRACE.set(t["id"])


def _before_send(request, **kw):
    tid = CURRENT_TRACE.get()
    if not tid:
        return
    if STATE.mode == "both":
        request.headers["X-Emu-Trace"] = str(tid)
    headers = {k: (v.decode() if isinstance(v, bytes) else str(v)) for k, v in request.headers.items()}
    STORE.update(tid, method=request.method, url=request.url,
                 req={"headers": headers, "body": body_text(request.body)}, t0=time.time())


def _after_call(http_response, parsed, model, **kw):
    tid = CURRENT_TRACE.get()
    if not tid:
        return
    t = STORE.get(tid) or {}
    body = ""
    try:
        if model.has_streaming_output:
            body = "<streaming body - not captured in SDK view>"
        elif model.has_event_stream_output:
            body = "<event stream - see Wire view in proxy/both mode>"
        else:
            body = body_text(http_response.content)
    except Exception as e:  # noqa
        body = f"<unreadable: {e}>"
    status = http_response.status_code
    err = None
    if isinstance(parsed, dict) and "Error" in parsed:
        e = parsed["Error"]
        err = f"{e.get('Code')}: {e.get('Message')}"
    STORE.update(tid, status=status, ok=status < 400,
                 resp={"headers": dict(http_response.headers), "body": body}, error=err,
                 ms=int((time.time() - t.get("t0", t.get("ts", time.time()))) * 1000))
    CURRENT_TRACE.set(None)


def _install_hooks(client):
    ev = client.meta.events
    ev.register("before-call.*.*", _before_call)
    ev.register("before-send.*.*", _before_send)
    ev.register("after-call.*.*", _after_call)


# ----------------------------------------------------------------- factory
def get_client(service):
    creds = docker_ctl.load_creds()
    if not creds and STATE.auth:
        raise NotRunning("Emulator is not running (no credentials found). Go to Install & Setup > Run & Control and start it.")
    mode = STATE.mode
    ak = creds["access_key"] if creds else "test"
    key = (service, mode, ak, STATE.port, STATE.proxy_port)
    with _lock:
        if key in _cache:
            return _cache[key]
        sess = boto3.session.Session(aws_access_key_id=ak,
                                     aws_secret_access_key=creds["secret_key"] if creds else "test",
                                     aws_session_token=creds.get("token") if creds else None,
                                     region_name=creds["region"] if creds else "us-east-1")
        if mode == "sdk":
            endpoint = f"https://127.0.0.1:{STATE.port}"
            verify = creds["ca"] if creds and os.path.exists(creds["ca"]) else False
        else:
            endpoint = f"http://127.0.0.1:{STATE.proxy_port}"
            verify = False
        client = sess.client(service, endpoint_url=endpoint, verify=verify, config=_config())
        if mode in ("sdk", "both"):
            _install_hooks(client)
        _cache[key] = client
        return client


def reset_cache():
    with _lock:
        _cache.clear()
