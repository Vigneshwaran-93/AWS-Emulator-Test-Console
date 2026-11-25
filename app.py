"""AWS Emulator Test Console - Flask app.

Run:  python app.py   ->  http://127.0.0.1:5055
"""
import json
import re
import time

from botocore.exceptions import ClientError
from flask import Flask, Response, abort, jsonify, render_template, request

from emu import docker_ctl, proxy, runner
from emu.clients import NotRunning, get_client, reset_cache
from emu.services import BY_ID, SERVICES
from emu.state import EMU_DIR, STATE
from emu.trace import CURRENT_LABEL, STORE
from emu.workflows import WORKFLOWS

app = Flask(__name__)
app.json.sort_keys = False

_LOCAL_HOSTS = {"127.0.0.1:5055", "localhost:5055"}


@app.before_request
def _local_only_guard():
    """The console has no login, so refuse anything that is not the local UI itself:
    - Host header must be loopback (blocks DNS-rebinding),
    - state-changing requests must be JSON and, if an Origin is sent, come from this app (blocks cross-site CSRF)."""
    if request.host not in _LOCAL_HOSTS:
        abort(403)
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] not in _LOCAL_HOSTS:
            abort(403)
        if not request.is_json:
            abort(415)

SETUP_PAGES = [("about", "About the emulator"), ("install", "1. Install"), ("run", "2. Run & control"), ("connect", "3. Connect CLI / SDK"), ("coverage", "4. Service coverage")]


def nav():
    return {"setup": SETUP_PAGES,
            "basic": [s for s in SERVICES if s["group"] == "basic"],
            "genai": [s for s in SERVICES if s["group"] == "genai"]}


@app.route("/")
def index():
    return render_template("base.html", nav=nav(), state=STATE)


# ------------------------------------------------------------------ page fragments
@app.route("/page/<name>")
def page(name):
    ctx = {"state": STATE, "emu_dir": EMU_DIR}
    if name in ("about", "install", "run", "connect", "coverage"):
        if name == "install":
            ctx["dockerfile"] = docker_ctl.dockerfile_text()
        if name == "coverage":
            ctx["services"] = SERVICES
        return render_template(f"page_{name}.html", **ctx)
    if name == "workflows":
        return render_template("page_service.html", svc={"id": "workflows", "title": "Cross-service workflows", "group": "workflows", "boto": "-", "docs": "",
                                                         "desc": "End-to-end scenarios that chain several services together.", "actions": [], "scenarios": WORKFLOWS}, **ctx)
    svc = BY_ID.get(name)
    if not svc:
        abort(404)
    return render_template("page_service.html", svc=svc, **ctx)


# ------------------------------------------------------------------ run actions
def _find(svc_id, kind, item_id):
    if svc_id == "workflows":
        pool = WORKFLOWS
    else:
        svc = BY_ID.get(svc_id)
        if not svc:
            abort(404)
        pool = svc["scenarios"] if kind == "scenario" else svc["actions"]
    for it in pool:
        if it["id"] == item_id:
            return it
    abort(404)


@app.post("/api/run/<svc_id>/<kind>/<item_id>")
def api_run(svc_id, kind, item_id):
    item = _find(svc_id, kind, item_id)
    raw = (request.get_json(silent=True) or {}).get("values", {})
    return jsonify(runner.run(item, raw, "scenario" if kind == "scenario" else "action"))


# ------------------------------------------------------------------ setup / control
@app.get("/api/status")
def api_status():
    st = docker_ctl.status()
    return jsonify(st)


@app.get("/api/prereq")
def api_prereq():
    return jsonify(docker_ctl.prerequisites())


@app.post("/api/setup/build")
def api_build():
    return jsonify({"started": docker_ctl.build_image()})


@app.get("/api/setup/build_log")
def api_build_log():
    return jsonify(docker_ctl.BUILD)


@app.post("/api/setup/start")
def api_start():
    d = request.get_json(silent=True) or {}
    try:
        port = int(d.get("port", STATE.port))
        idle = int(d.get("idle_timeout") or 0)
    except (TypeError, ValueError):
        return jsonify({"rc": 1, "output": "port and idle timeout must be numbers"}), 400
    memory = str(d.get("memory") or "2g")
    if not (1024 <= port <= 65000 - 21) or port in (5055, STATE.proxy_port) or not (0 <= idle <= 31536000) \
            or not re.fullmatch(r"\d{1,5}[mMgG]", memory):
        return jsonify({"rc": 1, "output": "invalid port (1024-64978, not 5055/9390), idle timeout, or memory (e.g. 2g)"}), 400
    STATE.port, STATE.idle_timeout, STATE.memory = port, idle, memory
    STATE.auth = bool(d.get("auth", True))
    STATE.telemetry = bool(d.get("telemetry", False))
    reset_cache()
    rc, out = docker_ctl.start()
    healthy = docker_ctl.wait_healthy(40) if rc == 0 else False
    return jsonify({"rc": rc, "output": out, "healthy": healthy, "status": docker_ctl.status()})


@app.post("/api/setup/stop")
def api_stop():
    rc, out = docker_ctl.stop()
    reset_cache()
    return jsonify({"rc": rc, "output": out, "status": docker_ctl.status()})


@app.get("/api/setup/logs")
def api_logs():
    return jsonify({"logs": docker_ctl.logs()})


@app.post("/api/mode")
def api_mode():
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode in ("sdk", "proxy", "both"):
        STATE.mode = mode
        reset_cache()
    return jsonify({"mode": STATE.mode})


# ------------------------------------------------------------------ coverage probe
@app.post("/api/coverage")
def api_coverage():
    out = []
    for s in SERVICES:
        client, method, kw = s["probe"]
        CURRENT_LABEL.set(f"coverage probe / {s['title']}")
        t0 = time.time()
        row = {"id": s["id"], "title": s["title"], "group": s["group"], "probe": f"{client}.{method}"}
        try:
            getattr(get_client(client), method)(**kw)
            row.update(status="ok", detail="implemented")
        except NotRunning as e:
            row.update(status="error", detail=str(e))
        except ClientError as e:
            st, info = runner.classify(e)
            row.update(status=st if st == "not_implemented" else "reachable", detail=f"{info['code']}: {info['message']}"[:160])
        except Exception as e:  # noqa
            row.update(status="error", detail=f"{type(e).__name__}: {e}"[:160])
        row["ms"] = int((time.time() - t0) * 1000)
        out.append(row)
    return jsonify(out)


# ------------------------------------------------------------------ trace API
@app.get("/api/traces")
def api_traces():
    since = int(request.args.get("since", 0))
    items, rev = STORE.since(since)
    return jsonify({"rev": rev, "items": items})


@app.post("/api/traces/clear")
def api_clear():
    STORE.clear()
    return jsonify({"ok": True})


@app.get("/api/traces/export")
def api_export():
    items, _ = STORE.since(0)
    return Response(json.dumps(items, indent=2, default=str), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=emulator-traces.json"})


if __name__ == "__main__":
    proxy.start_proxy()
    try:
        docker_ctl.adopt_running()
    except Exception:  # noqa
        pass
    print("AWS Emulator Test Console -> http://127.0.0.1:5055")
    app.run(host="127.0.0.1", port=5055, debug=False, threaded=True)
