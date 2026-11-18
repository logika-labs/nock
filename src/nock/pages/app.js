// The studio's page: the tasks agents put before the owner, each opened on its review.
// Routes are the address's hash: `#/` the front page, `#/t/TASK` a task, with `/item/SLUG`,
// `/asset/NAME`, `/block/ID` or `/chat` after it for the place to scroll to. The page polls
// `/api/stamp` and reads again when anything moved; floaters (cards, panels, the run's work)
// close with Esc or a click outside.
"use strict";

const main = document.getElementById("main");
const layersRoot = document.getElementById("layers");
const state = {
  word: main.dataset.word || "task",
  words: (main.dataset.word || "task") + "s",
  front: null,
  task: null,
  name: null,
  view: localGet("nock.view") || "story",
  stamp: null,
  route: null,
  versions: {},
  runPolls: new Map(),
};

// --- small things -------------------------------------------------------------------------------

function localGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function localSet(key, value) { try { localStorage.setItem(key, value); } catch { /* private window */ } }
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const hex8 = () => [...crypto.getRandomValues(new Uint8Array(4))].map(b => b.toString(16).padStart(2, "0")).join("");
const cap = text => text ? text[0].toUpperCase() + text.slice(1) : "";
const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.error || `${response.status}`);
  return value;
}

function ago(moment) {
  if (!moment) return "";
  const seconds = (Date.now() - new Date(moment).getTime()) / 1000;
  if (seconds < 60) return "just now";
  const minutes = seconds / 60, hours = minutes / 60, days = hours / 24;
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  if (hours < 24) return `${Math.round(hours)} h ago`;
  if (days < 30) return `${Math.round(days)} d ago`;
  return new Date(moment).toLocaleDateString();
}
const time = moment => moment ? `<time class="time" datetime="${esc(moment)}" title="${esc(new Date(moment).toLocaleString())}">${ago(moment)}</time>` : "";

function toast(markup, ms = 3200) {
  const element = document.getElementById("toast");
  element.innerHTML = markup;
  element.classList.add("shown");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("shown"), ms);
}

// Scroll so ELEMENT sits a comfortable way below the top, never flush with it — and again while
// what is above it still loads (pictures, html blocks), unless the owner scrolled meanwhile.
let ownerScrolled = false;
for (const kind of ["wheel", "touchmove", "keydown"]) addEventListener(kind, () => { ownerScrolled = true; }, { passive: true });
function reveal(element, flash = true) {
  if (!element) return;
  const offset = () => Math.max(96, innerHeight * 0.16);
  const place = behavior => scrollTo({ top: element.getBoundingClientRect().top + scrollY - offset(), behavior });
  ownerScrolled = false;
  place("smooth");
  for (const delay of [500, 1100, 2000]) setTimeout(() => {
    if (!ownerScrolled && element.isConnected && Math.abs(element.getBoundingClientRect().top - offset()) > 24) place("instant");
  }, delay);
  if (flash) { element.classList.remove("flash"); void element.offsetWidth; element.classList.add("flash"); }
}

// --- markdown: headings, lists, emphasis, code, links, tables, quotes; `[task/slug]` a reference --

function inline(text) {
  let out = esc(text);
  const codes = [];
  out = out.replace(/`([^`]+)`/g, (_, code) => { codes.push(code); return `\u0000${codes.length - 1}\u0000`; });
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) =>
    /^(https?:|#|\/|mailto:)/.test(href.replace(/&amp;/g, "&")) ? `<a href="${href}" target="${href.startsWith("#") ? "_self" : "_blank"}" rel="noopener">${label}</a>` : label);
  out = out.replace(/\[([a-z0-9][a-z0-9-]*)\/([a-z0-9][a-z0-9-]*)\]/g, (_, task, slug) =>
    `<button type="button" class="ref" data-ref="item" data-task="${task}" data-slug="${slug}">${task}/${slug}</button>`);
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>").replace(/(^|\W)_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

function markdown(source) {
  const lines = String(source ?? "").replace(/\r/g, "").split("\n");
  const out = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const code = [];
      for (i++; i < lines.length && !/^```/.test(lines[i]); i++) code.push(lines[i]);
      i++;
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
    } else if (/^#{1,4}\s/.test(line)) {
      const level = line.match(/^#+/)[0].length;
      out.push(`<h${level}>${inline(line.replace(/^#+\s*/, ""))}</h${level}>`); i++;
    } else if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = row => row.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
      const head = cells(line);
      i += 2;
      const body = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) body.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    } else if (/^\s*([-*]|\d+\.)\s/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s/, "");
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s/.test(lines[i])) item += " " + lines[i++].trim();
        items.push(`<li>${inline(item)}</li>`);
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
    } else if (/^>\s?/.test(line)) {
      const quote = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${markdown(quote.join("\n"))}</blockquote>`);
    } else if (!line.trim()) {
      i++;
    } else {
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|>|\s*([-*]|\d+\.)\s|\s*\|)/.test(lines[i])) paragraph.push(lines[i++]);
      if (!paragraph.length) paragraph.push(lines[i++]);
      out.push(`<p>${inline(paragraph.join(" "))}</p>`);
    }
  }
  return out.join("");
}

// --- floaters: one stack; Esc closes the top one, a click outside closes those it is outside of --

const layers = [];
function openLayer(markup, { anchor = null, className = "", key = null, onClose = null } = {}) {
  if (key) closeLayer(layers.find(layer => layer.key === key));
  const element = document.createElement("div");
  element.className = `layer ${className}`;
  element.setAttribute("role", "dialog");
  element.innerHTML = `<button type="button" class="close" aria-label="Close">×</button>${markup}`;
  layersRoot.append(element);
  const layer = { element, anchor, key, onClose };
  layers.push(layer);
  element.querySelector(".close").addEventListener("click", () => closeLayer(layer));
  if (!className.includes("run")) place(element, anchor);
  return layer;
}
function place(element, anchor) {
  const width = element.offsetWidth, height = element.offsetHeight;
  let left = (innerWidth - width) / 2, top = Math.max(16, (innerHeight - height) / 3);
  if (anchor) {
    const box = anchor.getBoundingClientRect();
    left = Math.min(Math.max(12, box.left), innerWidth - width - 12);
    top = box.bottom + 8;
    if (top + height > innerHeight - 12) top = Math.max(12, box.top - height - 8);
  }
  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
}
function closeLayer(layer) {
  if (!layer) return;
  const index = layers.indexOf(layer);
  if (index < 0) return;
  layers.splice(index, 1);
  layer.element.remove();
  layer.anchor?.setAttribute?.("aria-expanded", "false");
  layer.onClose?.();
}
const closeAll = () => [...layers].reverse().forEach(closeLayer);
addEventListener("keydown", event => { if (event.key === "Escape" && layers.length) { closeLayer(layers[layers.length - 1]); event.preventDefault(); } });
document.addEventListener("pointerdown", event => {
  if (event.target.closest("#selection-note")) return;
  for (const layer of [...layers].reverse()) {
    if (layer.element.contains(event.target) || layer.anchor?.contains?.(event.target)) break;
    closeLayer(layer);
  }
}, true);

// --- routing ------------------------------------------------------------------------------------

function route() {
  const hash = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "t" && parts[1]) return { page: "task", name: parts[1], kind: parts[2] || null, target: parts.slice(3).join("/") || null };
  if (parts[0] === "memory") return { page: "memory", name: "memory", kind: parts[1] || null, target: parts[2] || null };
  return { page: "front", kind: parts[0] || null, target: parts[1] || null };
}
function go(address) {
  if (location.hash === address) { show(true); return; }
  location.hash = address;
}
addEventListener("hashchange", () => show(true));

async function show(moved = false) {
  const where = route();
  const changedPage = !state.route || state.route.page !== where.page || state.route.name !== where.name;
  state.route = where;
  if (changedPage) closeAll();
  try {
    if (where.page === "memory") {
      await loadMemory();
      if (changedPage) scrollTo({ top: 0, behavior: "instant" });
      renderMemory();
      if (moved) arrive(where);
    } else if (where.page === "task") {
      await loadTask(where.name);
      if (changedPage) scrollTo({ top: 0, behavior: "instant" });
      renderTask();
      if (moved) arrive(where);
    } else {
      await loadFront();
      renderFront();
      if (moved && where.kind) reveal(document.getElementById(`task-${where.kind}`));
      else if (changedPage) scrollTo({ top: 0, behavior: "instant" });
    }
  } catch (error) {
    main.innerHTML = `<div class="empty sheet"><strong>That isn't here.</strong><span>${esc(error.message)}</span><a href="#/">Back to the ${esc(state.words)}</a></div>`;
  }
}

function arrive(where) {
  const target = where.target;
  let element = null;
  if (where.kind === "chat") element = document.getElementById("chat");
  else if (where.kind === "item") element = document.getElementById(`item-${target}`) || document.querySelector(`[data-item-row="${target}"]`);
  else if (where.kind === "asset") element = document.getElementById(`asset-${target}`) || document.querySelector(`[data-asset-row="${target}"]`);
  else if (where.kind === "block") element = document.getElementById(`block-${target}`);
  else if (where.kind === "line") element = document.getElementById(`line-${target}`);
  if (!element && (where.kind === "item" || where.kind === "asset") && state.view === "story") {
    // Not told in the story: the list holds everything.
    state.view = "list"; renderTask();
    element = document.getElementById(`${where.kind}-${target}`);
  }
  if (!element && where.kind) {
    const everything = document.querySelector(".everything");
    if (everything) { everything.open = true; element = document.querySelector(`[data-${where.kind}-row="${target}"]`); }
  }
  setTimeout(() => reveal(element), 30);
}

// --- loading, and staying live ------------------------------------------------------------------

async function loadFront() {
  state.front = await api("/api/topics");
  state.word = state.front.word || state.word;
  state.words = state.front.words || state.words;
  state.stamp = state.front.stamp;
}
async function loadTask(name) {
  state.task = await api(`/api/topic/${encodeURIComponent(name)}`);
  state.name = name;
  if (!state.front) await loadFront();
  for (const run of state.task.runs) if (run.status === "running") watchRun(run.id);
}
async function refresh() {
  if (state.route?.page === "memory") { await loadMemory(); renderMemory(); }
  else if (state.route?.page === "task") { await loadTask(state.route.name); renderTask(); }
  else { await loadFront(); renderFront(); }
  if (layers.some(layer => layer.key === "pending" || layer.key === "active")) {
    const open = layers.find(layer => layer.key === "pending" || layer.key === "active");
    if (open && state.front) openCountPanel(open.key, open.anchor);
  }
}
async function poll() {
  try {
    const { stamp } = await api("/api/stamp");
    if (stamp !== state.stamp) {
      state.stamp = stamp;
      if (!document.querySelector(".layer textarea:focus")) await refresh();
      if (state.route?.page !== "front") { const front = await api("/api/topics"); state.front = front; summary(); }
    }
  } catch { /* the studio is restarting */ }
  setTimeout(poll, 2000);
}

// Patch MAIN to MARKUP in place: what is the same stays (an iframe is not reloaded, focus and a
// draft stay), keyed children by their id.
function morph(element, markup) {
  const template = document.createElement("template");
  template.innerHTML = markup;
  morphChildren(element, template.content);
}
const keyOf = node => node.nodeType === Node.ELEMENT_NODE ? (node.getAttribute("data-key") ?? (node.id || null)) : null;
function morphChildren(into, from) {
  const keyed = new Map();
  for (const child of into.childNodes) { const key = keyOf(child); if (key !== null) keyed.set(key, child); }
  const wanted = new Set([...from.childNodes].map(keyOf).filter(key => key !== null));
  const unwanted = node => keyOf(node) !== null && !wanted.has(keyOf(node));
  let cursor = into.firstChild;
  for (const next of [...from.childNodes]) {
    while (cursor && unwanted(cursor)) cursor = cursor.nextSibling;
    const key = keyOf(next);
    let match = null;
    if (key !== null) match = keyed.get(key) ?? null;
    else if (cursor && keyOf(cursor) === null) match = cursor;
    if (match && match.nodeName !== next.nodeName) match = null;
    if (!match) { into.insertBefore(next, cursor); continue; }
    if (key !== null) keyed.delete(key);
    if (match === cursor) cursor = cursor.nextSibling;
    else into.insertBefore(match, cursor);
    if (match.nodeType === Node.ELEMENT_NODE) morphElement(match, next);
    else if (match.nodeValue !== next.nodeValue) match.nodeValue = next.nodeValue;
  }
  while (cursor) {
    const after = cursor.nextSibling;
    if (keyOf(cursor) === null || unwanted(cursor)) cursor.remove();
    cursor = after;
  }
  for (const node of keyed.values()) node.remove();
}
function morphElement(element, next) {
  for (const { name } of [...element.attributes]) {
    if (next.hasAttribute(name) || (name === "open" && element.tagName === "DETAILS")) continue;
    element.removeAttribute(name);
  }
  for (const { name, value } of [...next.attributes]) if (element.getAttribute(name) !== value) element.setAttribute(name, value);
  if (element.hasAttribute("data-own") && element.childNodes.length) return;
  morphChildren(element, next);
}

function summary() {
  const front = state.front;
  if (!front) return;
  document.getElementById("summary").textContent = `${front.project}`;
  document.title = state.route?.page === "task" ? `${state.name} — nock` : state.route?.page === "memory" ? "Memory — nock" : `nock — ${front.project}`;
}

// --- the front page -----------------------------------------------------------------------------

function renderFront() {
  const front = state.front;
  summary();
  // Finished tasks after the rest, in the server's order within each.
  const closed = task => ["done", "abandoned"].includes(task.state);
  const tasks = [...front.tasks.filter(task => !closed(task)), ...front.tasks.filter(closed)];
  const hints = front.hints.map(hint => hintMarkup(hint, front.runs)).join("");
  const hinted = run => front.hints.some(hint => hint.protocol === run.subject);
  const runs = front.runs.filter(run => !hinted(run) && (run.status === "running" || isRecent(run)))
    .map(run => `<div class="sheet hint" data-key="run-${run.id}">${runMarkup(run)}</div>`).join("");
  const list = tasks.length ? tasks.map(taskRow).join("") : `<div class="empty sheet" data-key="empty"><strong>No ${esc(state.words)} yet.</strong><span>Agents put their work here as they go.</span></div>`;
  morph(main, `
    <section class="counts" data-key="counts">
      <button type="button" class="count-button" data-count="active" aria-expanded="false"><strong>${front.active.length}</strong><span>active ${esc(front.active.length === 1 ? state.word : state.words)}</span></button>
      <button type="button" class="count-button" data-count="pending" aria-expanded="false"><strong>${front.pending.length}</strong><span>pending for you</span></button>
    </section>
    <section class="stack" data-key="hints">${hints}${runs}</section>
    <section class="stack" data-key="tasks">${list}</section>`);
}
const isRecent = run => Date.now() - new Date(run.finished || run.started).getTime() < 6 * 3600 * 1000;

function hintMarkup(hint, runs) {
  const run = runs.find(r => r.subject === hint.protocol);
  const running = run && run.status === "running";
  return `<div class="sheet hint" data-key="hint-${esc(hint.protocol)}" id="hint-${esc(hint.protocol)}">
    <div class="line"><span class="label">Round due</span><h3 class="display">${esc(hint.title)}</h3><span class="muted">${esc(hint.due)}</span></div>
    <div class="muted">${esc(hint.summary)} Its result is a ${esc(state.word)}: <a href="#/t/${esc(hint.task)}">${esc(hint.task)}</a>.</div>
    ${run ? runMarkup(run) : ""}
    <div class="actions">
      <button type="button" class="button primary" data-run-round="${esc(hint.protocol)}" ${running ? "disabled" : ""}>${running ? "Running…" : "Run"}</button>
      ${snoozeMarkup(hint.protocol)}
    </div></div>`;
}
function snoozeMarkup(name) {
  return `<span class="snooze">Remind me in <input type="number" min="1" value="7" aria-label="Days" data-snooze-days="${esc(name)}"> days
    <button type="button" class="button small" data-snooze="${esc(name)}" data-how="days">Snooze</button>
    <button type="button" class="button small ghost" data-snooze="${esc(name)}" data-how="twice">After twice the changes</button>
    <button type="button" class="button small ghost" data-snooze="${esc(name)}" data-how="never">Never</button></span>`;
}
function runMarkup(run) {
  const said = { running: "running", done: "done", failed: "failed", stopped: "stopped" }[run.status] || run.status;
  return `<div class="run-line">
    <span class="pill ${run.status === "done" ? "accepted" : run.status === "running" ? "open" : "rejected"}">${esc(said)}</span>
    <button type="button" class="ref" data-open-run="${esc(run.id)}">${esc(run.title)}</button>
    ${time(run.finished || run.started)}
    ${run.topic ? `<span>result → <a href="#/t/${esc(run.topic)}">${esc(state.word)} ${esc(run.topic)}</a></span>` : ""}
    ${run.log ? `<code title="Its log">${esc(run.log)}</code>` : ""}
    ${run.problem ? `<span style="color:var(--error)">${esc(run.problem)}</span>` : ""}
  </div>`;
}

function taskRow(task) {
  const owner = task.for_owner.length;
  const open = task.items.filter(item => item.status === "open").length;
  const waits = [];
  if (task.review && !task.reviewed && !["done", "abandoned"].includes(task.state)) waits.push(`<span><b>The review</b> waits for you</span>`);
  if (open) waits.push(`<span><b>${plural(open, "proposal")}</b> to decide</span>`);
  if (task.notes) waits.push(`<span>${plural(task.notes, "note")} not sent</span>`);
  if (task.for_agent.length) waits.push(`<span class="muted">waiting on an agent: ${task.for_agent.map(ref => esc(ref.split("/").pop())).join(", ")}</span>`);
  const decisions = task.items.filter(item => item.status === "decision"), proposals = task.items.filter(item => item.status !== "decision");
  const composed = [
    ...decisions.map(item => composedItem(task.name, item)),
    ...proposals.map(item => composedItem(task.name, item)),
    ...task.assets.map(asset => `<li data-key="a-${esc(asset.name)}" id="front-asset-${esc(task.name)}-${esc(asset.name)}"><span class="pill">asset</span><button type="button" class="ref" data-ref="asset" data-task="${esc(task.name)}" data-asset="${esc(asset.name)}">${esc(asset.title || asset.name)}</button></li>`),
  ].join("");
  return `<article class="sheet task" id="task-${esc(task.name)}" data-key="task-${esc(task.name)}">
    <div class="head">
      <h3 class="display"><a href="${task.name === "memory" ? "#/memory" : `#/t/${esc(task.name)}`}">${esc(task.name)}</a></h3>
      <span class="pill ${esc(task.state)}">${esc(task.state)}</span>
      ${time(task.active)}
    </div>
    ${task.status ? `<div>${esc(task.status)}</div>` : ""}
    ${progressMarkup(task.progress)}
    <div class="muted">${esc(task.summary || task.description)}</div>
    ${waits.length ? `<div class="waits">${waits.join("")}</div>` : ""}
    <details data-composed="${esc(task.name)}"><summary>${plural(task.decisions, "decision")} · ${plural(task.proposals, "proposal")} · ${plural(task.assets.length, "asset")}</summary>
      <ul class="composed">${composed || `<li class="muted">Nothing yet.</li>`}</ul>
    </details>
  </article>`;
}
function composedItem(task, item) {
  return `<li data-key="i-${esc(item.slug)}" id="front-item-${esc(task)}-${esc(item.slug)}"><span class="pill ${esc(item.status)}">${esc(item.status === "decision" ? "decision" : item.status === "open" ? "proposal" : item.status)}</span><button type="button" class="ref" data-ref="item" data-task="${esc(task)}" data-slug="${esc(item.slug)}">${esc(item.title)}</button></li>`;
}

function openCountPanel(which, anchor) {
  const front = state.front;
  const entries = which === "active"
    ? front.active.map(entry => ({ task: entry.topic, title: entry.topic, small: entry.title }))
    : front.pending.map(entry => ({ task: entry.topic, slug: entry.slug, title: entry.title, small: `${entry.kind === "review" ? "review" : "proposal"} · ${entry.topic}` }));
  const list = entries.length
    ? `<ul class="list">${entries.map(entry => `<li><button type="button" data-goto-task="${esc(entry.task)}" ${entry.slug ? `data-goto-slug="${esc(entry.slug)}"` : ""}><span>${esc(entry.title)}</span><small>${esc(entry.small || "")}</small></button></li>`).join("")}</ul>`
    : `<p class="muted">Nothing here.</p>`;
  anchor?.setAttribute("aria-expanded", "true");
  openLayer(`<h3>${which === "active" ? `Active ${esc(state.words)}` : "Pending for you"}</h3>${list}`, { anchor, key: which });
}

function gotoFront(task, slug) {
  closeAll();
  const act = () => {
    const row = document.getElementById(`task-${task}`);
    if (!row) return;
    const details = row.querySelector("details");
    if (slug && details) details.open = true;
    reveal(slug ? document.getElementById(`front-item-${task}-${slug}`) || row : row);
  };
  if (route().page !== "front") { location.hash = "#/"; setTimeout(act, 250); } else act();
}

// --- a task -------------------------------------------------------------------------------------

const items = () => new Map(state.task.items.map(item => [item.slug, item]));
const assets = () => new Map(state.task.assets.map(asset => [asset.name, asset]));
const review = () => { const versions = state.task?.review?.versions || []; return versions[versions.length - 1] || null; };
const unsent = () => (state.task?.topic.notes || []).filter(note => !note.sent);

function notesOn(match) {
  return unsent().filter(note => match(note.on || {}));
}
function notesMarkup(notes) {
  if (!notes.length) return "";
  return `<div class="notes">${notes.map(note => `<div class="note" data-key="note-${esc(note.id)}" id="note-${esc(note.id)}">
    <div class="meta"><span class="label">Your note · draft</span>${note.on.quote ? `<span class="quote">“${esc(note.on.quote)}”</span>` : ""}${note.on.line ? `<span class="label">line ${note.on.line}${note.on.side ? ` (${esc(note.on.side)})` : ""}</span>` : ""}<span class="spacer"></span>
    <button type="button" class="link" data-edit-note="${esc(note.id)}">Edit</button> <button type="button" class="link" data-remove-note="${esc(note.id)}">Remove</button></div>
    <div>${esc(note.text)}</div></div>`).join("")}</div>`;
}

// The ids one render gave out: an item told twice is found by its first.
const used = new Set();

function renderTask() {
  used.clear();
  const data = state.task, topic = data.topic, row = data.row;
  summary();
  const current = review();
  const toolbar = `<div class="toolbar" data-key="toolbar">
      <div class="toggle" role="group" aria-label="Show the review">
        <button type="button" data-view="story" aria-pressed="${state.view === "story"}">Story</button>
        <button type="button" data-view="list" aria-pressed="${state.view === "list"}">List</button>
      </div>
      <span class="label">${current ? `review v${current.version}` : "no review yet"}</span>
      <span class="spacer"></span>
      <button type="button" class="button small ghost" data-history="${esc(topic.name)}">History</button>
      <a class="button small ghost" href="#/t/${esc(topic.name)}/chat">Chat${unsent().length ? ` · ${plural(unsent().length, "note")}` : ""}</a>
      ${current ? (data.reviewed ? `<span class="pill accepted">You're done with this review</span>` : `<button type="button" class="button primary small" data-done>Done</button>`) : ""}
    </div>`;
  const body = state.view === "list" || !current ? listMarkup() : storyMarkup(current);
  morph(main, `
    <nav class="crumbs" data-key="crumbs"><a href="#/">← All ${esc(state.words)}</a></nav>
    <header class="sheet task-head" data-key="head" style="margin-top:10px">
      <div class="line"><h2 class="display">${esc(topic.name)}</h2><span class="pill ${esc(topic.state)}">${esc(topic.state)}</span>${time(row.active)}</div>
      ${topic.status ? `<div><span class="label">Status</span> ${esc(topic.status)}</div>` : ""}
      ${progressMarkup(row.progress, true)}
      <div class="muted md">${markdown(row.description)}</div>
    </header>
    ${toolbar}
    <section class="review" data-key="review-${state.view}">${body}</section>
    ${everythingMarkup()}
    ${chatMarkup()}`);
  wireIframes();
}

function storyMarkup(current) {
  const context = { review: current.version, inMessage: false };
  const told = current.blocks.filter(block => !(block.kind === "item" && items().get(block.item)?.status === "rejected"));
  return `<div class="review-summary" data-key="summary">${esc(current.summary)}</div>` + told.map(block => blockMarkup(block, context)).join("");
}

function listMarkup() {
  const all = state.task.items.filter(item => item.status !== "rejected");
  const decisions = all.filter(item => item.status === "decision"), proposals = all.filter(item => item.status !== "decision");
  const group = (title, list) => list.length ? `<div class="label group-title" data-key="g-${title}">${title}</div>${list.join("")}` : "";
  const context = { review: review()?.version, inMessage: false, list: true };
  return group("Decisions", decisions.map(item => blockMarkup({ kind: "item", item: item.slug, id: `list-${item.slug}` }, context)))
    + group("Proposals", proposals.map(item => blockMarkup({ kind: "item", item: item.slug, id: `list-${item.slug}` }, context)))
    + group("Assets", state.task.assets.map(asset => assetBlockMarkup(asset, context)))
    || `<div class="empty sheet"><strong>Nothing here yet.</strong></div>`;
}
function assetBlockMarkup(asset, context) {
  const latest = asset.versions[asset.versions.length - 1];
  const kind = latest && ["image", "video", "pdf"].includes(latest.type) ? "image" : asset.versions.length > 1 && latest?.text !== undefined ? "diff" : "doc";
  return blockMarkup({ kind, asset: asset.name, id: `list-asset-${asset.name}`, title: asset.title }, { ...context, assetAnchor: true });
}

// A block of the review (or of an agent's reply): its own markup inside a figure with a Note button.
function blockMarkup(block, context) {
  const id = block.id;
  const where = context.inMessage ? `m-${context.message}-${id}` : `block-${id}`;
  let inner = "", title = block.title || "", noteOn = null, notes = [];
  try {
    switch (block.kind) {
      case "text":
        inner = `<div class="md" data-text-block="${esc(id)}">${markdown(block.text)}</div>`;
        noteOn = { block: id, review: context.review };
        notes = notesOn(on => on.block === id && !on.asset && !on.item);
        break;
      case "item":
        return itemMarkup(items().get(block.item), block, context);
      case "diff": case "doc": case "excerpt": case "image": {
        const asset = assets().get(block.asset);
        if (!asset) { inner = `<p class="muted">No asset ${esc(block.asset)}.</p>`; break; }
        title = title || asset.title || asset.name;
        const shown = fileMarkup(block, asset, id);
        inner = shown.markup;
        noteOn = { asset: asset.name, version: shown.version };
        notes = notesOn(on => on.asset === asset.name && !on.line);
        if (context.assetAnchor) return figure(`asset-${asset.name}`, block, title, inner, noteOn, notes, assetRef(asset), context);
        return figure(where, block, title, inner, noteOn, notes, assetRef(asset), context);
      }
      case "table":
        inner = `<table class="data"><thead><tr>${(block.columns || []).map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${(block.rows || []).map(r => `<tr>${(Array.isArray(r) ? r : [r]).map(c => `<td>${inline(String(c ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
        noteOn = { block: id, review: context.review };
        notes = notesOn(on => on.block === id);
        break;
      case "chart":
        inner = chartMarkup(block);
        noteOn = { block: id, review: context.review };
        notes = notesOn(on => on.block === id);
        break;
      case "html":
        if (context.inMessage) { inner = `<p class="muted">An html block shows only in the review.</p>`; break; }
        inner = `<iframe class="html-block" data-own sandbox="allow-scripts" data-block="${esc(id)}" title="${esc(title || block.file)}" src="/api/html/${encodeURIComponent(state.name)}/${context.review}/${encodeURIComponent(block.file)}" style="height:${Number(block.height) || 320}px"></iframe>`;
        noteOn = { block: id, review: context.review };
        notes = notesOn(on => on.block === id);
        break;
      default:
        inner = `<p class="muted">A ${esc(block.kind)} block.</p>`;
    }
  } catch (error) {
    inner = `<p class="muted">This block could not be shown: ${esc(error.message)}</p>`;
  }
  return figure(where, block, title, inner, noteOn, notes, "", context);
}
function assetRef(asset) {
  return `<button type="button" class="ref title" data-ref="asset" data-task="${esc(state.name)}" data-asset="${esc(asset.name)}">${esc(asset.title || asset.name)}</button>`;
}
function figure(where, block, title, inner, noteOn, notes, head, context) {
  const noteButton = noteOn && !context.inMessage ? `<button type="button" class="note-button" data-note-on='${esc(JSON.stringify(noteOn))}'>✎ Note</button>` : "";
  const header = head || title ? `<header>${head || `<span class="title">${esc(title)}</span>`}<span class="spacer"></span>${noteButton}</header>` : noteButton;
  return `<figure class="block kind-${esc(block.kind)}${notes.length ? " noted" : ""}" id="${esc(where)}" data-key="${esc(where)}">${header}${inner}${block.caption ? `<figcaption>${inline(block.caption)}</figcaption>` : ""}${notesMarkup(notes)}</figure>`;
}

function itemMarkup(item, block, context) {
  if (!item) return `<figure class="block" data-key="missing-${esc(block.item)}"><p class="muted">No item ${esc(block.item)}.</p></figure>`;
  const status = item.status;
  const badge = status === "decision" ? (item.proposed ? "decision · was a proposal" : "decision") : status === "open" ? "proposal" : status === "accepted" ? "accepted — to be carried out" : "rejected";
  const notes = context.inMessage ? [] : notesOn(on => on.item === item.slug);
  const verdict = status === "open" && !context.inMessage ? `<div class="actions">
      <button type="button" class="button primary small accept" data-verdict="accepted" data-ref="${esc(item.ref)}">Accept</button>
      <button type="button" class="button small reject" data-verdict="rejected" data-ref="${esc(item.ref)}">Reject</button></div>` : "";
  let id = context.inMessage ? `m-${context.message}-${item.slug}` : `item-${item.slug}`;
  if (!context.inMessage && used.has(id)) id = `item-${item.slug}-${block.id}`;
  used.add(id);
  return `<figure class="block item ${esc(status)}${notes.length ? " noted" : ""}" id="${esc(id)}" data-key="${esc(id)}">
    <div class="head"><span class="pill ${esc(status === "decision" ? "decision" : status === "open" ? "proposal" : status)}">${esc(badge)}</span>
      <button type="button" class="ref title" data-ref="item" data-task="${esc(item.topic)}" data-slug="${esc(item.slug)}">${esc(item.title)}</button>
      ${context.inMessage ? "" : `<button type="button" class="note-button" data-note-on='${esc(JSON.stringify({ item: item.slug }))}'>✎ Note</button>`}</div>
    <div class="md">${markdown(item.means)}</div>
    ${item.why ? `<div class="why"><b>Why:</b> ${inline(item.why)}</div>` : ""}
    ${item.takes && status !== "decision" ? `<div class="takes"><b>Takes:</b> ${inline(item.takes)}</div>` : ""}
    ${block.caption ? `<figcaption>${inline(block.caption)}</figcaption>` : ""}
    ${verdict}${notesMarkup(notes)}</figure>`;
}

// Files: which versions a block shows, and the line diff between two.
function versionOf(asset, number) {
  if (!number) return asset.versions[asset.versions.length - 1];
  return asset.versions.find(v => v.version === number) || asset.versions[asset.versions.length - 1];
}
function fileMarkup(block, asset, id) {
  if (block.kind === "diff") {
    const to = versionOf(asset, block.to), from = versionOf(asset, block.from || Math.max(1, to.version - 1));
    if (from.text === undefined || to.text === undefined) {
      return { version: to.version, markup: `<div class="actions"><span class="label">v${from.version}</span>${mediaMarkup(from)}<span class="label">v${to.version}</span>${mediaMarkup(to)}</div>` };
    }
    const noted = new Set(notesOn(on => on.asset === asset.name && on.line).map(on => `${on.on.side}:${on.on.line}`));
    return { version: to.version, markup: `<div class="label" style="margin-bottom:6px">v${from.version} → v${to.version} · ${esc(to.name)}</div><div class="code">${diffTable(from.text, to.text, asset.name, from.version, to.version, noted)}</div>${lineNotes(asset.name, on => on.version === from.version || on.version === to.version)}` };
  }
  const version = versionOf(asset, block.version);
  if (block.kind === "excerpt") {
    const [start, end] = block.lines || [1, 20];
    const lines = (version.text ?? "").split("\n").slice(start - 1, end);
    const noted = new Set(notesOn(on => on.asset === asset.name && on.line).map(n => n.on.line));
    const rows = lines.map((line, index) => {
      const number = start + index;
      return `<tr class="${noted.has(number) ? "has-note" : ""}"><td class="n" data-line-note='${esc(JSON.stringify({ asset: asset.name, version: version.version, line: number }))}' title="Note on line ${number}">${number}</td><td class="t">${esc(line)}</td></tr>`;
    }).join("");
    return { version: version.version, markup: `<div class="label" style="margin-bottom:6px">${esc(version.name)} · lines ${start}–${end} · v${version.version}</div><div class="code"><table>${rows}</table></div>${lineNotes(asset.name, on => on.version === version.version && on.line >= start && on.line <= end)}` };
  }
  if (block.kind === "image" || ["image", "video", "pdf"].includes(version.type) || (version.type === "html" && version.text === undefined)) {
    return { version: version.version, markup: mediaMarkup(version) };
  }
  if (version.text === undefined) return { version: version.version, markup: `<a href="${esc(version.address)}" target="_blank">${esc(version.name)}</a>` };
  const isMarkdown = /\.(md|markdown)$/i.test(version.name);
  return { version: version.version, markup: `<div class="label" style="margin-bottom:6px">${esc(version.name)} · v${version.version}</div><div class="doc">${isMarkdown ? `<div class="md">${markdown(version.text)}</div>` : `<div class="code"><table>${version.text.split("\n").map((line, i) => `<tr><td class="n" data-line-note='${esc(JSON.stringify({ asset: asset.name, version: version.version, line: i + 1 }))}'>${i + 1}</td><td class="t">${esc(line)}</td></tr>`).join("")}</table></div>`}</div>` };
}
function lineNotes(asset, within = () => true) {
  const notes = notesOn(on => on.asset === asset && on.line && within(on));
  return notesMarkup(notes);
}
function mediaMarkup(version) {
  if (version.type === "image") return `<img class="media" loading="lazy" src="${esc(version.address)}" alt="${esc(version.name)}">`;
  if (version.type === "video") return `<video class="media" controls preload="metadata" ${version.poster ? `poster="${esc(version.poster)}"` : ""} src="${esc(version.address)}">${version.captions ? `<track kind="captions" default src="${esc(version.captions)}">` : ""}</video>`;
  if (version.type === "pdf") return `<iframe class="html-block" data-own src="${esc(version.address)}" style="height:520px" title="${esc(version.name)}"></iframe>`;
  if (version.type === "html") return `<iframe class="html-block" data-own sandbox="" src="${esc(version.address)}" style="height:420px" title="${esc(version.name)}"></iframe>`;
  return `<a href="${esc(version.address)}" target="_blank">${esc(version.name)}</a>`;
}

function diffLines(before, after) {
  const a = before.split("\n"), b = after.split("\n");
  if (a.length * b.length > 4e6) return [...a.map(t => ({ op: "del", t })), ...b.map(t => ({ op: "add", t }))];
  const n = a.length, m = b.length, table = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ op: "same", t: a[i], l: i + 1, r: j + 1 }); i++; j++; }
    else if (table[i + 1][j] >= table[i][j + 1]) { out.push({ op: "del", t: a[i], l: i + 1 }); i++; }
    else { out.push({ op: "add", t: b[j], r: j + 1 }); j++; }
  }
  while (i < n) { out.push({ op: "del", t: a[i], l: i + 1 }); i++; }
  while (j < m) { out.push({ op: "add", t: b[j], r: j + 1 }); j++; }
  return out;
}
function diffTable(before, after, asset, fromVersion, toVersion, noted) {
  const lines = diffLines(before, after);
  const keep = new Set();
  lines.forEach((line, index) => { if (line.op !== "same") for (let k = index - 3; k <= index + 3; k++) keep.add(k); });
  let rows = "", skipped = 0;
  const flush = () => { if (skipped) { rows += `<tr class="gap"><td class="n"></td><td class="n"></td><td class="s"></td><td class="t">… ${skipped} unchanged line${skipped === 1 ? "" : "s"}</td></tr>`; skipped = 0; } };
  lines.forEach((line, index) => {
    if (!keep.has(index)) { skipped++; return; }
    flush();
    const side = line.op === "del" ? "before" : "after";
    const number = line.op === "del" ? line.l : line.r;
    const on = { asset, version: side === "before" ? fromVersion : toVersion, line: number, side };
    const cls = line.op === "same" ? "" : line.op;
    rows += `<tr class="${cls}${noted.has(`${side}:${number}`) ? " has-note" : ""}"><td class="n" data-line-note='${esc(JSON.stringify(on))}' title="Note on this line">${line.l ?? ""}</td><td class="n" data-line-note='${esc(JSON.stringify(on))}'>${line.r ?? ""}</td><td class="s"></td><td class="t">${esc(line.t)}</td></tr>`;
  });
  flush();
  return `<table>${rows}</table>`;
}

const PALETTE = ["#6b4cf6", "#ff5cb8", "#14b8c9", "#e9a400", "#1f9d5a", "#f06a3b"];
function chartMarkup(block) {
  const labels = block.labels || [], series = block.series || [];
  const values = series.flatMap(s => s.values || []).filter(v => typeof v === "number");
  const max = Math.max(1, ...values), width = 640, height = 260, left = 44, bottom = 34, top = 12, right = 10;
  const plotW = width - left - right, plotH = height - top - bottom;
  const y = v => top + plotH - (v / max) * plotH;
  const ticks = [0, .25, .5, .75, 1].map(f => max * f);
  let marks = "";
  if (block.chart === "line") {
    const x = i => left + (labels.length <= 1 ? plotW / 2 : (i / (labels.length - 1)) * plotW);
    series.forEach((s, k) => {
      const points = (s.values || []).map((v, i) => `${x(i)},${y(v)}`).join(" ");
      marks += `<polyline fill="none" stroke="${PALETTE[k % 6]}" stroke-width="2.5" stroke-linejoin="round" points="${points}"/>`;
      (s.values || []).forEach((v, i) => { marks += `<circle cx="${x(i)}" cy="${y(v)}" r="3.5" fill="${PALETTE[k % 6]}"><title>${esc(s.name)} · ${esc(labels[i])}: ${v}${esc(block.unit || "")}</title></circle>`; });
    });
    labels.forEach((label, i) => { marks += `<text x="${x(i)}" y="${height - 12}" text-anchor="middle">${esc(label)}</text>`; });
  } else {
    const groupW = plotW / Math.max(1, labels.length), barW = Math.max(4, (groupW * .72) / Math.max(1, series.length));
    labels.forEach((label, i) => {
      series.forEach((s, k) => {
        const v = (s.values || [])[i] ?? 0;
        const x = left + i * groupW + groupW * .14 + k * barW;
        marks += `<rect x="${x}" y="${y(v)}" width="${barW - 2}" height="${top + plotH - y(v)}" rx="3" fill="${PALETTE[k % 6]}"><title>${esc(s.name)} · ${esc(label)}: ${v}${esc(block.unit || "")}</title></rect>`;
      });
      marks += `<text x="${left + i * groupW + groupW / 2}" y="${height - 12}" text-anchor="middle">${esc(label)}</text>`;
    });
  }
  const grid = ticks.map(t => `<line x1="${left}" x2="${width - right}" y1="${y(t)}" y2="${y(t)}" stroke="rgb(17 17 22 / .08)"/><text x="${left - 6}" y="${y(t) + 4}" text-anchor="end">${Math.round(t * 10) / 10}</text>`).join("");
  return `<div class="chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(block.title || "chart")}" style="font: 11px var(--mono); fill: var(--muted)">${grid}${marks}</svg>
    <div class="legend">${series.map((s, k) => `<span><i style="background:${PALETTE[k % 6]}"></i>${esc(s.name)}</span>`).join("")}${block.unit ? `<span>unit: ${esc(block.unit)}</span>` : ""}</div></div>`;
}

function everythingMarkup() {
  const data = state.task;
  const rows = [
    ...data.items.map(item => `<div class="r" data-item-row="${esc(item.slug)}" data-key="ir-${esc(item.slug)}"><span class="pill ${esc(item.status === "open" ? "proposal" : item.status)}">${esc(item.status === "open" ? "proposal" : item.status)}</span><span class="grow"><button type="button" class="ref" data-ref="item" data-task="${esc(item.topic)}" data-slug="${esc(item.slug)}">${esc(item.title)}</button></span>${time(item.updated)}</div>`),
    ...data.assets.map(asset => `<div class="r" data-asset-row="${esc(asset.name)}" data-key="ar-${esc(asset.name)}"><span class="pill">asset</span><span class="grow"><button type="button" class="ref" data-ref="asset" data-task="${esc(state.name)}" data-asset="${esc(asset.name)}">${esc(asset.title || asset.name)}</button> <span class="muted">${asset.versions.map(v => `v${v.version} ${esc(v.name)}`).join(" · ")}</span></span>${time(asset.updated)}</div>`),
  ];
  return `<details class="everything sheet" data-key="everything"><summary>Everything in this ${esc(state.word)}: ${plural(data.items.length, "item")}, ${plural(data.assets.length, "asset")}</summary><div class="rows">${rows.join("") || `<p class="muted">Nothing yet.</p>`}</div></details>`;
}


// --- plan and progress --------------------------------------------------------------------------

function duration(minutes) {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}
function progressMarkup(progress, steps = false) {
  if (!progress || !progress.steps?.length) return "";
  const total = progress.steps.length;
  const currentIndex = progress.steps.findIndex(step => step.title === progress.current);
  const where = progress.current
    ? `step ${currentIndex + 1} of ${total}: ${esc(progress.current)}`
    : progress.done >= total ? `all ${total} steps done` : `${progress.done} of ${total} steps done`;
  const left = progress.done >= total ? "" : progress.left >= 1 ? `about ${duration(progress.left)} left` : "nearly done";
  const list = steps ? `<details class="steps" data-key="steps"><summary>The plan: ${plural(total, "step")}${progress.pace && progress.done ? ` · pace ${progress.pace}× the estimates` : ""}</summary><ol>${progress.steps.map(step => {
    const mark = step.done ? "✓" : step.title === progress.current ? "▸" : "·";
    const timing = step.done && step.actual !== null && step.actual !== undefined ? `${duration(step.estimate)} est. · ${duration(step.actual)} took` : step.title === progress.current ? `${duration(step.estimate)} est. · under way` : `${duration(step.estimate)} est.`;
    return `<li class="${step.done ? "done" : step.title === progress.current ? "current" : ""}"><span class="mark">${mark}</span><span class="grow">${esc(step.title)}</span><span class="time">${esc(timing)}</span></li>`;
  }).join("")}</ol></details>` : "";
  return `<div class="progress" data-key="progress"><div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress.share * 100)}"><span style="width:${Math.round(progress.share * 100)}%"></span></div>
    <div class="said"><span>${where}</span>${left ? `<span class="muted">${left}</span>` : ""}</div>${list}</div>`;
}

// --- the memory: what nock learned, line by line, with the owner's notes and its chat -----------

async function loadMemory() {
  state.memory = await api("/api/memory");
  state.name = state.memory.task;
  try { state.task = await api(`/api/topic/${encodeURIComponent(state.memory.task)}`); }
  catch { state.task = null; }
  if (!state.front) await loadFront();
  for (const run of state.task?.runs || []) if (run.status === "running") watchRun(run.id);
}
function memoryLine(line) {
  if (/^#{1,4}\s/.test(line)) { const level = line.match(/^#+/)[0].length; return `<span class="h h${level}">${inline(line.replace(/^#+\s*/, ""))}</span>`; }
  if (/^\s*[-*]\s/.test(line)) return `<span class="li">${inline(line.replace(/^\s*[-*]\s/, ""))}</span>`;
  return inline(line) || "&nbsp;";
}
function renderMemory() {
  const memory = state.memory;
  summary();
  const notes = memory.notes.filter(note => !note.sent);
  const byLine = new Map();
  for (const note of notes) { const line = note.on.line || 0; byLine.set(line, [...(byLine.get(line) || []), note]); }
  const lines = memory.text.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  const rows = lines.map((line, index) => {
    const number = index + 1, pinned = byLine.get(number) || [];
    return `<tr id="line-${number}" class="${pinned.length ? "has-note" : ""}" data-key="l-${number}"><td class="n" data-memory-line="${number}" title="Note on line ${number}">${number}</td><td class="t">${memoryLine(line)}</td></tr>`
      + (pinned.length ? `<tr class="pinned" data-key="p-${number}"><td></td><td>${notesMarkup(pinned)}</td></tr>` : "");
  }).join("");
  const size = memory.text.length;
  const editing = state.editingMemory;
  morph(main, `
    <nav class="crumbs" data-key="crumbs"><a href="#/">← All ${esc(state.words)}</a></nav>
    <header class="sheet task-head" data-key="head" style="margin-top:10px">
      <div class="line"><h2 class="display">Memory</h2><span class="label">${esc(memory.path)}</span></div>
      <div class="muted">What nock has learned about this project, read by every orchestrator before it starts. Leave a note on a line to have it changed, or edit it yourself.</div>
      <div class="size ${size > memory.limit ? "over" : ""}"><div class="bar"><span style="width:${Math.min(100, Math.round(size / memory.limit * 100))}%"></span></div><span class="label">${size.toLocaleString()} of ${memory.limit.toLocaleString()} characters</span></div>
      ${memory.problems.length ? `<ul class="problems">${memory.problems.map(problem => `<li>${esc(problem)}</li>`).join("")}</ul>` : ""}
    </header>
    <div class="toolbar" data-key="toolbar">
      ${editing ? `<button type="button" class="button primary small" data-memory-save>Save</button><button type="button" class="button small ghost" data-memory-cancel>Cancel</button>` : `<button type="button" class="button small" data-memory-edit>Edit</button>`}
      <span class="spacer"></span>
      <a class="button small ghost" href="#/memory/chat">Chat${notes.length ? ` · ${plural(notes.length, "note")}` : ""}</a>
    </div>
    ${editing ? `<div class="sheet" data-key="editor" style="margin-top:16px"><textarea class="memory-editor" id="memory-editor" data-own spellcheck="false"></textarea></div>`
      : `<div class="block memory" data-key="lines" style="margin-top:16px"><div class="code memory-lines"><table>${rows || `<tr><td></td><td class="muted">Nothing learned yet.</td></tr>`}</table></div></div>`}
    ${state.task ? chatMarkup() : `<section class="chat" id="chat" data-key="chat"><h3 class="display">Chat</h3><div class="status-line">Leave a note on a line to start the memory's chat.</div></section>`}`);
  if (editing) {
    const editor = document.getElementById("memory-editor");
    if (!editor.dataset.filled) { editor.value = memory.text; editor.dataset.filled = "1"; editor.focus(); }
  }
  updateComposer();
}

// --- the chat -----------------------------------------------------------------------------------

function chatMarkup() {
  const data = state.task, topic = data.topic;
  const runs = data.runs;
  const byMessage = new Map(runs.filter(run => run.message).map(run => [run.message, run]));
  const entries = topic.thread.map(entry => {
    if (entry.kind === "status") return `<div class="status-line" data-key="s-${esc(entry.id)}">${esc(entry.state ? `${entry.state}${entry.text && entry.text !== entry.state ? ": " + entry.text : ""}` : entry.text)} · ${ago(entry.moment)}</div>`;
    if (entry.kind === "reviewed") return `<div class="status-line" data-key="r-${esc(entry.id)}">You were done with review v${esc(entry.version)} · ${ago(entry.moment)}</div>`;
    const owner = entry.author === "owner";
    const run = byMessage.get(entry.id);
    const carried = entry.carried || [];
    const blocks = (entry.blocks || []).map(block => blockMarkup(block, { inMessage: true, message: entry.id, review: review()?.version })).join("");
    const files = (entry.attachments || []).map(file => `<a href="${esc(file.address)}" target="_blank">${esc(file.name)}</a>`).join(" · ");
    return `<div class="bubble-msg ${owner ? "owner" : "agent"}${run ? " has-run" : ""}" id="msg-${esc(entry.id)}" data-key="m-${esc(entry.id)}" ${run ? `data-open-run="${esc(run.id)}"` : ""}>
      <div class="meta"><span class="who">${owner ? "You" : esc(entry.role && entry.role !== "interactive" ? `agent · ${entry.role}` : "agent")}</span>${time(entry.moment)}${run ? `<span class="label">see its work →</span>` : ""}</div>
      ${entry.text ? `<div class="md">${markdown(entry.text)}</div>` : owner && carried.length ? `<div class="muted" style="color:rgb(255 255 255 / .7)">(your notes)</div>` : ""}
      ${blocks ? `<div class="blocks">${blocks}</div>` : ""}
      ${files ? `<div>${files}</div>` : ""}
      ${carried.length ? `<button type="button" class="notes-count" data-carried="${esc(entry.id)}">✎ ${plural(carried.length, "note")}</button>` : ""}
    </div>`;
  }).join("");
  const working = runs.filter(run => run.kind === "answer" && (run.status === "running" || ((run.status === "failed" || run.status === "stopped") && !run.message && isRecent(run))))
    .map(run => `<button type="button" class="working${run.status === "running" ? "" : " failed"}" data-open-run="${esc(run.id)}" data-key="w-${esc(run.id)}"><span class="spin"></span><span>${run.status === "running" ? "Working…" : `The agent ${esc(run.status)}`}</span><span class="last" data-run-last="${esc(run.id)}">${esc(lastLine(run))}</span></button>`).join("");
  const listening = data.listening.length ? `<div class="status-line">An agent listens: what you send goes to it at once.</div>` : "";
  const count = unsent().length;
  return `<section class="chat" id="chat" data-key="chat">
    <div class="line" style="display:flex;gap:10px;align-items:baseline"><h3 class="display">Chat</h3><span class="muted">One chat for this ${esc(state.word)}.</span></div>
    <div class="thread">${entries || `<div class="status-line">Nothing said yet.</div>`}${working}${listening}</div>
    <div class="sheet composer" id="composer" data-key="composer" data-own>
      <textarea id="composer-text" placeholder="Write to the agent — or send just your notes"></textarea>
      <div class="files" id="composer-files"></div>
      <div class="bar">
        <label class="button small ghost">Attach<input type="file" id="composer-attach" multiple hidden></label>
        <span class="muted" id="composer-notes"></span>
        <span class="spacer"></span>
        <button type="button" class="button primary" id="composer-send">Send</button>
      </div>
    </div>
  </section>`;
}
function updateComposer() {
  const span = document.getElementById("composer-notes");
  if (!span) return;
  const count = unsent().length;
  span.textContent = count ? `${plural(count, "note")} will go with it` : "";
}
const lastLine = run => {
  const live = state.runPolls.get(run.id)?.events || run.events || [];
  const last = [...live].reverse().find(event => event.kind === "tool" || event.kind === "text");
  return last ? (last.kind === "tool" ? `${last.name}: ${last.summary}` : last.text.slice(0, 120)) : "";
};

const uploads = [];
async function attach(files) {
  for (const file of files) {
    try {
      const response = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error);
      uploads.push(value);
    } catch (error) { toast(`Couldn't attach ${esc(file.name)}: ${esc(error.message)}`); }
  }
  document.getElementById("composer-files").innerHTML = uploads.map(file => `<span>${esc(file.name)}</span>`).join("");
}

async function send() {
  const text = document.getElementById("composer-text");
  const button = document.getElementById("composer-send");
  button.disabled = true;
  try {
    const result = await api("/api/send", { topic: state.name, text: text.value, id: hex8(), attachments: uploads.map(file => file.token) });
    text.value = ""; uploads.length = 0;
    document.getElementById("composer-files").innerHTML = "";
    said(result.run);
    await refresh();
    reveal(document.querySelector(".chat .thread > :last-child"), false);
  } catch (error) { toast(esc(error.message)); }
  button.disabled = false;
}
function said(run) {
  if (!run) return;
  if (run.listening) toast("Sent: the agent listening on its inbox has it now.");
  else if (run.problem) toast(esc(run.problem), 6000);
  else if (run.id) { watchRun(run.id); toast("Sent: an agent is answering now."); }
}

// --- runs: the turn's work as it streams --------------------------------------------------------

function watchRun(id) {
  if (state.runPolls.has(id)) return;
  const entry = { events: [], status: "running", timer: null };
  state.runPolls.set(id, entry);
  const tick = async () => {
    try {
      const { run } = await api(`/api/run/${id}`);
      entry.events = run.events; entry.status = run.status; entry.run = run;
      const last = document.querySelector(`[data-run-last="${id}"]`);
      if (last) last.textContent = lastLine(run);
      const layer = layers.find(l => l.key === `run-${id}`);
      if (layer) fillRun(layer, run);
      if (run.status === "running") entry.timer = setTimeout(tick, 1000);
      else { state.runPolls.delete(id); refresh(); }
    } catch { state.runPolls.delete(id); }
  };
  tick();
}
async function openRun(id) {
  const layer = openLayer(`<header><span class="label">The agent's work</span><h3 data-run-title>…</h3><div class="muted" data-run-state></div></header><div class="events" data-events></div>`, { className: "run", key: `run-${id}` });
  const box = layer.element.querySelector("[data-events]");
  layer.follow = true;
  box.addEventListener("scroll", () => { layer.follow = box.scrollTop + box.clientHeight >= box.scrollHeight - 24; });
  try {
    const { run } = await api(`/api/run/${id}`);
    fillRun(layer, run);
    if (run.status === "running") watchRun(id);
  } catch (error) { box.innerHTML = `<p class="muted">${esc(error.message)}</p>`; }
}
function fillRun(layer, run) {
  layer.element.querySelector("[data-run-title]").textContent = run.title;
  layer.element.querySelector("[data-run-state]").innerHTML = `${esc(run.status === "running" ? "Working…" : run.status)} · started ${ago(run.started)}${run.log ? ` · log <code>${esc(run.log)}</code>` : ""}${run.problem ? ` · <span style="color:var(--error)">${esc(run.problem)}</span>` : ""}`;
  const box = layer.element.querySelector("[data-events]");
  const results = new Map(run.events.filter(e => e.kind === "result").map(e => [e.id, e]));
  const open = new Set([...box.querySelectorAll("details[open]")].map(d => d.dataset.tool));
  box.innerHTML = run.events.map((event, index) => {
    if (event.kind === "thinking") return `<div class="ev-thinking">${esc(event.text)}</div>`;
    if (event.kind === "text") return `<div class="ev-text md">${markdown(event.text)}</div>`;
    if (event.kind === "event") return `<div class="ev-event">${esc(event.text)}</div>`;
    if (event.kind === "tool") {
      const result = results.get(event.id);
      const key = event.id || String(index);
      return `<details class="ev-tool" data-tool="${esc(key)}" ${open.has(key) ? "open" : ""}><summary><b>${esc(event.name)}</b><span>${esc(event.summary)}</span><span class="state time">${result ? (result.error ? "failed" : "done") : "…"}</span></summary>
        <pre>${esc(event.input)}</pre>${result ? `<pre class="${result.error ? "error" : ""}">${esc(result.text || "(no output)")}</pre>` : ""}</details>`;
    }
    return "";
  }).join("") || `<p class="muted">Nothing yet.</p>`;
  if (layer.follow) box.scrollTop = box.scrollHeight;
}

// --- notes --------------------------------------------------------------------------------------

function noteComposer(on, anchor, existing = null) {
  const target = on.memory ? `line ${on.line} of the memory${on.quote ? `: “${on.quote.slice(0, 120)}”` : ""}` : on.quote ? `“${on.quote.slice(0, 120)}”` : on.item ? `the ${items().get(on.item)?.status === "decision" ? "decision" : "proposal"} “${items().get(on.item)?.title || on.item}”` : on.asset ? `${assets().get(on.asset)?.title || on.asset}${on.line ? `, line ${on.line}` : ""}${on.version ? ` (v${on.version})` : ""}` : on.block ? `this block` : "";
  const layer = openLayer(`<h3>${existing ? "Edit your note" : "A note"}</h3><div class="muted">On ${esc(target)}. It waits here as a draft until you send.</div>
    <textarea data-note-text placeholder="What should change, or what you think">${esc(existing?.text || "")}</textarea>
    <div class="actions"><button type="button" class="button primary small" data-note-save>Save note</button><button type="button" class="button small ghost" data-note-cancel>Cancel</button></div>`, { anchor, key: "note" });
  const area = layer.element.querySelector("[data-note-text]");
  setTimeout(() => area.focus(), 20);
  layer.element.querySelector("[data-note-cancel]").addEventListener("click", () => closeLayer(layer));
  const save = async () => {
    const text = area.value.trim();
    if (!text) { area.focus(); return; }
    try {
      await api("/api/note", { topic: state.name, on, text, id: hex8(), ...(existing ? { replaces: existing.id } : {}) });
      closeLayer(layer);
      await refresh();
      updateComposer();
      toast("Note kept as a draft — Send carries it to the agent.");
    } catch (error) { toast(esc(error.message)); }
  };
  layer.element.querySelector("[data-note-save]").addEventListener("click", save);
  area.addEventListener("keydown", event => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) save(); });
}
async function removeNote(id) {
  const note = unsent().find(n => n.id === id);
  if (!note) return;
  try { await api("/api/note", { topic: state.name, on: note.on, text: "", replaces: id }); await refresh(); updateComposer(); }
  catch (error) { toast(esc(error.message)); }
}
function noteTargetAddress(note) {
  const on = note.on || {};
  if (on.memory) return `#/memory/line/${on.line}`;
  if (on.block) return `#/t/${state.name}/block/${on.block}`;
  if (on.item) return `#/t/${state.name}/item/${on.item}`;
  if (on.asset) return `#/t/${state.name}/asset/${on.asset}`;
  return `#/t/${state.name}`;
}
function openCarried(id, anchor) {
  const entry = state.task.topic.thread.find(e => e.id === id);
  const carried = entry?.carried || [];
  openLayer(`<h3>${plural(carried.length, "note")} sent with this message</h3><ul class="list">${carried.map(note => `<li><a href="${esc(noteTargetAddress(note))}"><span>${esc(note.text)}</span><small>on ${esc(note.target)}</small></a></li>`).join("")}</ul>`, { anchor, key: "carried" });
}

// A span of a text block chosen: a Note button beside it.
document.addEventListener("selectionchange", () => {
  clearTimeout(selectionTimer);
  selectionTimer = setTimeout(showSelectionNote, 180);
});
let selectionTimer = null;
function showSelectionNote() {
  const old = document.getElementById("selection-note");
  const selection = getSelection();
  const text = selection && !selection.isCollapsed ? selection.toString().trim() : "";
  const holder = text && selection.anchorNode?.parentElement?.closest("[data-text-block]");
  if (!holder || route().page !== "task") { old?.remove(); return; }
  const box = selection.getRangeAt(0).getBoundingClientRect();
  const button = old || document.createElement("button");
  button.id = "selection-note"; button.type = "button"; button.className = "button primary small selection-note";
  button.textContent = "✎ Note on this";
  button.style.left = `${Math.min(box.left + scrollX, innerWidth - 150)}px`;
  button.style.top = `${box.bottom + scrollY + 6}px`;
  button.dataset.quote = text.slice(0, 600);
  button.dataset.block = holder.dataset.textBlock;
  if (!old) document.body.append(button);
}
document.addEventListener("click", event => {
  const button = event.target.closest("#selection-note");
  if (!button) return;
  const on = { block: button.dataset.block, review: review()?.version, quote: button.dataset.quote };
  button.remove();
  getSelection()?.removeAllRanges();
  noteComposer(on, null);
});

// --- reference cards ----------------------------------------------------------------------------

async function openItemCard(task, slug, anchor) {
  let item = state.task && state.name === task ? items().get(slug) : null;
  if (!item) {
    try { item = (await api(`/api/topic/${encodeURIComponent(task)}`)).items.find(i => i.slug === slug); } catch { item = null; }
  }
  if (!item) { openLayer(`<h3>${esc(task)}/${esc(slug)}</h3><p class="muted">No such item.</p>`, { anchor, key: "card" }); return; }
  const status = item.status;
  const kind = status === "decision" ? "Decision" : status === "open" ? "Proposal" : status === "accepted" ? "Accepted proposal" : "Rejected proposal";
  const here = state.name === task && route().page === "task";
  const layer = openLayer(`<span class="label">${esc(kind)} · ${esc(task)}</span><h3>${esc(item.title)}</h3>
    <div class="md">${markdown(item.means)}</div>
    ${item.why ? `<div class="muted"><b>Why:</b> ${inline(item.why)}</div>` : ""}
    ${item.takes && status !== "decision" ? `<div class="muted"><b>Takes:</b> ${inline(item.takes)}</div>` : ""}
    <div class="actions">
      ${status === "open" ? `<button type="button" class="button primary small accept" data-verdict="accepted" data-ref="${esc(item.ref)}">Accept</button><button type="button" class="button small reject" data-verdict="rejected" data-ref="${esc(item.ref)}">Reject</button>` : ""}
      ${here ? `<button type="button" class="button small" data-card-note>✎ Note</button>` : ""}
      <a class="button small ghost" href="#/t/${esc(task)}/item/${esc(slug)}">Open</a>
    </div>`, { anchor, key: "card" });
  layer.element.querySelector("[data-card-note]")?.addEventListener("click", () => { closeLayer(layer); noteComposer({ item: slug }, anchor); });
}
async function openAssetCard(task, name, anchor) {
  let asset = state.task && state.name === task ? assets().get(name) : null;
  if (!asset) { try { asset = (await api(`/api/topic/${encodeURIComponent(task)}`)).assets.find(a => a.name === name); } catch { asset = null; } }
  if (!asset) return;
  const here = state.name === task && route().page === "task";
  const latest = asset.versions[asset.versions.length - 1];
  const layer = openLayer(`<span class="label">Asset · ${esc(task)}</span><h3>${esc(asset.title || asset.name)}</h3>
    ${asset.description ? `<div class="md">${markdown(asset.description)}</div>` : ""}
    <ul class="list">${asset.versions.slice().reverse().map(v => `<li><a href="${esc(v.address)}" target="_blank"><span>v${v.version} · ${esc(v.name)}</span><small>${esc(v.type)} · ${ago(v.moment)}${v.from?.length ? ` · from ${esc(v.from.join(", "))}` : ""}${v.when ? ` · when ${esc(v.when)}` : ""}</small></a></li>`).join("")}</ul>
    ${latest?.recipe ? `<div class="muted"><b>Made by:</b> <code>${esc(latest.recipe.command || latest.recipe.instruction || "")}</code></div>` : ""}
    <div class="actions">${here ? `<button type="button" class="button small" data-card-note>✎ Note</button>` : ""}<a class="button small ghost" href="#/t/${esc(task)}/asset/${esc(name)}">Open</a></div>`, { anchor, key: "card" });
  layer.element.querySelector("[data-card-note]")?.addEventListener("click", () => { closeLayer(layer); noteComposer({ asset: name, version: latest?.version }, anchor); });
}
function openTaskCard(task, anchor) {
  const row = state.front?.tasks.find(t => t.name === task);
  if (!row) return;
  openLayer(`<span class="label">${esc(cap(state.word))} · ${esc(row.state)}</span><h3>${esc(row.name)}</h3><div class="muted">${esc(row.status)}</div><div class="md">${markdown(row.description)}</div>
    <div class="actions"><a class="button small primary" href="#/t/${esc(task)}">Open</a></div>`, { anchor, key: "card" });
}

// --- history and notifications ------------------------------------------------------------------

async function openHistory(task, anchor) {
  const seen = localGet("nock.seen") || "";
  const { events } = await api(`/api/history${task ? `?topic=${encodeURIComponent(task)}` : ""}`);
  const list = events.slice(0, 80).map(event => `<a class="ev${!task && event.moment > seen && event.author === "agent" ? " new" : ""}" href="${esc(event.address)}">
    <span class="what"><b>${esc(event.topic)}</b> ${esc(event.phrase)}${event.title && event.title !== event.topic ? `: ${esc(event.title)}` : ""}</span>${time(event.moment)}
    ${event.preview ? `<span class="preview">${esc(event.preview)}</span>` : ""}</a>`).join("");
  openLayer(`<h3>${task ? `What changed in ${esc(task)}` : "What changed"}</h3><div class="history">${list || `<p class="muted">Nothing yet.</p>`}</div>`, { anchor, key: "history" });
  if (!task) { localSet("nock.seen", new Date().toISOString().replace(/\.\d+Z$/, "Z")); document.getElementById("bell-dot").hidden = true; anchor?.setAttribute("aria-expanded", "true"); }
}
async function checkBell() {
  try {
    const { events } = await api("/api/history");
    const seen = localGet("nock.seen") || "";
    document.getElementById("bell-dot").hidden = !events.some(event => event.moment > seen && event.author === "agent");
  } catch { /* later */ }
}

let lastNotification = null;
async function notifications() {
  const seen = document.hasFocus() ? "focused" : (localGet("nock.notify") === "on" && "Notification" in window && Notification.permission === "granted") ? "notifying" : "unwatched";
  try {
    const answer = await api(`/notifications?seen=${seen}${lastNotification !== null ? `&after=${lastNotification}` : ""}`);
    lastNotification = answer.latest;
    for (const note of answer.notifications) {
      if (seen === "notifying") {
        const shown = new Notification(`nock · ${state.front?.project || ""}`, { body: note.text, icon: "/icon.png", tag: `nock-${note.topic}` });
        shown.onclick = () => { focus(); go(note.address); shown.close(); };
      } else {
        toast(`${esc(note.text)} — <a href="${esc(note.address)}">open</a>`, 7000);
      }
      checkBell();
    }
  } catch { /* the studio is restarting */ }
  setTimeout(notifications, document.hasFocus() ? 3000 : 10000);
}

// --- settings and rounds ------------------------------------------------------------------------

async function openSettings(anchor) {
  const [settings, rounds] = await Promise.all([api("/api/settings"), api("/api/rounds")]);
  const notifying = localGet("nock.notify") === "on" && "Notification" in window && Notification.permission === "granted";
  const roundsMarkup = rounds.rounds.map(round => {
    const m = round.measure || {};
    const measure = m.measure === "never" ? "never due by itself" : m.value === null || m.value === undefined ? (round.last ? "nothing to measure yet" : round.protocol === "nock.fit" ? "due: it has never run here" : "quiet until Fit has run") : `${Number(m.value).toLocaleString()} of ${Number(m.threshold).toLocaleString()} ${m.unit}`;
    return `<div class="round" data-round="${esc(round.protocol)}">
      <div class="line"><b>${esc(round.title)}</b>${round.due ? `<span class="pill open">due</span>` : ""}
        <button type="button" class="switch" role="switch" aria-checked="${round.on}" data-round-on="${esc(round.protocol)}" aria-label="${esc(round.title)} on" ${round.unavailable ? "disabled" : ""}><span></span></button></div>
      <small>${esc(round.summary)}</small>
      <small>${round.unavailable ? esc(round.unavailable) : `${esc(measure)} · last run ${round.last ? ago(round.last) : "never"}${round.snooze_until ? ` · snoozed until ${esc(round.snooze_until)}` : ""}${round.snooze_at ? ` · hints again at ${Number(round.snooze_at).toLocaleString()}` : ""}`}</small>
      ${round.paths?.length && m.measure === "lines" ? `<small>Looks at: <code>${esc(round.paths.slice(0, 6).join(", "))}${round.paths.length > 6 ? ", …" : ""}</code></small>` : ""}
      <div class="line">${m.threshold !== null && m.threshold !== undefined ? `<label class="muted" style="font-size:12px">Threshold <input type="number" min="1" value="${esc(m.threshold)}" data-round-threshold="${esc(round.protocol)}"></label>` : ""}
        <button type="button" class="button small primary" data-run-round="${esc(round.protocol)}" ${round.unavailable ? "disabled" : ""}>Run</button></div>
    </div>`;
  }).join("");
  anchor?.setAttribute("aria-expanded", "true");
  openLayer(`<h3>Settings</h3><div class="settings-layer" style="display:grid;gap:12px">
    <section><div class="setting">Share usage reports <button type="button" class="switch" role="switch" aria-checked="${settings.share === true}" data-share-switch><span></span></button></div>
      <small class="muted">${settings.share === null ? "Not answered yet. " : ""}Weekly at most, counts and categories only.</small>
      <details><summary class="muted" style="font-size:12px">What it holds</summary><small class="muted">${esc(settings.question)}</small></details></section>
    <section><div class="setting">Browser notifications <button type="button" class="switch" role="switch" aria-checked="${notifying}" data-notify-switch ${settings.notifications ? "" : "disabled"}><span></span></button></div>
      <small class="muted">${settings.notifications ? "When a task is your turn: here while the studio is in front of you, from the browser while it is away, on the desktop when no page is open." : "Off in nock's config (notifications = false)."}</small></section>
    <section><div class="label">Rounds</div><small class="muted">Each is due when enough changed in what it looks at since its last run. Run starts it in the background; its result is a ${esc(state.word)}.</small>${roundsMarkup}</section>
  </div>`, { anchor, key: "settings", className: "settings" });
}

async function runRound(name, button) {
  if (button) button.disabled = true;
  try {
    const { run } = await api("/api/rounds/run", { name });
    toast(`${esc(run.title)} is running — its result will be the ${esc(state.word)} <a href="#/t/${esc(run.topic)}">${esc(run.topic)}</a>.`, 6000);
    watchRun(run.id);
    refresh();
  } catch (error) { toast(esc(error.message), 6000); if (button) button.disabled = false; }
}

// --- one listener for every click ---------------------------------------------------------------

document.addEventListener("click", async event => {
  const target = event.target.closest("button, a, td.n, .bubble-msg.has-run");
  if (!target) return;
  const data = target.dataset;
  if (data.count) { event.preventDefault(); if (layers.some(l => l.key === data.count)) { closeLayer(layers.find(l => l.key === data.count)); return; } openCountPanel(data.count, target); return; }
  if (data.gotoTask) { gotoFront(data.gotoTask, data.gotoSlug); return; }
  if (data.ref === "item") { event.preventDefault(); openItemCard(data.task, data.slug, target); return; }
  if (data.ref === "asset") { event.preventDefault(); openAssetCard(data.task, data.asset, target); return; }
  if (data.ref === "task") { event.preventDefault(); openTaskCard(data.task, target); return; }
  if (data.verdict && data.ref) {
    target.disabled = true;
    try {
      await api("/api/verdict", { ref: data.ref, verdict: data.verdict });
      toast(data.verdict === "accepted" ? "Accepted: an agent carries it out at its next look at its inbox." : "Rejected: dropped from the review, kept in its history.");
      closeAll(); await refresh();
    } catch (error) { toast(esc(error.message)); target.disabled = false; }
    return;
  }
  if (data.noteOn) { noteComposer(JSON.parse(data.noteOn), target); return; }
  if (data.lineNote) { noteComposer(JSON.parse(data.lineNote), target); return; }
  if (data.memoryLine) {
    const line = Number(data.memoryLine);
    const text = (state.memory.text.split("\n")[line - 1] || "").replace(/^\s*(#+|[-*])\s*/, "").trim();
    noteComposer({ memory: true, line, ...(text ? { quote: text.slice(0, 300) } : {}) }, target);
    return;
  }
  if (data.memoryEdit !== undefined) { state.editingMemory = true; renderMemory(); return; }
  if (data.memoryCancel !== undefined) { state.editingMemory = false; renderMemory(); return; }
  if (data.memorySave !== undefined) {
    target.disabled = true;
    try {
      state.memory = await api("/api/memory", { text: document.getElementById("memory-editor").value });
      state.editingMemory = false;
      toast(state.memory.problems.length ? "Saved — but see what holds it back." : "Memory saved.");
      await refresh();
    } catch (error) { toast(esc(error.message)); target.disabled = false; }
    return;
  }
  if (data.editNote) { const note = unsent().find(n => n.id === data.editNote); if (note) noteComposer(note.on, target, note); return; }
  if (data.removeNote) { removeNote(data.removeNote); return; }
  if (data.carried) { event.stopPropagation(); openCarried(data.carried, target); return; }
  if (data.openRun) { if (event.target.closest("a, .ref, .notes-count, video, iframe")) return; openRun(data.openRun); return; }
  if (data.view) { state.view = data.view; localSet("nock.view", data.view); renderTask(); return; }
  if (data.history !== undefined && data.history) { openHistory(data.history, target); return; }
  if (target.id === "bell") { openHistory(null, target); return; }
  if (target.id === "gear" || data.openSettings !== undefined) { openSettings(document.getElementById("gear")); return; }
  if (data.done !== undefined) {
    target.disabled = true;
    try {
      const result = await api("/api/done", { topic: state.name });
      toast(result.sent ? "Done — your notes went to the agent, who answers now." : result.state === "done" ? `Done — the ${esc(state.word)} is finished.` : "Done — decisions without a note count as fine.");
      said(result.run);
      await refresh();
    } catch (error) { toast(esc(error.message)); target.disabled = false; }
    return;
  }
  if (data.runRound) { runRound(data.runRound, target); return; }
  if (data.snooze) {
    const how = data.how, body = { name: data.snooze };
    if (how === "days") body.days = Number(document.querySelector(`[data-snooze-days="${CSS.escape(data.snooze)}"]`)?.value || 7);
    else body[how] = true;
    try { await api("/api/rounds/snooze", body); toast(how === "never" ? "Turned off: it won't remind you again." : "Snoozed."); refresh(); }
    catch (error) { toast(esc(error.message)); }
    return;
  }
  if (data.roundOn) {
    const on = target.getAttribute("aria-checked") !== "true";
    try { await api("/api/rounds/set", { name: data.roundOn, enabled: on }); target.setAttribute("aria-checked", String(on)); refresh(); }
    catch (error) { toast(esc(error.message)); }
    return;
  }
  if (data.shareSwitch !== undefined) {
    const on = target.getAttribute("aria-checked") !== "true";
    try { await api("/usage", { share: on }); target.setAttribute("aria-checked", String(on)); document.getElementById("usage").hidden = true; }
    catch (error) { toast(esc(error.message)); }
    return;
  }
  if (data.notifySwitch !== undefined) {
    const on = target.getAttribute("aria-checked") !== "true";
    if (on && "Notification" in window) {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") { toast("The browser didn't allow notifications."); return; }
    }
    localSet("nock.notify", on ? "on" : "off");
    target.setAttribute("aria-checked", String(on));
    return;
  }
  if (data.share !== undefined && target.closest("#usage")) {
    try { await api("/usage", { share: data.share === "true" }); document.getElementById("usage").hidden = true; }
    catch (error) { toast(esc(error.message)); }
    return;
  }
  if (target.id === "composer-send") { send(); return; }
  if (target.tagName === "A" && target.getAttribute("href")?.startsWith("#/")) {
    // A link to where the page already is still scrolls there.
    if (target.getAttribute("href") === location.hash) { event.preventDefault(); show(true); }
    closeAll();
  }
});
document.addEventListener("change", event => {
  if (event.target.id === "composer-attach") attach([...event.target.files]);
  const threshold = event.target.dataset?.roundThreshold;
  if (threshold) {
    api("/api/rounds/set", { name: threshold, threshold: Number(event.target.value) }).then(() => { toast("Threshold set."); refresh(); }).catch(error => toast(esc(error.message)));
  }
});
document.addEventListener("input", event => { if (event.target.id === "composer-text") updateComposer(); });
document.addEventListener("keydown", event => {
  if (event.target.id === "composer-text" && event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
});

// html blocks: what their bridge says, by the frame it comes from.
function wireIframes() { updateComposer(); }
addEventListener("message", event => {
  const message = event.data;
  if (!message || message.nock !== true) return;
  const frame = [...document.querySelectorAll("iframe.html-block")].find(f => f.contentWindow === event.source);
  if (!frame) return;
  const block = frame.dataset.block;
  if (message.action === "size" && Number(message.height) > 0) frame.style.height = `${Math.min(4000, Math.max(80, Number(message.height) + 4))}px`;
  else if (message.action === "note") {
    const on = { block, review: review()?.version, ...(message.quote ? { quote: message.quote } : {}) };
    if (message.text) api("/api/note", { topic: state.name, on, text: message.text, id: hex8() }).then(() => { toast("Note kept as a draft."); refresh(); }).catch(error => toast(esc(error.message)));
    else noteComposer(on, frame);
  } else if (message.action === "verdict" && message.item) {
    const ref = message.item.includes("/") ? message.item : `${state.name}/${message.item}`;
    api("/api/verdict", { ref, verdict: message.verdict }).then(() => { toast(message.verdict === "accepted" ? "Accepted." : "Rejected."); refresh(); }).catch(error => toast(esc(error.message)));
  } else if (message.action === "open" && /^#\//.test(message.address)) go(message.address);
});

// --- restart, usage, start ----------------------------------------------------------------------

async function checkRestart() {
  try {
    const standing = await api("/restart");
    const element = document.getElementById("restart");
    element.hidden = !standing.stale;
    element.querySelector(".busy").textContent = standing.busy.length ? `Running: ${standing.busy.join(", ")}` : "";
    element.querySelector("button").onclick = async () => {
      try {
        await api("/restart", {});
        const before = standing.instance;
        const wait = async () => { try { const now = await api("/restart"); if (now.instance !== before) { location.reload(); return; } } catch { /* down */ } setTimeout(wait, 500); };
        setTimeout(wait, 500);
      } catch (error) { toast(esc(error.message)); }
    };
  } catch { /* later */ }
  setTimeout(checkRestart, 30000);
}

if (document.getElementById("usage").dataset.askUsage === "true") document.getElementById("usage").hidden = false;
show(true).then(() => { poll(); notifications(); checkBell(); checkRestart(); });
setInterval(checkBell, 60000);
