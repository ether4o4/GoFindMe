// Tiny DOM helpers. All text goes through textContent / el(...) so external tool
// output and API data can never inject HTML.
export function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k === "html") e.innerHTML = v; // only used with trusted, static strings
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "for") e.htmlFor = v;
    else e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

let toastTimer;
export function toast(msg, isErr = false) {
  let t = document.querySelector(".toast");
  if (!t) { t = el("div", { class: "toast" }); document.body.append(t); }
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 1800);
}

export function field(labelText, input) {
  return el("div", { class: "field" }, [el("label", { text: labelText }), input]);
}

export function input(attrs = {}) { return el("input", attrs); }

export function button(text, opts = {}) {
  return el("button", { class: "btn " + (opts.cls || ""), onclick: opts.onclick }, [text]);
}

export function statusDot(status) {
  const map = { done: "ok", running: "run", queued: "warn", error: "bad",
                timeout: "bad", cancelled: "bad" };
  return el("span", { class: "dot " + (map[status] || "warn"), title: status });
}

// Confirmation via native dialog (kept simple & dependency-free).
export function confirmAction(msg) { return window.confirm(msg); }

// Disposer registry: views register cleanup (EventSource.close, clearInterval);
// the router runs them before navigating away so streams/timers don't leak.
const _disposers = [];
export function onDispose(fn) { _disposers.push(fn); }
export function runDisposers() { while (_disposers.length) { try { _disposers.pop()(); } catch {} } }
