"""Install / start / stop the AWS Emulator through Docker (the only supported path on Windows/macOS)."""
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request

from .state import EMU_DIR, IMAGE, RPM_BASE, STATE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_DIR = os.path.join(ROOT, "docker")

BUILD = {"running": False, "lines": [], "rc": None}
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW


def _run(args, timeout=60):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", **_NOWIN)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "command not found: " + args[0]
    except subprocess.TimeoutExpired:
        return 124, "timed out: " + " ".join(args)


def prerequisites():
    items = []
    docker_path = shutil.which("docker")
    items.append({"name": "Docker CLI installed", "ok": bool(docker_path), "detail": docker_path or "not found on PATH"})
    rc, out = _run(["docker", "version", "--format", "{{.Server.Version}}"], 20) if docker_path else (1, "")
    items.append({"name": "Docker daemon running", "ok": rc == 0,
                  "detail": ("server " + out.strip()) if rc == 0 else "start Docker Desktop and wait until it says 'running'"})
    rc2, _ = _run(["docker", "image", "inspect", IMAGE], 20) if rc == 0 else (1, "")
    items.append({"name": f"Image '{IMAGE}' built", "ok": rc2 == 0, "detail": "ready" if rc2 == 0 else "use the Build button below"})
    aws = shutil.which("aws")
    items.append({"name": "AWS CLI (optional)", "ok": bool(aws), "detail": aws or "not installed - only needed for the CLI examples"})
    items.append({"name": "Platform", "ok": True, "detail": f"{platform.system()} {platform.machine()}"})
    return items


GPG_FINGERPRINT = "98BCF336A3BE53B734E967C52E5BF49BD940F624"
GPG_KEY_URL = "https://downloads.aws.com/keys/gpg/current.asc"


def dockerfile_text():
    arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    return f"""# Stage 1: download the emulator package and verify its GPG signature (build fails if it does not verify)
FROM public.ecr.aws/amazonlinux/amazonlinux:2023 AS verify
RUN dnf install -y --allowerasing gnupg2 curl && dnf clean all
WORKDIR /dl
RUN curl -fsSLO {RPM_BASE}/aws-emulator-{arch}.rpm \
 && curl -fsSLO {RPM_BASE}/aws-emulator-{arch}.rpm.sig \
 && curl -fsSLo key.asc {GPG_KEY_URL} \
 && test "$(gpg --show-keys --with-colons key.asc | awk -F: '/^fpr/ {{print $10; exit}}')" = "{GPG_FINGERPRINT}" \
 && gpg --import key.asc \
 && gpg --verify aws-emulator-{arch}.rpm.sig aws-emulator-{arch}.rpm

# Stage 2: runtime image (only the verified package is copied in)
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal
COPY --from=verify /dl/aws-emulator-{arch}.rpm /tmp/aws-emulator.rpm
RUN rpm -i /tmp/aws-emulator.rpm && rm -f /tmp/aws-emulator.rpm \
 && mkdir -p /home/emulator/.aws/emulator && chown -R 1000:1000 /home/emulator
USER 1000
ENV HOME=/home/emulator EMULATOR_BIND_ADDRESS=0.0.0.0
ENTRYPOINT ["aws-emulator"]
"""


def build_image():
    if BUILD["running"]:
        return False
    os.makedirs(DOCKER_DIR, exist_ok=True)
    with open(os.path.join(DOCKER_DIR, "Dockerfile"), "w", newline="\n") as f:
        f.write(dockerfile_text())
    BUILD.update(running=True, lines=[], rc=None)

    def worker():
        try:
            p = subprocess.Popen(["docker", "build", "--progress=plain", "-t", IMAGE, DOCKER_DIR],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace", **_NOWIN)
            for line in p.stdout:
                BUILD["lines"].append(line.rstrip())
            BUILD["rc"] = p.wait()
        except Exception as e:  # noqa
            BUILD["lines"].append(f"ERROR: {e}")
            BUILD["rc"] = 1
        finally:
            BUILD["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True


# ---------------------------------------------------------------- run control
def _host_dir(port=None):
    return os.path.join(EMU_DIR, str(port or STATE.port))


def start():
    port = STATE.port
    name = STATE.container
    if running_container():
        return 0, f"{name} already running"
    os.makedirs(EMU_DIR, exist_ok=True)
    lo, hi = port + 1, port + 20
    args = ["docker", "run", "-d", "--rm", "--name", name,
            f"--memory={STATE.memory}", f"--memory-swap={STATE.memory}",
            "-p", f"127.0.0.1:{port}:{port}",
            "-p", f"127.0.0.1:{lo}-{hi}:{lo}-{hi}",
            "-e", f"EMULATOR_LISTENER_PORT_RANGE={lo}-{hi}",
            "-v", f"{EMU_DIR}:/home/emulator/.aws/emulator",
            IMAGE, "-p", str(port)]
    if not STATE.auth:
        args += ["-a", "off"]
    args += ["-t", "on" if STATE.telemetry else "off"]
    if STATE.idle_timeout:
        args += ["--idle-timeout", str(int(STATE.idle_timeout))]
    rc, out = _run(args, 90)
    return rc, out.strip()


def stop():
    rc, out = _run(["docker", "stop", "-t", "10", STATE.container], 40)
    return rc, out.strip()


def running_container():
    rc, out = _run(["docker", "ps", "--filter", f"name=^{STATE.container}$", "--format", "{{.Names}}|{{.Status}}"], 20)
    if rc == 0 and out.strip():
        return out.strip().splitlines()[0]
    return None


def adopt_running():
    """If an emulator container is already running (e.g. app restarted), adopt its port."""
    rc, out = _run(["docker", "ps", "--filter", "name=^aws-emulator-", "--format", "{{.Names}}"], 15)
    if rc == 0 and out.strip():
        m = re.match(r"aws-emulator-(\d+)$", out.strip().splitlines()[0])
        if m:
            STATE.port = int(m.group(1))
            return True
    return False


def logs(tail=120):
    rc, out = _run(["docker", "logs", "--tail", str(tail), STATE.container], 20)
    return out


def ensure_local_files():
    d = _host_dir()
    if os.path.exists(os.path.join(d, "emulator_credentials")):
        return d
    if running_container():  # fallback when the bind mount is not visible on the host
        _run(["docker", "cp", f"{STATE.container}:/home/emulator/.aws/emulator/{STATE.port}", EMU_DIR], 30)
    return d


def load_creds():
    d = ensure_local_files()
    cred = os.path.join(d, "emulator_credentials")
    if not os.path.exists(cred):
        return None
    text = open(cred, encoding="utf-8", errors="replace").read()
    ak = re.search(r"aws_access_key_id\s*=\s*(\S+)", text)
    sk = re.search(r"aws_secret_access_key\s*=\s*(\S+)", text)
    st = re.search(r"aws_session_token\s*=\s*(\S+)", text)
    if not (ak and sk):
        return None
    region = "us-east-1"
    cfg = os.path.join(d, "config")
    if os.path.exists(cfg):
        m = re.search(r"^\s*region\s*=\s*(\S+)", open(cfg, encoding="utf-8", errors="replace").read(), re.M)
        if m:
            region = m.group(1)
    return {"access_key": ak.group(1), "secret_key": sk.group(1), "token": st.group(1) if st else None,
            "region": region, "ca": os.path.join(d, "ca.pem"), "dir": d,
            "credentials_file": cred, "config_file": cfg}


def health():
    creds = load_creds()
    url = f"https://127.0.0.1:{STATE.port}/__admin/health"
    try:
        ctx = ssl.create_default_context(cafile=creds["ca"]) if creds and os.path.exists(creds["ca"]) else ssl._create_unverified_context()
        ctx.check_hostname = False
        with urllib.request.urlopen(url, timeout=3, context=ctx) as r:
            return r.status == 200, r.read().decode()[:100]
    except Exception as e:  # noqa
        return False, f"{type(e).__name__}: {e}"


def wait_healthy(seconds=40):
    end = time.time() + seconds
    while time.time() < end:
        ok, _ = health()
        if ok:
            return True
        time.sleep(1)
    return False


def status():
    rc, out = _run(["docker", "version", "--format", "{{.Server.Version}}"], 15)
    docker_ok = rc == 0
    cont = running_container() if docker_ok else None
    ok, detail = health() if cont else (False, "container not running")
    creds = load_creds() if cont else None
    return {"docker": docker_ok, "container": cont, "healthy": ok, "health_detail": detail,
            "port": STATE.port, "endpoint": f"https://127.0.0.1:{STATE.port}",
            "creds": ({"access_key": creds["access_key"], "secret_key": creds["secret_key"], "region": creds["region"],
                       "ca": creds["ca"], "credentials_file": creds["credentials_file"], "config_file": creds["config_file"]}
                      if creds else None),
            "auth": STATE.auth, "mode": STATE.mode, "proxy_port": STATE.proxy_port}
