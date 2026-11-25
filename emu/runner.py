"""Executes service actions / scenarios, classifies outcomes and makes results JSON-safe."""
import base64
import datetime as dt
import decimal
import time
import traceback

from botocore.exceptions import BotoCoreError, ClientError

from .clients import NotRunning, get_client
from .trace import CURRENT_LABEL, CURRENT_TRACE, STORE


class Abort(Exception):
    pass


def clean(o, depth=0):
    if depth > 12:
        return "<max depth>"
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "ResponseMetadata":
                out["_http_status"] = (v or {}).get("HTTPStatusCode")
            else:
                out[str(k)] = clean(v, depth + 1)
        return out
    if isinstance(o, (list, tuple, set)):
        return [clean(x, depth + 1) for x in o]
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (bytes, bytearray)):
        try:
            s = bytes(o).decode("utf-8")
            return s if len(s) <= 6000 else s[:6000] + f"...[{len(o)} bytes]"
        except UnicodeDecodeError:
            return f"<binary {len(o)} bytes>"
    if hasattr(o, "read"):
        try:
            return clean(o.read(), depth + 1)
        except Exception as e:  # noqa
            return f"<stream: {e}>"
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    return str(o)


def classify(e):
    """-> (status, info). status in ok | not_implemented | error"""
    if isinstance(e, NotRunning):
        return "error", {"code": "EmulatorNotRunning", "message": str(e), "http": None}
    if isinstance(e, ClientError):
        http = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = e.response.get("Error", {}).get("Code")
        msg = e.response.get("Error", {}).get("Message")
        st = "not_implemented" if (http == 501 or code in ("NotImplemented", "501")) else "error"
        return st, {"code": code, "message": msg, "http": http}
    if isinstance(e, BotoCoreError):
        return "error", {"code": type(e).__name__, "message": str(e), "http": None}
    return "error", {"code": type(e).__name__, "message": str(e), "http": None}


class Steps:
    """Collects ordered scenario steps."""

    def __init__(self, scenario_label):
        self.rows = []
        self.label = scenario_label

    def run(self, label, fn, soft=False, show=True):
        t0 = time.time()
        CURRENT_LABEL.set(f"{self.label} / {label}")
        try:
            r = fn()
            self.rows.append({"step": label, "status": "ok", "ms": int((time.time() - t0) * 1000),
                              "result": clean(r) if show else None})
            return r
        except Exception as e:  # noqa
            st, info = classify(e)
            STORE.fail_pending(e) if not isinstance(e, ClientError) else None
            self.rows.append({"step": label, "status": st, "ms": int((time.time() - t0) * 1000), "error": info})
            if not soft:
                raise Abort(label)
            return None

    def note(self, label, value):
        self.rows.append({"step": label, "status": "info", "ms": 0, "result": clean(value)})


class Values(dict):
    """Form values with typed accessors."""

    def num(self, k, default=0):
        try:
            x = float(self.get(k, default))
            return int(x) if x == int(x) else x
        except (TypeError, ValueError):
            return default

    def flag(self, k):
        return bool(self.get(k))

    def lines(self, k):
        return [x.strip() for x in str(self.get(k, "")).splitlines() if x.strip()]

    def json(self, k, default=None):
        import json
        s = self.get(k)
        if s in (None, ""):
            return default
        return json.loads(s, parse_float=decimal.Decimal)


def _coerce(fields, raw):
    from .common import sample_image
    v = Values()
    for f in fields:
        name = f["name"]
        val = raw.get(name)
        if f["type"] == "file":
            if isinstance(val, dict) and val.get("b64"):
                v[name] = base64.b64decode(val["b64"])
            else:
                v[name] = sample_image(f.get("sample", "invoice"))
        elif f["type"] == "checkbox":
            v[name] = bool(val)
        else:
            v[name] = f.get("default", "") if val is None else val
    return v


def run(item, raw, kind="action"):
    """item = action or scenario dict. Returns JSON-safe result envelope."""
    t0 = time.time()
    label = f"{item.get('svc_title', '')} / {item['title']}".strip(" /")
    CURRENT_LABEL.set(label)
    CURRENT_TRACE.set(None)
    v = _coerce(item["fields"], raw)
    env = {"kind": kind}
    try:
        if kind == "scenario":
            steps = Steps(item["title"])
            aborted = None
            try:
                item["fn"](get_client, v, steps)
            except Abort as a:
                aborted = str(a)
            counts = {"ok": 0, "not_implemented": 0, "error": 0}
            for r in steps.rows:
                if r["status"] in counts:
                    counts[r["status"]] += 1
            env.update(status="ok" if not aborted and not counts["error"] and not counts["not_implemented"] else
                       ("not_implemented" if counts["not_implemented"] and not counts["error"] else "error"),
                       steps=steps.rows, counts=counts, aborted=aborted)
        else:
            r = item["fn"](get_client, v)
            env.update(status="ok", result=clean(r))
    except Exception as e:  # noqa
        st, info = classify(e)
        if not isinstance(e, ClientError):
            STORE.fail_pending(e)
        env.update(status=st, error=info)
        if st == "error" and info["code"] not in ("EmulatorNotRunning",) and not isinstance(e, (ClientError, BotoCoreError)):
            env["traceback"] = traceback.format_exc()[-1500:]
    env["ms"] = int((time.time() - t0) * 1000)
    return env
