"""Thread-safe in-memory trace store with revision numbers for incremental polling."""
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar

CURRENT_LABEL = ContextVar("current_label", default="")
CURRENT_TRACE = ContextVar("current_trace", default=None)

_MAX = 1500
_BODY_LIMIT = 30000


def body_text(b, limit=_BODY_LIMIT):
    """Render a request/response body for display."""
    if b is None:
        return ""
    if isinstance(b, str):
        s = b
        n = len(b)
    elif isinstance(b, (bytes, bytearray)):
        n = len(b)
        try:
            s = bytes(b).decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {n} bytes> " + bytes(b[:48]).hex(" ")
    else:
        return f"<{type(b).__name__}>"
    if len(s) > limit:
        return s[:limit] + f"\n...[truncated, {n} total]"
    return s


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = OrderedDict()
        self.next_id = 1
        self.rev = 0

    def add(self, **fields):
        with self.lock:
            tid = self.next_id
            self.next_id += 1
            self.rev += 1
            t = {"id": tid, "rev": self.rev, "ts": time.time(), **fields}
            self.items[tid] = t
            while len(self.items) > _MAX:
                self.items.popitem(last=False)
            return t

    def update(self, tid, **fields):
        with self.lock:
            t = self.items.get(tid)
            if not t:
                return None
            self.rev += 1
            t.update(fields)
            t["rev"] = self.rev
            return t

    def get(self, tid):
        with self.lock:
            return self.items.get(tid)

    def since(self, rev):
        with self.lock:
            return [dict(t) for t in self.items.values() if t["rev"] > rev], self.rev

    def clear(self):
        with self.lock:
            self.items.clear()
            self.rev += 1

    def fail_pending(self, exc):
        """Mark calls that never completed (e.g. connection errors)."""
        with self.lock:
            for t in self.items.values():
                if t.get("status") is None and t.get("source") == "sdk":
                    self.rev += 1
                    t["rev"] = self.rev
                    t["status"] = 0
                    t["ok"] = False
                    t["error"] = f"{type(exc).__name__}: {exc}"
                    t["ms"] = int((time.time() - t["ts"]) * 1000)


STORE = Store()
