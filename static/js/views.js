import { api, streamJob } from "./api.js";
import { el, clear, toast, field, button, statusDot, onDispose, confirmAction } from "./ui.js";

let prefill = null;          // target handed from Dashboard → Search
export function setPrefill(t) { prefill = t; }

const TARGET_TYPES = ["username", "realname", "email", "phone", "domain", "ip", "hash", "bitcoin"];

/* =========================== Dashboard =========================== */
async function dashboard(root) {
  root.append(el("div", { class: "banner" }, [
    el("span", { text: "⚠️" }),
    el("div", { html: "<b>Authorized use only.</b> GoFindMe runs recon tools and queries APIs " +
      "on your behalf. Investigate only targets you are authorized to — your own footprint or " +
      "scoped engagements — and respect each service's terms." }),
  ]));

  const search = el("div", { class: "row" }, [
    el("input", { placeholder: "Search a target — username, email, phone, domain, IP, hash…",
                  id: "dashq", style: "flex:1;min-width:240px" }),
    button("⚡ Search All", { cls: "primary", onclick: go }),
  ]);
  function go() {
    const q = document.getElementById("dashq").value.trim();
    if (!q) return toast("Enter a target", true);
    setPrefill(q); location.hash = "#/search";
  }
  document.addEventListener("keydown", function onk(e) {
    if (e.key === "Enter" && document.activeElement?.id === "dashq") go();
  });
  root.append(search);

  const kpi = el("div", { class: "kpi" });
  root.append(el("h2", { text: "Overview" }), kpi);
  try {
    const o = await api.get("/api/overview");
    const cards = [
      ["Identity items", o.identity_items], ["Accounts", o.accounts],
      ["Without 2FA", o.accounts_without_2fa], ["Timeline events", o.timeline_events],
      ["Findings", o.findings], ["Breached emails", o.breached_emails.length],
      ["Jobs run", o.jobs_total], ["Running now", o.jobs_running],
    ];
    for (const [l, n] of cards)
      kpi.append(el("div", { class: "card" }, [el("div", { class: "n", text: String(n) }),
                                               el("div", { class: "l", text: l })]));
    if (o.breached_emails.length)
      root.append(el("div", { class: "card", style: "margin-top:14px" }, [
        el("div", { class: "ch" }, [el("span", { text: "Emails seen in breaches" })]),
        el("div", { class: "cd", text: o.breached_emails.join(", ") }),
      ]));
  } catch (e) { kpi.append(el("div", { class: "empty", text: "Could not load overview." })); }
}

/* ============================= Search ============================ */
async function searchView(root) {
  const q = el("input", { placeholder: "Target…", value: prefill || "", style: "flex:1;min-width:240px" });
  const typeSel = el("select", { style: "max-width:170px" },
    [el("option", { value: "", text: "auto-detect" }), ...TARGET_TYPES.map(t => el("option", { value: t, text: t }))]);
  const detected = el("div", { class: "small muted", style: "margin-top:6px" });
  const results = el("div");
  const run = button("⚡ Search All", { cls: "primary", onclick: doSearch });

  q.addEventListener("input", debounce(updateDetect, 250));
  q.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
  root.append(el("div", { class: "row" }, [q, typeSel, run]), detected, results);

  async function updateDetect() {
    const t = q.value.trim();
    if (!t || typeSel.value) { detected.textContent = ""; return; }
    try { const d = await api.post("/api/detect", { target: t });
      detected.textContent = d.candidate_types.length ? "Detected: " + d.candidate_types.join(", ") : "";
    } catch {}
  }
  updateDetect();

  async function doSearch() {
    const target = q.value.trim();
    if (!target) return toast("Enter a target", true);
    clear(results);
    let res;
    try { res = await api.post("/api/search-all", { target, type: typeSel.value || null }); }
    catch (e) { return toast(e.message, true); }

    results.append(el("h2", { text: `Tools · ${res.tool_jobs.length}` }));
    const toolGrid = el("div", { class: "grid" });
    results.append(toolGrid);
    if (!res.tool_jobs.length)
      toolGrid.append(el("div", { class: "empty", text: "No installed auto-runnable tools for this type." }));
    for (const tj of res.tool_jobs) toolGrid.append(toolJobCard(tj.name, tj.job_id));

    if (res.tools_skipped.length)
      results.append(el("div", { class: "small muted", style: "margin-top:8px" },
        ["Not installed: " + res.tools_skipped.join(", ") + " — install them from the Tools tab."]));

    results.append(el("h2", { text: `Providers · ${res.providers.length}` }));
    const provGrid = el("div", { class: "grid" });
    results.append(provGrid);
    if (!res.providers.length)
      provGrid.append(el("div", { class: "empty", text: "No keyless/configured providers for this type. Add keys in the Vault tab." }));
    pollFindings(res.target, res.type, res.providers, provGrid);
  }
}

function toolJobCard(name, jobId) {
  const dot = statusDot("queued");
  const out = el("pre", { class: "out", text: "" });
  const det = el("details", {}, [
    el("summary", {}, [el("span", {}, [dot, " ", el("b", { text: name })]),
                       el("span", { class: "tag", text: jobId.slice(0, 6) })]),
    el("div", { class: "body" }, [out]),
  ]);
  det.open = true;
  const es = streamJob(jobId, ev => {
    if (ev.type === "output") out.textContent += ev.data;
    else if (ev.type === "status" && ev.status) {
      dot.className = statusDot(ev.status).className;
      dot.title = ev.status + (ev.error ? ": " + ev.error : "");
      if (ev.error === "tool_not_installed") out.textContent = "(not installed)";
    }
    out.scrollTop = out.scrollHeight;
  });
  onDispose(() => es.close());
  return det;
}

function pollFindings(target, type, providerNames, grid) {
  const seen = new Map();
  const started = Date.now();
  async function tick() {
    let rows;
    try { rows = await api.get(`/api/findings?target=${encodeURIComponent(target)}&type=${type}`); }
    catch { return; }
    for (const f of rows.filter(r => r.source_kind === "provider")) {
      if (seen.has(f.source_name)) continue;
      seen.set(f.source_name, true);
      grid.append(findingCard(f));
    }
    const done = seen.size >= providerNames.length || Date.now() - started > 90000;
    if (done) clearInterval(timer);
  }
  const timer = setInterval(tick, 2000);
  onDispose(() => clearInterval(timer));
  tick();
}

function findingCard(f) {
  const s = f.summary || {};
  const found = s.found;
  const head = el("div", { class: "ch" }, [
    el("span", {}, [el("b", { text: f.source_name }), " ", el("span", { class: "tag", text: f.target_type })]),
    el("span", { class: "tag " + (found === true ? "ok" : found === false ? "" : "warn"),
                 text: found === true ? "hit" : found === false ? "clear" : "info" }),
  ]);
  const body = el("div", { class: "cd" });
  for (const [k, v] of Object.entries(s)) {
    if (k === "found") continue;
    body.append(el("div", { text: `${k}: ${Array.isArray(v) ? v.slice(0, 8).join(", ") : v}` }));
  }
  const card = el("div", { class: "card" }, [head, body]);
  if (f.raw) {
    card.append(el("details", { style: "margin-top:10px" }, [
      el("summary", { text: "raw" }),
      el("div", { class: "body" }, [el("pre", { class: "out", text: JSON.stringify(f.raw, null, 2) })]),
    ]));
  }
  return card;
}

/* ============================== Tools =========================== */
async function toolsView(root) {
  const mgr = await api.get("/api/tools/managers").catch(() => ({ allowed: false, available: {} }));
  const head = el("div", { class: "row" }, [
    el("div", { class: "small muted", style: "flex:1" },
      [mgr.allowed
        ? "Managers: " + Object.entries(mgr.available).map(([m, ok]) => `${m}${ok ? "✓" : "✗"}`).join("  ")
        : "In-app install/update is off in this build. Install tools on your computer (and make sure " +
          "they're on your PATH) — they'll be auto-detected here. For one-click installs, use the Python/server version."]),
    mgr.allowed ? button("⬆ Update all installed", { onclick: async () => {
      const r = await api.post("/api/tools/update-all"); toast(`Updating ${r.started.length}`); location.hash = "#/jobs";
    } }) : null,
    button("＋ Add custom tool", { cls: "primary", onclick: () => addCustom(root) }),
  ]);
  root.append(el("h2", { text: "Installed tools & frameworks" }), head);

  const grid = el("div", { class: "grid" });
  root.append(grid);
  const tools = await api.get("/api/tools");
  for (const t of tools) grid.append(toolCard(t, mgr));
}

function toolCard(t, mgr) {
  const avail = el("span", { class: "tag " + (t.available ? "ok" : ""), text: t.available ? "installed" : "missing" });
  const kind = el("span", { class: "tag", text: t.interactive ? "GUI/manual" : (t.source === "custom" ? "custom" : "cli") });
  const head = el("div", { class: "ch" }, [el("span", {}, [el("b", { text: t.name }), " ", kind]), avail]);
  const meta = el("div", { class: "cd" }, [
    `accepts: ${(t.accepts || []).join(", ") || "—"}`,
    t.install_method !== "none" ? el("div", { text: `install: ${t.install_method} ${t.install_ref || ""}` }) : null,
    t.notes ? el("div", { class: "muted", text: t.notes }) : null,
  ]);
  const actions = el("div", { class: "row", style: "margin-top:10px" });
  if (t.available)
    actions.append(button("Version", { cls: "sm ghost", onclick: () => manage(t.name, "version") }));
  if (mgr.allowed && t.install_method !== "none" && mgr.available[t.install_method]) {
    actions.append(button(t.available ? "Update" : "Install",
      { cls: "sm", onclick: () => manage(t.name, t.available ? "update" : "install") }));
  }
  if (t.interactive)
    actions.append(button("Copy command", { cls: "sm ghost",
      onclick: () => { navigator.clipboard.writeText(t.run_template.replace("{bin}", t.bin)); toast("Copied"); } }));
  if (t.source === "custom")
    actions.append(button("Delete", { cls: "sm danger", onclick: async () => {
      if (!confirmAction(`Delete custom tool ${t.name}?`)) return;
      await api.del(`/api/tools/custom/${t.name}`); toast("Deleted"); rerender();
    } }));
  return el("div", { class: "card" }, [head, meta, actions]);
}

async function manage(name, action) {
  try {
    const r = await api.post(`/api/tools/${name}/${action}`);
    toast(`${action} started`); location.hash = "#/jobs";
    return r;
  } catch (e) { toast(e.message, true); }
}

function addCustom(root) {
  const f = {
    name: el("input", { placeholder: "mytool" }),
    bin: el("input", { placeholder: "executable name on PATH" }),
    accepts: el("input", { placeholder: "username, domain (comma-separated types)" }),
    run_template: el("input", { placeholder: "{bin} -u {target}" }),
    install_method: el("select", {}, ["none", "pip", "pipx", "go", "git", "npm"].map(m => el("option", { value: m, text: m }))),
    install_ref: el("input", { placeholder: "package / module@version / https repo" }),
  };
  const card = el("div", { class: "card", style: "margin:14px 0" }, [
    el("div", { class: "ch" }, [el("span", { text: "Add custom tool" })]),
    field("Name", f.name), field("Binary", f.bin), field("Accepts types", f.accepts),
    field("Run template (must include {target})", f.run_template),
    field("Install method", f.install_method), field("Install reference", f.install_ref),
    el("div", { class: "row", style: "margin-top:10px" }, [
      button("Save", { cls: "primary", onclick: save }),
      button("Cancel", { cls: "ghost", onclick: () => card.remove() }),
    ]),
  ]);
  root.insertBefore(card, root.children[2] || null);
  async function save() {
    const accepts = f.accepts.value.split(",").map(s => s.trim()).filter(Boolean);
    try {
      await api.post("/api/tools/custom", {
        name: f.name.value.trim(), bin: f.bin.value.trim(), accepts, categories: accepts,
        run_template: f.run_template.value.trim(), install_method: f.install_method.value,
        install_ref: f.install_ref.value.trim() || null,
      });
      toast("Saved"); rerender();
    } catch (e) { toast(e.message, true); }
  }
}

/* ============================== Vault =========================== */
async function vaultView(root) {
  const st = await api.get("/api/vault/status");
  const provs = await api.get("/api/providers");

  const stateRow = el("div", { class: "card", style: "margin-bottom:14px" });
  function renderState() {
    clear(stateRow);
    const locked = st.mode === "encrypted" && !st.unlocked;
    stateRow.append(el("div", { class: "row" }, [
      el("span", {}, [el("span", { class: "dot " + (st.mode === "plaintext" ? "bad" : st.unlocked ? "warn" : "ok") }),
        " ", el("b", { text: st.mode === "plaintext" ? "Plaintext (not encrypted)" : st.unlocked ? "Unlocked" : "Locked" })]),
      el("div", { class: "spacer" }),
    ]));
    if (st.mode === "encrypted") {
      const pass = el("input", { type: "password", placeholder: "passphrase", style: "max-width:200px" });
      const row = el("div", { class: "row", style: "margin-top:10px" }, [pass]);
      if (locked) row.append(button("Unlock", { cls: "primary", onclick: async () => {
        try { Object.assign(st, await api.post("/api/vault/unlock", { passphrase: pass.value })); toast("Unlocked"); rerender(); }
        catch (e) { toast(e.message, true); } } }));
      else row.append(button("Lock", { onclick: async () => { Object.assign(st, await api.post("/api/vault/lock")); toast("Locked"); rerender(); } }));
      stateRow.append(row);
      stateRow.append(el("div", { class: "small muted", style: "margin-top:8px" },
        ["Keys are AES-256-GCM encrypted (PBKDF2-SHA256, 200k). The passphrase is never stored. " +
         `Auto-locks after ${st.idle_minutes} min idle.`]));
    }
  }
  renderState();
  root.append(el("h2", { text: "API Vault" }), stateRow);

  const editable = st.mode === "plaintext" || st.unlocked;
  root.append(el("div", { class: "small muted", style: "margin:0 0 12px" },
    ["This is where API keys go. Enter each provider's key and press Save; tap " +
     "“Get key ↗” to open where to sign up for it. Keyless providers (crt.sh) work with no key. " +
     (st.mode === "encrypted" && !st.unlocked ? "Unlock the vault above to add or edit keys." : "")]));
  const grid = el("div", { class: "grid" });
  root.append(grid);
  for (const p of provs) {
    if (!p.vault_key && !p.requires_key) { grid.append(keylessCard(p)); continue; }
    grid.append(providerKeyCard(p, editable));
  }
}

function keylessCard(p) {
  return el("div", { class: "card" }, [
    el("div", { class: "ch" }, [el("span", {}, [el("b", { text: p.name }), " ", el("span", { class: "tag ok", text: "keyless" })]),
      button("Test", { cls: "sm ghost", onclick: () => testProvider(p.name) })]),
    el("div", { class: "cd", text: "accepts: " + p.input_types.join(", ") }),
  ]);
}

function providerKeyCard(p, editable) {
  const inp = el("input", { type: "password", placeholder: p.needs_two_part ? "id:secret" : "API key",
                            disabled: !editable });
  const head = el("div", { class: "ch" }, [
    el("span", {}, [el("b", { text: p.name }), " ",
      el("span", { class: "tag " + (p.configured ? "ok" : "warn"), text: p.configured ? "set" : "needs key" })]),
    el("span", { class: "tag", text: p.input_types.join(",") }),
  ]);
  const actions = el("div", { class: "row", style: "margin-top:10px" }, [
    button("Save", { cls: "sm primary", onclick: async () => {
      if (!inp.value) return; try { await api.put(`/api/vault/keys/${p.vault_key}`, { value: inp.value });
        toast("Saved"); inp.value = ""; rerender(); } catch (e) { toast(e.message, true); } }, }),
    button("Test", { cls: "sm ghost", onclick: () => testProvider(p.name) }),
    p.key_url ? el("a", { class: "btn sm ghost", href: p.key_url, target: "_blank",
                          rel: "noopener noreferrer", text: "Get key ↗" }) : null,
    p.configured ? button("Delete", { cls: "sm danger", onclick: async () => {
      await api.del(`/api/vault/keys/${p.vault_key}`); toast("Deleted"); rerender(); } }) : null,
  ]);
  return el("div", { class: "card" }, [head, field("Key", inp), actions]);
}

async function testProvider(name) {
  toast("Testing " + name + "…");
  try { const r = await api.post(`/api/providers/${name}/test`); toast(name + (r.ok ? ": OK" : ": " + (r.error || "failed")), !r.ok); }
  catch (e) { toast(name + ": " + e.message, true); }
}

/* ============================== Jobs =========================== */
async function jobsView(root) {
  root.append(el("h2", { text: "Recent jobs" }));
  const wrap = el("div");
  root.append(wrap);
  async function load() {
    clear(wrap);
    const jobs = await api.get("/api/jobs?limit=80");
    if (!jobs.length) { wrap.append(el("div", { class: "empty", text: "No jobs yet." })); return; }
    const tbl = el("table", {}, [el("thead", {}, [el("tr", {}, [
      el("th", { text: "" }), el("th", { text: "kind" }), el("th", { text: "name" }),
      el("th", { text: "target" }), el("th", { text: "status" }), el("th", { text: "when" })])])]);
    const tb = el("tbody");
    for (const j of jobs) {
      const tr = el("tr", { onclick: () => showJob(j.id) }, [
        el("td", {}, [statusDot(j.status)]), el("td", { text: j.kind }), el("td", { text: j.name }),
        el("td", { text: j.target }), el("td", { text: j.status }),
        el("td", { class: "small muted", text: (j.created_at || "").replace("T", " ") })]);
      tr.style.cursor = "pointer";
      tb.append(tr);
    }
    tbl.append(tb); wrap.append(tbl);
  }
  await load();
  const timer = setInterval(load, 4000); onDispose(() => clearInterval(timer));
}

async function showJob(id) {
  const j = await api.get(`/api/jobs/${id}`);
  const pre = el("pre", { class: "out", text: j.output || j.error || "(no output)" });
  const box = el("div", { class: "card", style: "margin:12px 0" }, [
    el("div", { class: "ch" }, [el("span", {}, [statusDot(j.status), " ", el("b", { text: j.name }), " — ", j.target]),
      button("✕", { cls: "sm ghost", onclick: () => box.remove() })]),
    pre,
  ]);
  const root = document.getElementById("view");
  root.insertBefore(box, root.firstChild);
}

/* ============================== Logs =========================== */
async function logsView(root) {
  root.append(el("h2", { text: "Audit & activity logs" }));
  const rows = await api.get("/api/logs?limit=300");
  if (!rows.length) return root.append(el("div", { class: "empty", text: "No logs yet." }));
  const tbl = el("table", {}, [el("thead", {}, [el("tr", {}, [
    el("th", { text: "time" }), el("th", { text: "level" }), el("th", { text: "cat" }), el("th", { text: "message" })])])]);
  const tb = el("tbody");
  for (const r of rows)
    tb.append(el("tr", {}, [el("td", { class: "small muted", text: (r.ts || "").replace("T", " ") }),
      el("td", { text: r.level }), el("td", { text: r.category || "" }), el("td", { text: r.message })]));
  tbl.append(tb); root.append(tbl);
}

/* ============================ Settings ========================== */
async function settingsView(root) {
  const h = await api.get("/api/health");
  root.append(el("h2", { text: "Settings & system" }));
  root.append(el("div", { class: "card" }, [
    el("div", { text: `Version: ${h.version}` }),
    el("div", { text: `Vault mode: ${h.vault_mode} (${h.vault_unlocked ? "unlocked" : "locked"})` }),
    el("div", { text: `Data folder: ${h.data_dir || "—"}` }),
    el("div", { class: "small muted", text: `Database file: ${h.db_path || "—"} (your data persists here between runs)` }),
    h.packaged ? el("div", { class: "small muted", style: "margin-top:8px",
      text: "Packaged app: in-app tool install/update is off (no bundled Python). Tools already on " +
            "your system PATH are detected and run; for one-click installs, run the Python/server version." }) : null,
    el("div", { class: "small muted", style: "margin-top:8px",
      html: 'Legacy single-file launcher is preserved at <a href="/legacy" target="_blank">/legacy</a>.' }),
  ]));
  root.append(el("h2", { text: "Importers (planned)" }));
  const ig = el("div", { class: "grid" });
  for (const k of ["browser", "cloud", "file"])
    ig.append(el("div", { class: "card" }, [el("div", { class: "ch" }, [el("span", { text: k + " import" }), el("span", { class: "tag", text: "planned" })]),
      el("div", { class: "cd", text: "Endpoint scaffolded; returns 501 until implemented." })]));
  root.append(ig);
}

/* ====================== Generic CRUD views ===================== */
function crudView(opts) {
  return async function (root) {
    root.append(el("h2", { text: opts.title }));
    const formHost = el("div");
    const listHost = el("div");
    root.append(formHost, listHost);
    renderForm();
    await load();

    function renderForm() {
      clear(formHost);
      const inputs = {};
      const rows = opts.fields.map(fl => {
        let inp;
        if (fl.type === "select") inp = el("select", {}, fl.options.map(o => el("option", { value: o, text: o })));
        else if (fl.type === "textarea") inp = el("textarea", { placeholder: fl.label });
        else inp = el("input", { placeholder: fl.label, type: fl.type || "text" });
        inputs[fl.key] = inp;
        return field(fl.label, inp);
      });
      const card = el("div", { class: "card", style: "margin-bottom:16px" },
        [...rows, el("div", { class: "row", style: "margin-top:10px" },
          [button("Add", { cls: "primary", onclick: add })])]);
      formHost.append(card);
      async function add() {
        const body = {};
        for (const fl of opts.fields) {
          let v = inputs[fl.key].value;
          if (fl.type === "number" || fl.coerce === "int") v = v === "" ? null : parseInt(v, 10);
          if (v !== "" && v != null) body[fl.key] = v;
        }
        try { await api.post(opts.path, body); toast("Added"); for (const i of Object.values(inputs)) i.value = ""; await load(); }
        catch (e) { toast(e.message, true); }
      }
    }
    async function load() {
      clear(listHost);
      const rows = await api.get(opts.path);
      if (!rows.length) { listHost.append(el("div", { class: "empty", text: "Nothing yet." })); return; }
      const tbl = el("table", {}, [el("thead", {}, [el("tr", {},
        [...opts.columns.map(c => el("th", { text: c.label })), el("th", { text: "" })])])]);
      const tb = el("tbody");
      for (const r of rows) {
        const tr = el("tr", {}, [
          ...opts.columns.map(c => el("td", { text: fmt(r[c.key]) })),
          el("td", {}, [button("✕", { cls: "sm danger", onclick: async () => {
            if (!confirmAction("Delete this entry?")) return;
            await api.del(`${opts.path}/${r.id}`); await load(); } })]),
        ]);
        tb.append(tr);
      }
      tbl.append(tb); listHost.append(tbl);
    }
  };
}
function fmt(v) { return v == null ? "" : String(v); }

const identityView = crudView({
  title: "Identity — emails, usernames, handles", path: "/api/identity",
  columns: [{ key: "kind", label: "kind" }, { key: "value", label: "value" }, { key: "label", label: "label" }],
  fields: [
    { key: "kind", label: "Kind", type: "select", options: ["email", "username", "handle", "realname", "phone", "domain"] },
    { key: "value", label: "Value" }, { key: "label", label: "Label" }, { key: "notes", label: "Notes", type: "textarea" },
  ],
});
const accountsView = crudView({
  title: "Accounts & recovery status", path: "/api/accounts",
  columns: [{ key: "service", label: "service" }, { key: "status", label: "status" },
            { key: "has_2fa", label: "2FA" }, { key: "recovery_status", label: "recovery" }],
  fields: [
    { key: "service", label: "Service" }, { key: "url", label: "URL" },
    { key: "status", label: "Status", type: "select", options: ["", "active", "closed", "unknown"] },
    { key: "has_2fa", label: "2FA (1/0)", type: "select", options: ["", "1", "0"], coerce: "int" },
    { key: "recovery_email", label: "Recovery email" }, { key: "recovery_phone", label: "Recovery phone" },
    { key: "recovery_status", label: "Recovery status", type: "select", options: ["", "configured", "missing", "exposed", "unknown"] },
    { key: "notes", label: "Notes", type: "textarea" },
  ],
});
const timelineView = crudView({
  title: "Digital timeline", path: "/api/timeline",
  columns: [{ key: "occurred_at", label: "when" }, { key: "event_type", label: "type" }, { key: "title", label: "title" }],
  fields: [
    { key: "event_type", label: "Type", type: "select", options: ["account_created", "device_added", "breach", "note"] },
    { key: "occurred_at", label: "When (year or date)" }, { key: "title", label: "Title" },
    { key: "detail", label: "Detail", type: "textarea" },
  ],
});
const notesView = crudView({
  title: "Case notes", path: "/api/notes",
  columns: [{ key: "body", label: "note" }, { key: "created_at", label: "created" }],
  fields: [{ key: "body", label: "Note", type: "textarea" }],
});

export const VIEWS = {
  dashboard, search: searchView, tools: toolsView, vault: vaultView,
  identity: identityView, accounts: accountsView, timeline: timelineView, notes: notesView,
  jobs: jobsView, logs: logsView, settings: settingsView,
};

let _rerender = () => {};
export function setRerender(fn) { _rerender = fn; }
function rerender() { _rerender(); }

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
