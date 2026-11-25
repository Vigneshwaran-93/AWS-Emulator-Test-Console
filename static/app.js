/* AWS Emulator Test Console - front end (no framework, no animations) */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  async function api(url, opts) {
    const r = await fetch(url, opts);
    return r.json();
  }
  const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

  /* ------------------------------------------------------------ router */
  let currentPage = null;
  async function loadPage() {
    const name = (location.hash.replace(/^#\//, "") || "about").split("?")[0];
    currentPage = name;
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === name));
    const res = await fetch("/page/" + encodeURIComponent(name));
    $("#content").innerHTML = res.ok ? await res.text() : "<h1>Not found</h1>";
    $("#content").scrollTop = 0;
    initPage(name);
  }
  window.addEventListener("hashchange", loadPage);

  /* ------------------------------------------------------------ generic form runner */
  const fileToB64 = (file) => new Promise((ok) => {
    const fr = new FileReader();
    fr.onload = () => ok({ name: file.name, b64: String(fr.result).split(",")[1] });
    fr.readAsDataURL(file);
  });

  async function collect(form) {
    const v = {};
    for (const el of $$("[name]", form)) {
      if (el.type === "checkbox") v[el.name] = el.checked;
      else if (el.type === "file") { if (el.files && el.files[0]) v[el.name] = await fileToB64(el.files[0]); }
      else v[el.name] = el.value;
    }
    return v;
  }

  function statusBadge(st) {
    const label = { ok: "OK", not_implemented: "501 NOT IMPLEMENTED", error: "ERROR" }[st] || st;
    return `<span class="badge ${st === "not_implemented" ? "b501" : st}">${label}</span>`;
  }

  function renderResult(env) {
    let h = `<div class="rhead">${statusBadge(env.status)} <span class="tms">${env.ms} ms</span></div>`;
    if (env.kind === "scenario") {
      const c = env.counts || {};
      h += `<div>Steps: ${c.ok || 0} ok, ${c.not_implemented || 0} not implemented (501), ${c.error || 0} failed${env.aborted ? ` &mdash; <b>stopped at: ${esc(env.aborted)}</b>` : ""}</div>`;
      h += "<table><tr><th>#</th><th>Step</th><th>Status</th><th>ms</th><th>Output</th></tr>";
      (env.steps || []).forEach((s, i) => {
        let out = "";
        if (s.error) out = `<span class="err-text">${esc(s.error.code)}: ${esc(s.error.message || "")}${s.error.http ? " (HTTP " + s.error.http + ")" : ""}</span>`;
        else if (s.result !== undefined && s.result !== null) {
          const txt = JSON.stringify(s.result, null, 2);
          out = txt.length < 90 ? `<code>${esc(txt)}</code>` : `<details><summary>show (${txt.length} chars)</summary><pre>${esc(txt)}</pre></details>`;
        }
        const st = s.status === "info" ? "info" : s.status;
        h += `<tr><td>${i + 1}</td><td>${esc(s.step)}</td><td>${st === "info" ? "note" : statusBadge(st)}</td><td>${s.ms}</td><td>${out}</td></tr>`;
      });
      h += "</table>";
    } else if (env.error) {
      h += `<div class="err-text"><b>${esc(env.error.code)}</b>: ${esc(env.error.message || "")}${env.error.http ? " (HTTP " + env.error.http + ")" : ""}</div>`;
      if (env.status === "not_implemented") h += `<div>The emulator does not implement this operation yet.</div>`;
      if (env.traceback) h += `<pre>${esc(env.traceback)}</pre>`;
    } else {
      let r = env.result;
      let audio = "";
      if (r && r._audio && r._audio.b64) {
        audio = `<audio controls src="data:${r._audio.mime};base64,${r._audio.b64}"></audio>`;
        r = Object.assign({}, r, { _audio: `[${r._audio.mime} audio, see player]` });
      }
      h += audio + `<pre>${esc(JSON.stringify(r, null, 2))}</pre>`;
    }
    return h;
  }

  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form.run[data-url]");
    if (!form) return;
    e.preventDefault();
    const btn = $("button[type=submit]", form);
    const msg = $(".runmsg", form);
    const box = $(".result", form);
    const badge = form.closest("details") && $("[data-badge]", form.closest("details"));
    btn.disabled = true;
    msg.textContent = "running...";
    try {
      const values = await collect(form);
      const env = await post(form.dataset.url, { values });
      box.hidden = false;
      box.innerHTML = renderResult(env);
      if (badge) { badge.className = "badge " + (env.status === "not_implemented" ? "b501" : env.status); badge.textContent = env.status === "ok" ? "OK" : env.status === "not_implemented" ? "501" : "ERROR"; }
      msg.textContent = "";
    } catch (err) {
      msg.textContent = "request failed: " + err;
    }
    btn.disabled = false;
    pollTraces();
  });

  /* synced fields (bucket / queue / table names shared across forms on a page) */
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (!t.dataset || !t.dataset.sync) return;
    $$(`#content [data-sync="${t.dataset.sync}"]`).forEach((el) => { if (el !== t && el.tagName === t.tagName) el.value = t.value; });
  });

  /* ------------------------------------------------------------ setup pages */
  function statusTable(st) {
    const rows = [
      ["Docker daemon", st.docker ? "running" : "NOT running - start Docker Desktop"],
      ["Emulator container", st.container ? st.container.replace("|", " — ") : "stopped"],
      ["Health (/__admin/health)", st.container ? (st.healthy ? "ok" : "not healthy: " + esc(st.health_detail)) : "-"],
      ["Endpoint", st.endpoint],
      ["Request signing", st.auth ? "on (SigV4)" : "off"],
      ["Capture mode", st.mode + " (proxy on :" + st.proxy_port + ")"],
    ];
    return rows.map((r) => `<tr><th>${r[0]}</th><td>${r[1]}</td></tr>`).join("");
  }

  async function refreshRun() {
    const st = await api("/api/status");
    const t = $("#status-table");
    if (t) t.innerHTML = statusTable(st);
    const c = $("#creds");
    if (c) {
      if (!st.creds) c.innerHTML = st.auth ? "<em>Not running - no credentials yet.</em>" : "<em>Auth is off - no credentials needed (the console uses dummy keys).</em>";
      else {
        c.innerHTML = `<table class="grid">
          <tr><th>Access key ID</th><td><code>${esc(st.creds.access_key)}</code></td></tr>
          <tr><th>Secret key</th><td><code id="sk" data-v="${esc(st.creds.secret_key)}">${"*".repeat(40)}</code> <button type="button" id="btn-reveal">Show</button></td></tr>
          <tr><th>Region</th><td>${esc(st.creds.region)}</td></tr>
          <tr><th>CA bundle</th><td><code>${esc(st.creds.ca)}</code></td></tr>
          <tr><th>Credentials file</th><td><code>${esc(st.creds.credentials_file)}</code></td></tr></table>`;
        $("#btn-reveal").onclick = () => { const e = $("#sk"); const hidden = e.textContent.startsWith("*"); e.textContent = hidden ? e.dataset.v : "*".repeat(40); $("#btn-reveal").textContent = hidden ? "Hide" : "Show"; };
      }
    }
    updatePill(st);
  }

  function updatePill(st) {
    const p = $("#emu-status");
    if (!st.docker) { p.className = "pill off"; p.textContent = "Docker not running"; }
    else if (st.container && st.healthy) { p.className = "pill on"; p.textContent = "Emulator running :" + st.port; }
    else if (st.container) { p.className = "pill neutral"; p.textContent = "Emulator starting..."; }
    else { p.className = "pill off"; p.textContent = "Emulator stopped"; }
  }

  function initPage(name) {
    if (name === "install") {
      const loadPrereq = async () => {
        const items = await api("/api/prereq");
        $("#prereq").innerHTML = items.map((i) => `<tr><th>${esc(i.name)}</th><td>${i.ok ? "&#10004; " : "&#10008; "}${esc(i.detail)}</td></tr>`).join("");
      };
      loadPrereq();
      $("#btn-prereq").onclick = loadPrereq;
      let timer = null;
      const pollBuild = async () => {
        const b = await api("/api/setup/build_log");
        const log = $("#build-log");
        if (!log) { clearInterval(timer); return; }
        log.hidden = false;
        log.textContent = b.lines.slice(-200).join("\n");
        log.scrollTop = log.scrollHeight;
        if (!b.running) {
          clearInterval(timer);
          $("#btn-build").disabled = false;
          $("#build-msg").textContent = b.rc === 0 ? "Build finished OK." : "Build failed (exit " + b.rc + ") - see log.";
          loadPrereq();
        }
      };
      $("#btn-build").onclick = async () => {
        $("#btn-build").disabled = true;
        $("#build-msg").textContent = "building...";
        await post("/api/setup/build");
        clearInterval(timer);
        timer = setInterval(pollBuild, 1500);
        pollBuild();
      };
    }
    if (name === "run") {
      refreshRun();
      $("#btn-refresh").onclick = refreshRun;
      $("#start-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = e.target;
        $("#btn-start").disabled = true;
        $("#start-msg").textContent = "starting container and waiting for health check...";
        const r = await post("/api/setup/start", {
          port: Number(f.port.value), auth: f.auth.checked, telemetry: f.telemetry.checked,
          idle_timeout: Number(f.idle_timeout.value || 0), memory: f.memory.value,
        });
        $("#start-msg").textContent = r.rc !== 0 ? "docker run failed: " + r.output : (r.healthy ? "Emulator is up." : "Started, but not healthy yet - check the container log.");
        $("#btn-start").disabled = false;
        refreshRun();
      });
      $("#btn-stop").onclick = async () => {
        $("#start-msg").textContent = "stopping...";
        const r = await post("/api/setup/stop");
        $("#start-msg").textContent = r.rc === 0 ? "Stopped." : r.output;
        refreshRun();
      };
      $("#btn-logs").onclick = async () => {
        const r = await api("/api/setup/logs");
        const l = $("#logs"); l.hidden = false; l.textContent = r.logs || "(no output)"; l.scrollTop = l.scrollHeight;
      };
    }
    if (name === "coverage") {
      $("#btn-probe").onclick = async () => {
        $("#btn-probe").disabled = true;
        $("#probe-msg").textContent = "probing...";
        const rows = await post("/api/coverage");
        rows.forEach((r) => {
          const tr = $(`#probe-table tr[data-id="${r.id}"]`);
          if (!tr) return;
          const label = { ok: "implemented", not_implemented: "501", reachable: "reachable", error: "error" }[r.status];
          $(".res", tr).innerHTML = `<span class="badge ${r.status === "not_implemented" ? "b501" : r.status}">${label}</span>`;
          $(".det", tr).textContent = r.detail;
          $(".ms", tr).textContent = r.ms;
        });
        const n501 = rows.filter((r) => r.status === "not_implemented").length;
        $("#probe-msg").textContent = `${rows.filter((r) => r.status === "ok" || r.status === "reachable").length} available, ${n501} return 501, ${rows.filter((r) => r.status === "error").length} errors`;
        $("#btn-probe").disabled = false;
        pollTraces();
      };
    }
  }

  /* ------------------------------------------------------------ monitor */
  const traces = new Map();
  let rev = 0, paused = false;

  function pretty(s) {
    if (!s) return "";
    const t = s.trim();
    if ((t[0] === "{" || t[0] === "[") && t.length < 60000) { try { return JSON.stringify(JSON.parse(t), null, 2); } catch (e) { /* not json */ } }
    return s;
  }
  const hdrs = (h) => Object.entries(h || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
  const pre = (title, txt) => txt ? `<h4>${title}</h4><pre>${esc(txt)}</pre>` : "";

  function statusClass(t) {
    if (t.status == null) return "s-pend";
    if (t.status === 501) return "s-501";
    return t.status >= 400 || t.status === 0 ? "s-err" : "s-ok";
  }

  function traceHTML(t, open) {
    const time = new Date(t.ts * 1000).toTimeString().slice(0, 8);
    const src = t.source === "sdk" ? "SDK" : "PROXY";
    const st = t.status == null ? "..." : (t.status === 0 ? "ERR" : t.status);
    let body = `<div class="url"><b>${esc(t.method || "")}</b> ${esc(t.url || "(not sent yet)")}</div>`;
    if (t.error) body += `<div class="errline">${esc(t.error)}</div>`;
    body += pre("Request headers", hdrs(t.req && t.req.headers)) + pre("Request body", pretty(t.req && t.req.body));
    body += pre("Response headers", hdrs(t.resp && t.resp.headers)) + pre("Response body", pretty(t.resp && t.resp.body));
    if (t.wire) {
      body += `<h4>Wire view (via proxy, ${t.wire.proxy_ms} ms)</h4>`;
      body += pre("Wire request: " + esc(t.wire.request.line), hdrs(t.wire.request.headers) + (t.wire.request.body ? "\n\n" + pretty(t.wire.request.body) : ""));
      body += pre("Wire response: " + esc(t.wire.response.line), hdrs(t.wire.response.headers) + (t.wire.response.body ? "\n\n" + pretty(t.wire.response.body) : ""));
    }
    const text = `${t.service} ${t.operation} ${t.status} ${t.label || ""} ${t.error || ""} ${t.url || ""}`.toLowerCase();
    return `<details class="trace ${statusClass(t)}" id="t-${t.id}" data-text="${esc(text)}" data-st="${t.status == null ? "" : t.status}"${open ? " open" : ""}>
      <summary><span class="tid">#${t.id}</span><span class="time">${time}</span><span class="src ${t.source}">${src}</span>
      <span class="opn">${esc(t.service)}.${esc(t.operation)}</span><span class="st">${st}</span><span class="tms">${t.ms == null ? "" : t.ms + " ms"}</span>
      <span class="lbl">${esc(t.label || "")}</span></summary><div class="tbody">${body}</div></details>`;
  }

  function applyFilter(el) {
    const q = $("#filter").value.trim().toLowerCase();
    const f = $("#statusfilter").value;
    const st = el.dataset.st;
    let show = !q || el.dataset.text.includes(q);
    if (show && f) {
      const n = st === "" ? null : Number(st);
      if (f === "ok") show = n !== null && n > 0 && n < 400;
      else if (f === "err") show = n !== null && (n >= 400 || n === 0);
      else if (f === "501") show = n === 501;
    }
    el.hidden = !show;
  }

  function render(items, prevRev) {
    const box = $("#traces");
    if (box.firstElementChild && box.firstElementChild.classList.contains("empty")) box.innerHTML = "";
    items.sort((a, b) => a.id - b.id).forEach((t) => {
      traces.set(t.id, t);
      const old = $("#t-" + t.id);
      const html = traceHTML(t, old ? old.open : false);
      if (old) old.outerHTML = html;
      else {
        box.insertAdjacentHTML("afterbegin", html);
        const fresh = $("#t-" + t.id);
        if (fresh && prevRev > 0) fresh.classList.add("fresh");  // slide-in only for rows that arrive live, not the initial load
      }
      applyFilter($("#t-" + t.id));
    });
    $("#trace-count").textContent = traces.size + " calls";
  }

  let polling = false;
  async function pollTraces() {
    if (paused || polling) return;
    polling = true;
    try {
      const r = await api("/api/traces?since=" + rev);
      if (r.rev < rev) { traces.clear(); $("#traces").innerHTML = ""; rev = 0; }
      const prevRev = rev;
      rev = r.rev;
      if (r.items.length) render(r.items, prevRev);
      if (!traces.size && !$("#traces").firstElementChild) $("#traces").innerHTML = '<div class="empty">No calls yet. Run something on the left, or use the logging proxy from your own tools.</div>';
    } catch (e) { /* server restarting */ }
    polling = false;
  }

  $("#btn-pause").onclick = () => { paused = !paused; $("#btn-pause").textContent = paused ? "Resume" : "Pause"; if (!paused) pollTraces(); };
  $("#btn-clear").onclick = async () => { await post("/api/traces/clear"); traces.clear(); $("#traces").innerHTML = ""; rev = 0; pollTraces(); };
  $("#btn-export").addEventListener("click", (e) => {
    if (!confirm("The export contains raw request headers, including SigV4 signatures and the emulator's temporary access key. The keys stop working when the emulator stops, but do not paste the file into public issues or chats. Continue?")) e.preventDefault();
  });
  $("#btn-collapse").onclick = () => $$("#traces details").forEach((d) => (d.open = false));
  $("#filter").addEventListener("input", () => $$("#traces .trace").forEach(applyFilter));
  $("#statusfilter").addEventListener("change", () => $$("#traces .trace").forEach(applyFilter));
  $("#mode").addEventListener("change", async (e) => { await post("/api/mode", { mode: e.target.value }); });

  /* ------------------------------------------------------------ boot */
  setInterval(pollTraces, 1000);
  setInterval(async () => { if (!document.hidden) { try { updatePill(await api("/api/status")); } catch (e) { /* ignore */ } } }, 6000);
  api("/api/status").then(updatePill).catch(() => {});
  if (!location.hash) location.hash = "#/about";
  loadPage();
  pollTraces();
})();
