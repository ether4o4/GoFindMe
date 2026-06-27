import { api, setToken, clearToken, getToken, setUnauthorizedHandler } from "./api.js";
import { el, clear, toast, button, field, runDisposers } from "./ui.js";
import { VIEWS, setRerender, setPrefill } from "./views.js";

const app = document.getElementById("app");

const NAV = [
  ["dashboard", "Dashboard"], ["search", "Search"], ["tools", "Tools"], ["vault", "Vault"],
  ["identity", "Identity"], ["accounts", "Accounts"], ["timeline", "Timeline"],
  ["notes", "Notes"], ["jobs", "Jobs"], ["logs", "Logs"], ["settings", "Settings"],
];

let currentRoute = "dashboard";

setUnauthorizedHandler(() => { clearToken(); showLogin(); });

boot();

async function boot() {
  let health;
  try { health = await api.get("/api/health"); }
  catch { app.textContent = "Cannot reach the GoFindMe server."; return; }
  if (!health.setup_complete) return showSetup();
  if (!getToken()) return showLogin();
  try { await api.get("/api/me"); renderShell(); }
  catch { showLogin(); }
}

/* ----------------------------- auth screens ----------------------------- */
function authShell(title, subtitle, inputs, submitText, onSubmit) {
  clear(app);
  const card = el("div", { class: "authcard" }, [
    el("div", { class: "row" }, [el("div", { class: "logo", text: "⌖" }),
      el("div", {}, [el("h1", { text: title }), el("div", { class: "small muted", text: subtitle })])]),
    el("div", { class: "col" }, [
      ...Object.entries(inputs).map(([k, i]) => field(k, i)),
      button(submitText, { cls: "primary", onclick: onSubmit }),
    ]),
  ]);
  Object.values(inputs).forEach(i => i.addEventListener("keydown", e => { if (e.key === "Enter") onSubmit(); }));
  app.append(el("div", { class: "authwrap" }, [card]));
}

function showSetup() {
  const inputs = {
    Username: el("input", { autocomplete: "username" }),
    Password: el("input", { type: "password", autocomplete: "new-password", placeholder: "min 8 characters" }),
  };
  authShell("Welcome to GoFindMe", "Create the owner account (one-time).", inputs, "Create account", async () => {
    try {
      const r = await api.post("/api/auth/setup",
        { username: inputs.Username.value, password: inputs.Password.value });
      setToken(r.token); renderShell();
    } catch (e) { toast(e.message, true); }
  });
}

function showLogin() {
  const inputs = {
    Username: el("input", { autocomplete: "username" }),
    Password: el("input", { type: "password", autocomplete: "current-password" }),
  };
  authShell("GoFindMe", "Sign in to your console.", inputs, "Sign in", async () => {
    try {
      const r = await api.post("/api/auth/login",
        { username: inputs.Username.value, password: inputs.Password.value });
      setToken(r.token); renderShell();
    } catch (e) { toast(e.message, true); }
  });
}

/* ------------------------------- app shell ------------------------------ */
function renderShell() {
  clear(app);
  const tabs = el("nav", { class: "tabs" });
  for (const [key, label] of NAV) {
    tabs.append(el("button", { class: "tab", "data-route": key, text: label,
      onclick: () => { location.hash = "#/" + key; } }));
  }
  const header = el("header", {}, [
    el("div", { class: "bar" }, [
      el("div", { class: "logo", text: "⌖" }),
      el("div", { class: "brand" }, [el("h1", { text: "GoFindMe" }),
        el("div", { class: "sub", text: "self-hosted OSINT console" })]),
      el("div", { class: "spacer" }),
      button("Logout", { cls: "sm ghost", onclick: logout }),
    ]),
    tabs,
  ]);
  const main = el("main", {}, [el("div", { id: "view" })]);
  app.append(header, main);

  setRerender(() => renderRoute(currentRoute));
  window.addEventListener("hashchange", () => renderRoute(routeFromHash()));
  renderRoute(routeFromHash());
}

function routeFromHash() {
  const h = location.hash.replace(/^#\/?/, "");
  return VIEWS[h] ? h : "dashboard";
}

async function renderRoute(route) {
  currentRoute = route;
  runDisposers();
  for (const t of document.querySelectorAll(".tab"))
    t.classList.toggle("active", t.dataset.route === route);
  const view = document.getElementById("view");
  clear(view);
  try {
    await VIEWS[route](view);
  } catch (e) {
    view.append(el("div", { class: "empty", text: "Error: " + e.message }));
  }
}

async function logout() {
  try { await api.post("/api/auth/logout"); } catch {}
  clearToken(); showLogin();
}
