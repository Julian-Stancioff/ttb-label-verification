"use strict";

// ============================ helpers ============================
const $ = (id) => document.getElementById(id);
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!r.ok) throw new Error((data && data.detail) || `Request failed (${r.status})`);
  return data;
}

// Field rows (verification + alignment use these exact keys) → labels, colors,
// and the extraction/expected keys an edit writes back to.
const FIELDS = [
  { key: "brand_name",            label: "Brand name",        color: "#d6334c", exp: "brand_name",            ext: "brand_name" },
  { key: "class_type",            label: "Class / type",      color: "#1a8a3a", exp: "class_type",            ext: "class_type" },
  { key: "alcohol_content",       label: "Alcohol content",   color: "#e08a00", exp: "alcohol_content",       ext: "alcohol_content" },
  { key: "net_contents",          label: "Net contents",      color: "#0a8aa0", exp: "net_contents",          ext: "net_contents" },
  { key: "producer_name_address", label: "Producer",          color: "#8a3fc0", exp: "producer_name_address", ext: "producer_name_address" },
  { key: "country_of_origin",     label: "Country of origin", color: "#6b7b00", exp: "country_of_origin",     ext: "country_of_origin" },
  { key: "government_warning",    label: "Government warning", color: "#0050d8", exp: null,                    ext: "government_warning_text" },
];
const FIELD_BY_KEY = Object.fromEntries(FIELDS.map((f) => [f.key, f]));

const reviewer = () => ($("reviewer").value || "").trim();
const mismatchCount = (item) =>
  (item.fields || []).filter((f) => f.status === "mismatch" || f.status === "missing").length;

function verdictWord(o) { return o === "PASS" ? "PASS" : o === "ERROR" ? "ERROR" : "FAIL"; }
function verdictClass(o) { return o === "PASS" ? "v-pass" : o === "ERROR" ? "v-err" : "v-fail"; }
function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso), now = new Date(), s = Math.round((now - d) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString();
}

// ============================ reviewer name ============================
$("reviewer").value = localStorage.getItem("ttb_reviewer") || "";
$("reviewer").addEventListener("input", () =>
  localStorage.setItem("ttb_reviewer", $("reviewer").value));

// ============================ gov banner ============================
$("gov-banner-toggle").onclick = (e) => {
  const btn = e.currentTarget, open = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", String(!open));
  $("gov-banner-content").hidden = open;
};

// ============================ tabs ============================
const TABS = {
  submit: ["tab-submit", "panel-submit"],
  queue: ["tab-queue", "panel-queue"],
  history: ["tab-history", "panel-history"],
};
function showTab(which) {
  for (const [key, [tabId, panelId]] of Object.entries(TABS)) {
    const active = key === which;
    $(tabId).classList.toggle("active", active);
    $(tabId).setAttribute("aria-selected", String(active));
    $(panelId).hidden = !active;
  }
  if (which === "queue") { closeQueueDetail(); loadQueue(); }
  if (which === "history") { closeHistoryDetail(); loadHistory(); }
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$("tab-submit").onclick = () => showTab("submit");
$("tab-queue").onclick = () => showTab("queue");
$("tab-history").onclick = () => showTab("history");

// ============================ submit: mode switch ============================
$("mode-single").onclick = () => setMode("single");
$("mode-batch").onclick = () => setMode("batch");
function setMode(m) {
  const single = m === "single";
  $("mode-single").classList.toggle("active", single);
  $("mode-batch").classList.toggle("active", !single);
  $("mode-single").setAttribute("aria-selected", String(single));
  $("mode-batch").setAttribute("aria-selected", String(!single));
  $("submode-single").hidden = !single;
  $("submode-batch").hidden = single;
}

// ============================ dropzones ============================
function wireDrop(zoneId, inputId, onFiles) {
  const zone = $(zoneId), input = $(inputId);
  zone.onclick = () => input.click();
  zone.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("drag"); }));
  zone.addEventListener("drop", (e) => onFiles(e.dataTransfer.files));
  input.addEventListener("change", () => onFiles(input.files));
}

// ---------- submit single ----------
let oneFile = null;
wireDrop("drop-one", "file-one", (files) => {
  if (!files || !files.length) return;
  oneFile = files[0];
  const img = $("preview-one");
  img.src = URL.createObjectURL(oneFile);
  img.hidden = false;
  $("drop-one").querySelector(".dz-inner").style.display = "none";
  $("go-one").disabled = false;
});

function applicationFromForm() {
  const o = {};
  const b = $("f-brand").value.trim(); if (b) o.brand_name = b;
  const a = $("f-abv").value.trim(); if (a) o.alcohol_content = a;
  const c = $("f-class").value.trim(); if (c) o.class_type = c;
  const n = $("f-net").value.trim(); if (n) o.net_contents = n;
  return o;
}

$("go-one").onclick = async () => {
  if (!oneFile) return;
  const btn = $("go-one"), msg = $("submit-one-msg");
  btn.disabled = true; btn.textContent = "Reading the label…";
  msg.hidden = true;
  try {
    const fd = new FormData();
    fd.append("image", oneFile);
    fd.append("application", JSON.stringify(applicationFromForm()));
    const item = await api("/api/items", { method: "POST", body: fd });
    msg.hidden = false;
    msg.className = "submit-msg ok";
    msg.innerHTML = `✓ Sent to the Review Queue — AI verdict
      <span class="pill ${verdictClass(item.ai_overall)}">${verdictWord(item.ai_overall)}</span>.
      <a href="#" id="goto-review">Open the queue →</a>`;
    $("goto-review").onclick = (e) => { e.preventDefault(); showTab("queue"); openReview(item.id); };
    resetSingle();
    refreshBadges();
  } catch (e) {
    msg.hidden = false; msg.className = "submit-msg err";
    msg.textContent = `Could not process this label: ${e.message}`;
  } finally {
    btn.disabled = false; btn.textContent = "Run & send to Review Queue";
  }
};
function resetSingle() {
  oneFile = null;
  $("preview-one").hidden = true; $("preview-one").src = "";
  $("drop-one").querySelector(".dz-inner").style.display = "";
  $("file-one").value = ""; $("go-one").disabled = true;
}

// ---------- submit batch ----------
let batchFiles = [];
wireDrop("drop-batch", "file-batch", (files) => {
  batchFiles = Array.from(files || []);
  $("batch-count").textContent = batchFiles.length
    ? `${batchFiles.length} image${batchFiles.length === 1 ? "" : "s"} ready.` : "";
  $("go-batch").disabled = batchFiles.length === 0;
});

$("go-batch").onclick = async () => {
  if (!batchFiles.length) return;
  const btn = $("go-batch"), msg = $("submit-batch-msg");
  btn.disabled = true; btn.textContent = `Reading ${batchFiles.length} labels…`;
  msg.hidden = true;
  try {
    const fd = new FormData();
    batchFiles.forEach((f) => fd.append("images", f));
    const appsText = $("batch-apps").value.trim();
    if (appsText) { JSON.parse(appsText); fd.append("applications", appsText); }
    const res = await api("/api/items/batch", { method: "POST", body: fd });
    msg.hidden = false; msg.className = "submit-msg ok";
    msg.innerHTML = `✓ ${res.created} label${res.created === 1 ? "" : "s"} sent to the Review Queue.
      <a href="#" id="goto-review-b">Open the queue →</a>`;
    $("goto-review-b").onclick = (e) => { e.preventDefault(); showTab("queue"); };
    batchFiles = []; $("file-batch").value = ""; $("batch-count").textContent = ""; $("go-batch").disabled = true;
    refreshBadges();
  } catch (e) {
    msg.hidden = false; msg.className = "submit-msg err";
    msg.textContent = `Could not process the batch: ${e.message}`;
  } finally {
    btn.disabled = false; btn.textContent = "Run all & send to Review Queue";
  }
};

// ============================ shared list rendering ============================
function itemRowHTML(item, opts = {}) {
  const o = item.overall || item.ai_overall;
  const mm = mismatchCount(item);
  const statusTag = opts.history
    ? `<span class="pill ${item.status === "approved" ? "v-pass" : "v-fail"}">${item.status === "approved" ? "APPROVED" : "DECLINED"}</span>`
    : `<span class="pill ${verdictClass(o)}">${verdictWord(o)}</span>`;
  const when = opts.history ? (item.decided_at || item.created_at) : item.created_at;
  const sub = opts.history && item.reviewer ? `by ${esc(item.reviewer)} · ` : "";
  const flags = [];
  if (item.edited) flags.push(`<span class="tag tag--edit">edited</span>`);
  if (mm > 0) flags.push(`<span class="tag tag--warn">${mm} field${mm === 1 ? "" : "s"} flagged</span>`);
  return `<button class="item-row ${verdictClass(o)}" data-open="${item.id}">
    <img class="item-thumb" src="/api/items/${item.id}/image" alt="" loading="lazy" />
    <div class="item-main">
      <div class="item-name">${esc(item.filename || "label")}</div>
      <div class="item-meta">${sub}${esc(timeAgo(when))}</div>
      <div class="item-tags">${flags.join("")}</div>
    </div>
    <div class="item-right">${statusTag}<span class="chev">›</span></div>
  </button>`;
}

// ============================ REVIEW QUEUE ============================
$("refresh-queue").onclick = loadQueue;
$("bulk-approve").onclick = bulkApprove;
let queueCache = [];

async function loadQueue() {
  const list = $("queue-list");
  list.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const data = await api("/api/items?status=pending");
    queueCache = data.items || [];
    setBadges(data.counts);
    const passing = queueCache.filter((i) => (i.overall || i.ai_overall) === "PASS");
    $("bulk-approve").hidden = passing.length === 0;
    $("bulk-approve").textContent = `✓ Approve all passing (${passing.length})`;
    $("queue-sub").textContent = queueCache.length
      ? `${queueCache.length} label${queueCache.length === 1 ? "" : "s"} awaiting a decision — exceptions first.`
      : "Nothing waiting — the queue is clear.";
    if (!queueCache.length) {
      list.innerHTML = `<div class="empty">🎉 Queue is empty. Submit labels to get started.</div>`;
      return;
    }
    list.innerHTML = queueCache.map((i) => itemRowHTML(i)).join("");
    list.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => openReview(b.dataset.open));
  } catch (e) {
    list.innerHTML = `<div class="empty err">Could not load the queue: ${esc(e.message)}</div>`;
  }
}

async function bulkApprove() {
  const passing = queueCache.filter((i) => (i.overall || i.ai_overall) === "PASS").map((i) => i.id);
  if (!passing.length) return;
  if (!confirm(`Approve ${passing.length} passing label${passing.length === 1 ? "" : "s"}?`)) return;
  await api("/api/items/bulk-approve", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: passing, reviewer: reviewer() || null }),
  });
  loadQueue(); refreshBadges();
}

function closeQueueDetail() {
  $("queue-detail-view").hidden = true; $("queue-detail-view").innerHTML = "";
  $("queue-list-view").hidden = false;
}

async function openReview(id) {
  $("queue-list-view").hidden = true;
  const view = $("queue-detail-view");
  view.hidden = false;
  view.innerHTML = `<div class="empty">Loading review…</div>`;
  try {
    const item = await api(`/api/items/${id}`);
    renderStation(view, item, { editable: true });
  } catch (e) {
    view.innerHTML = `<div class="empty err">Could not open: ${esc(e.message)}</div>
      <button class="btn btn--outline btn--sm" onclick="history.length">Back</button>`;
  }
}

// ============================ HISTORY ============================
$("refresh-history").onclick = loadHistory;
async function loadHistory() {
  const list = $("history-list");
  list.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const data = await api("/api/items?status=decided");
    setBadges(data.counts);
    const items = data.items || [];
    if (!items.length) { list.innerHTML = `<div class="empty">No decisions yet.</div>`; return; }
    list.innerHTML = items.map((i) => itemRowHTML(i, { history: true })).join("");
    list.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => openHistory(b.dataset.open));
  } catch (e) {
    list.innerHTML = `<div class="empty err">Could not load history: ${esc(e.message)}</div>`;
  }
}
function closeHistoryDetail() {
  $("history-detail-view").hidden = true; $("history-detail-view").innerHTML = "";
  $("history-list-view").hidden = false;
}
async function openHistory(id) {
  $("history-list-view").hidden = true;
  const view = $("history-detail-view");
  view.hidden = false;
  view.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const item = await api(`/api/items/${id}`);
    renderStation(view, item, { editable: false });
  } catch (e) {
    view.innerHTML = `<div class="empty err">Could not open: ${esc(e.message)}</div>`;
  }
}

// ============================ REVIEW STATION (side-by-side) ============================
function renderStation(view, item, { editable }) {
  const o = item.overall || item.ai_overall;
  const back = editable ? "Back to queue" : "Back to history";
  view.innerHTML = `
    <div class="station">
      <div class="station__bar">
        <button class="btn btn--ghost btn--sm" data-back>‹ ${back}</button>
        <div class="station__title">
          <span class="pill ${verdictClass(o)}">${verdictWord(o)}</span>
          <span class="station__name">${esc(item.filename || "label")}</span>
          ${item.edited ? `<span class="tag tag--edit">edited</span>` : ""}
          ${item.status !== "pending" ? `<span class="tag">${esc(item.status)}</span>` : ""}
        </div>
        <div class="station__actions" id="station-actions"></div>
      </div>
      <div class="station__body">
        <div class="station__imgcol">
          <div class="img-toolbar">
            <label class="chk"><input type="checkbox" id="toggle-ocr" checked /> Show all detected text</label>
            <span class="legend" id="legend"></span>
          </div>
          <div class="img-wrap" id="img-wrap"></div>
        </div>
        <div class="station__fieldcol">
          <div id="field-panel"></div>
          <div class="meta-card" id="audit-card"></div>
        </div>
      </div>
    </div>`;

  view.querySelector("[data-back]").onclick = () =>
    editable ? closeQueueDetail() : closeHistoryDetail();

  renderImage(item);
  renderFields(view, item, { editable });
  renderActions(view, item, { editable });
  renderAudit(item);
  buildLegend(item);
}

function renderImage(item) {
  const wrap = $("img-wrap");
  const words = (item.ocr && item.ocr.words) || [];
  const ocrRects = words.map((w) =>
    `<rect class="ocr-box" x="${w.nx}" y="${w.ny}" width="${w.nw}" height="${w.nh}"></rect>`).join("");
  const fieldRects = FIELDS.map((f) => {
    const a = (item.alignment || {})[f.key];
    if (!a || !a.box) return "";
    const b = a.box;
    return `<rect class="field-box" data-fbox="${f.key}" x="${b.nx}" y="${b.ny}"
      width="${b.nw}" height="${b.nh}" style="stroke:${f.color}"></rect>`;
  }).join("");
  wrap.innerHTML = `
    <img class="label-img" src="/api/items/${item.id}/image" alt="Label image" />
    <svg class="overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
      <g id="ocr-layer">${ocrRects}</g>
      <g id="field-layer">${fieldRects}</g>
    </svg>`;
  $("toggle-ocr").onchange = (e) =>
    $("ocr-layer").style.display = e.target.checked ? "" : "none";
  // box → field row linking
  wrap.querySelectorAll("[data-fbox]").forEach((rect) => {
    const key = rect.dataset.fbox;
    rect.addEventListener("mouseenter", () => highlight(key, true));
    rect.addEventListener("mouseleave", () => highlight(key, false));
  });
}

function highlight(key, on) {
  document.querySelectorAll(`[data-fbox="${key}"]`).forEach((el) => el.classList.toggle("hot", on));
  document.querySelectorAll(`[data-frow="${key}"]`).forEach((el) => el.classList.toggle("hot", on));
}

function buildLegend(item) {
  const located = FIELDS.filter((f) => (item.alignment || {})[f.key] && (item.alignment[f.key].box));
  $("legend").innerHTML = located.map((f) =>
    `<span class="legend-item"><span class="swatch" style="background:${f.color}"></span>${esc(f.label)}</span>`).join("");
}

// Merge verification results with raw extraction so EVERY field the AI read
// (or located on the label) gets a row — checked fields carry a verdict, the
// rest show as "not checked". Keeps the table consistent with the image boxes.
function unifiedRows(item) {
  const byField = Object.fromEntries((item.fields || []).map((r) => [r.field, r]));
  const extracted = item.extracted || {};
  const expected = item.expected || {};
  const align = item.alignment || {};
  return FIELDS.map((f) => {
    if (byField[f.key]) return { ...byField[f.key], field: f.key };
    const found = extracted[f.ext];
    const located = align[f.key] && align[f.key].box;
    if ((found == null || found === "") && !located) return null;  // AI saw nothing here
    return {
      field: f.key,
      expected: f.exp ? (expected[f.exp] ?? null) : null,
      found: found ?? null,
      status: "not_checked",
      note: "",
    };
  }).filter(Boolean);
}

let editing = false;
function renderFields(view, item, { editable }) {
  editing = false;
  const panel = $("field-panel");
  const rows = unifiedRows(item);
  const byField = Object.fromEntries(rows.map((r) => [r.field, r]));
  const trs = FIELDS.filter((f) => byField[f.key]).map((f) => {
    const r = byField[f.key];
    const a = (item.alignment || {})[f.key];
    const loc = a && a.box ? `<span class="loc" style="--c:${f.color}" title="Located on the label">◉</span>`
                           : `<span class="loc loc--off" title="Not located on the label">○</span>`;
    return `<tr data-frow="${f.key}" data-fieldrow="${f.key}">
      <td class="fname">${loc} ${esc(f.label)}</td>
      <td class="cell-exp">${cellHTML(r.expected)}</td>
      <td class="cell-found">${cellHTML(r.found)}</td>
      <td class="cell-status"><span class="status-pill s-${esc(r.status)}">${esc((r.status || "").replace("_", " "))}</span></td>
    </tr>${r.note ? `<tr class="note-row"><td></td><td colspan="3" class="note">${esc(r.note)}</td></tr>` : ""}`;
  }).join("");
  panel.innerHTML = `
    <table class="fields review">
      <thead><tr><th>Field</th><th>Application says</th><th>Label shows</th><th>Result</th></tr></thead>
      <tbody>${trs}</tbody>
    </table>`;
  // row → box linking
  panel.querySelectorAll("[data-fieldrow]").forEach((tr) => {
    const key = tr.dataset.fieldrow;
    tr.addEventListener("mouseenter", () => highlight(key, true));
    tr.addEventListener("mouseleave", () => highlight(key, false));
  });
}
function cellHTML(v) { return v == null || v === "" ? `<em>—</em>` : esc(v); }

function renderActions(view, item, { editable }) {
  const bar = $("station-actions");
  if (!editable) { bar.innerHTML = `<span class="decided-note">Decision recorded.</span>`; return; }
  bar.innerHTML = `
    <button class="btn btn--outline btn--sm" id="act-edit">✎ Edit</button>
    <button class="btn btn--outline btn--sm" id="act-redo">↻ Redo</button>
    <button class="btn btn--danger btn--sm" id="act-decline">✗ Decline</button>
    <button class="btn btn--success btn--sm" id="act-approve">✓ Approve</button>`;
  $("act-edit").onclick = () => toggleEdit(view, item);
  $("act-redo").onclick = () => openRedo(view, item);
  $("act-decline").onclick = () => openDecline(view, item);
  $("act-approve").onclick = () => decide(item, "approve");
}

// ---------- edit mode ----------
function toggleEdit(view, item) {
  if (editing) return;
  editing = true;
  $("field-panel").querySelectorAll("[data-fieldrow]").forEach((tr) => {
    const key = tr.dataset.fieldrow;
    const f = FIELD_BY_KEY[key];
    const expCell = tr.querySelector(".cell-exp");
    const foundCell = tr.querySelector(".cell-found");
    const expVal = expCell.querySelector("em") ? "" : expCell.textContent;
    const foundVal = foundCell.querySelector("em") ? "" : foundCell.textContent;
    if (f.exp) expCell.innerHTML = `<input class="edit-inp" data-exp="${key}" value="${esc(expVal)}" />`;
    foundCell.innerHTML = `<input class="edit-inp" data-found="${key}" value="${esc(foundVal)}" />`;
  });
  $("station-actions").innerHTML = `
    <button class="btn btn--ghost btn--sm" id="act-cancel">Cancel</button>
    <button class="btn btn--success btn--sm" id="act-save">Save &amp; re-check</button>`;
  $("act-cancel").onclick = () => openReview(item.id);
  $("act-save").onclick = () => saveEdits(view, item);
}

async function saveEdits(view, item) {
  const expected = { ...(item.expected || {}) };
  const extracted = { ...(item.extracted || {}) };
  let abvEdited = false;
  $("field-panel").querySelectorAll("input[data-exp]").forEach((inp) => {
    const f = FIELD_BY_KEY[inp.dataset.exp];
    const v = inp.value.trim();
    if (v) expected[f.exp] = v; else delete expected[f.exp];
  });
  $("field-panel").querySelectorAll("input[data-found]").forEach((inp) => {
    const f = FIELD_BY_KEY[inp.dataset.found];
    const v = inp.value.trim();
    extracted[f.ext] = v || null;
    if (f.key === "alcohol_content") abvEdited = true;
  });
  // If the reviewer rewrote the alcohol text, re-derive the numeric ABV from it.
  if (abvEdited) extracted.abv_percent = null;
  const btn = $("act-save"); btn.disabled = true; btn.textContent = "Re-checking…";
  try {
    const updated = await api(`/api/items/${item.id}/edit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected, extracted, reviewer: reviewer() || null }),
    });
    renderStation(view, updated, { editable: true });
  } catch (e) {
    alert(`Could not save: ${e.message}`);
    btn.disabled = false; btn.textContent = "Save & re-check";
  }
}

// ---------- redo ----------
function openRedo(view, item) {
  const bar = $("station-actions");
  bar.innerHTML = `
    <span class="redo-hint">Re-run the AI:</span>
    <button class="btn btn--ghost btn--sm" id="redo-cancel">Cancel</button>
    <label class="btn btn--outline btn--sm" for="redo-file">⤓ New image…</label>
    <input type="file" id="redo-file" accept="image/*" hidden />
    <button class="btn btn--primary btn--sm" id="redo-same">↻ Re-run on this image</button>`;
  $("redo-cancel").onclick = () => renderActions(view, item, { editable: true });
  $("redo-same").onclick = () => runRedo(view, item, null);
  $("redo-file").onchange = (e) => { if (e.target.files[0]) runRedo(view, item, e.target.files[0]); };
}
async function runRedo(view, item, file) {
  $("station-actions").innerHTML = `<span class="redo-hint">Re-running the AI…</span>`;
  const fd = new FormData();
  if (file) fd.append("image", file);
  if (reviewer()) fd.append("reviewer", reviewer());
  try {
    const updated = await api(`/api/items/${item.id}/redo`, { method: "POST", body: fd });
    renderStation(view, updated, { editable: true });
  } catch (e) {
    alert(`Redo failed: ${e.message}`);
    renderActions(view, item, { editable: true });
  }
}

// ---------- decline ----------
function openDecline(view, item) {
  const bar = $("station-actions");
  bar.innerHTML = `
    <input type="text" id="decline-note" class="decline-inp" placeholder="Reason (optional)" />
    <button class="btn btn--ghost btn--sm" id="decline-cancel">Cancel</button>
    <button class="btn btn--danger btn--sm" id="decline-confirm">Confirm decline</button>`;
  $("decline-note").focus();
  $("decline-cancel").onclick = () => renderActions(view, item, { editable: true });
  $("decline-confirm").onclick = () => decide(item, "decline", $("decline-note").value.trim());
  $("decline-note").onkeydown = (e) => { if (e.key === "Enter") decide(item, "decline", e.target.value.trim()); };
}

async function decide(item, decision, note) {
  try {
    await api(`/api/items/${item.id}/decide`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer: reviewer() || null, note: note || null }),
    });
    closeQueueDetail();
    loadQueue();
    refreshBadges();
  } catch (e) {
    alert(`Could not record decision: ${e.message}`);
  }
}

// ---------- audit ----------
function renderAudit(item) {
  const card = $("audit-card");
  const expected = item.expected || {};
  const expList = Object.keys(expected).length
    ? Object.entries(expected).map(([k, v]) => `<li><span>${esc(k.replace(/_/g, " "))}</span><strong>${esc(v)}</strong></li>`).join("")
    : `<li class="muted">No application data was provided.</li>`;
  const audit = (item.audit || []).slice().reverse().map((a) =>
    `<li><span class="audit-act audit-${esc(a.action)}">${esc(a.action)}</span>
       ${a.by ? `by ${esc(a.by)} ` : ""}<span class="audit-when">${esc(timeAgo(a.at))}</span>
       ${a.detail ? `<div class="audit-detail">${esc(a.detail)}</div>` : ""}</li>`).join("");
  card.innerHTML = `
    <details open><summary>Application on file</summary><ul class="kv">${expList}</ul></details>
    <details><summary>Audit trail (${(item.audit || []).length})</summary><ul class="audit">${audit}</ul></details>
    <div class="proc-time">${item.elapsed_ms ? `Processed in ${(item.elapsed_ms / 1000).toFixed(1)}s` : ""}</div>`;
}

// ============================ badges + service status ============================
function setBadges(counts) {
  if (!counts) return;
  const q = $("queue-badge"); q.textContent = counts.pending || 0; q.hidden = !counts.pending;
  const h = $("hist-badge"); const decided = (counts.approved || 0) + (counts.declined || 0);
  h.textContent = decided; h.hidden = decided === 0;
}
async function refreshBadges() {
  try { setBadges(await api("/api/stats")); } catch { /* ignore */ }
}

fetch("/health").then((r) => r.json()).then((h) => {
  const dot = $("svc-dot"), txt = $("svc-status");
  if (h.status === "ok" && h.configured) { dot.classList.add("ok"); txt.textContent = "Service online"; }
  else { dot.classList.add("down"); txt.textContent = "Not configured"; }
  if (h.model) $("model-tag").textContent = `Model: ${h.model}`;
}).catch(() => { $("svc-dot").classList.add("down"); $("svc-status").textContent = "Service offline"; });

refreshBadges();
