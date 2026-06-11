"use strict";

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
const titleize = (s) => s.replace(/_/g, " ");

const FIELD_LABELS = {
  brand_name: "Brand name",
  alcohol_content: "Alcohol content",
  government_warning: "Government warning",
  class_type: "Class / type",
  net_contents: "Net contents",
  producer_name_address: "Producer",
  country_of_origin: "Country of origin",
};

// ---------- shared render helpers (reused by live results AND history) ----------
function fieldsTableHTML(fields) {
  const rows = (fields || []).map((f) => `
    <tr>
      <td class="field-name">${esc(FIELD_LABELS[f.field] || titleize(f.field))}</td>
      <td>${esc(f.expected) || "<em>—</em>"}</td>
      <td>${esc(f.found) || "<em>—</em>"}</td>
      <td><span class="status-pill s-${esc(f.status)}">${esc((f.status || "").replace("_", " "))}</span>
          ${f.note ? `<span class="note">${esc(f.note)}</span>` : ""}</td>
    </tr>`).join("");
  return `<table class="fields">
    <thead><tr><th>Field</th><th>Application says</th><th>Label shows</th><th>Result</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function verdictAlertHTML(overall, ms) {
  const pass = overall === "PASS";
  const cls = pass ? "alert--pass" : (overall === "ERROR" ? "alert--err" : "alert--fail");
  const mark = pass ? "✓" : (overall === "ERROR" ? "⚠" : "✗");
  const word = pass ? "PASS" : overall;
  const msTxt = ms != null ? `<span class="ms">${(ms / 1000).toFixed(1)}s</span>` : "";
  return `<div class="alert ${cls}"><span class="mark">${mark}</span>
            <span class="alert__title">${esc(word)}</span>${msTxt}</div>`;
}

function singleResultHTML(r) {
  return verdictAlertHTML(r.overall, r.elapsed_ms) + fieldsTableHTML(r.fields);
}

function batchSummaryHTML(s) {
  s = s || {};
  return `<div class="summary">
    <div class="chip total"><span class="n">${s.total || 0}</span>Total</div>
    <div class="chip pass"><span class="n">${s.pass || 0}</span>Passed</div>
    <div class="chip fail"><span class="n">${(s.fail || 0) + (s.error || 0)}</span>Need review</div>
  </div>`;
}

function batchRowsHTML(results) {
  return (results || []).map((r) => {
    const isPass = r.overall === "PASS";
    const cls = isPass ? "s-match" : "s-mismatch";
    const word = r.overall === "ERROR" ? "ERROR" : (isPass ? "PASS" : "FAIL");
    const detail = r.error
      ? `<div class="alert alert--err">${esc(r.error)}</div>`
      : fieldsTableHTML(r.fields);
    return `<details class="brow">
      <summary><span class="bstatus ${cls}">${esc(word)}</span>
        <span class="bname">${esc(r.filename || "(unnamed)")}</span></summary>
      <div class="bdetail">${detail}</div></details>`;
  }).join("");
}

function summarize(results) {
  return {
    total: results.length,
    pass: results.filter((r) => r.overall === "PASS").length,
    fail: results.filter((r) => r.overall === "FAIL").length,
    error: results.filter((r) => r.overall === "ERROR").length,
  };
}

// ---------- gov banner ----------
$("gov-banner-toggle").onclick = (e) => {
  const btn = e.currentTarget;
  const open = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", String(!open));
  $("gov-banner-content").hidden = open;
};

// ---------- tabs ----------
const TABS = { one: ["tab-one", "panel-one"], batch: ["tab-batch", "panel-batch"], history: ["tab-history", "panel-history"] };
function showTab(which) {
  for (const [key, [tabId, panelId]] of Object.entries(TABS)) {
    const active = key === which;
    $(tabId).classList.toggle("active", active);
    $(tabId).setAttribute("aria-selected", String(active));
    $(panelId).hidden = !active;
  }
  if (which === "history") renderHistory();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$("tab-one").onclick = () => showTab("one");
$("tab-batch").onclick = () => showTab("batch");
$("tab-history").onclick = () => showTab("history");

// ---------- dropzone wiring ----------
function wireDrop(zoneId, inputId, onFiles) {
  const zone = $(zoneId), input = $(inputId);
  zone.onclick = () => input.click();
  zone.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("drag"); }));
  zone.addEventListener("drop", (e) => onFiles(e.dataTransfer.files));
  input.addEventListener("change", () => onFiles(input.files));
}

// ---------- single verify ----------
let oneFile = null;
let lastSingle = null;
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
  const btn = $("go-one"), out = $("result-one");
  btn.disabled = true; btn.textContent = "Checking…";
  out.hidden = false; out.innerHTML = `<p class="hint">Reading the label…</p>`;
  try {
    const fd = new FormData();
    fd.append("image", oneFile);
    fd.append("application", JSON.stringify(applicationFromForm()));
    const resp = await fetch("/verify", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Verification failed.");
    lastSingle = data;
    out.innerHTML = singleResultHTML(data);
    mountSaveUI(out, "single", [data], `Label: ${data.filename || "result"}`);
  } catch (e) {
    out.innerHTML = `<div class="alert alert--err">Could not check this label: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Verify Label";
  }
};

// ---------- batch verify ----------
let batchFiles = [];
let lastBatch = null;
wireDrop("drop-batch", "file-batch", (files) => {
  batchFiles = Array.from(files || []);
  $("batch-count").textContent = batchFiles.length
    ? `${batchFiles.length} image${batchFiles.length === 1 ? "" : "s"} ready.` : "";
  $("go-batch").disabled = batchFiles.length === 0;
});

$("go-batch").onclick = async () => {
  if (!batchFiles.length) return;
  const btn = $("go-batch"), out = $("result-batch"), sum = $("batch-summary"), saveWrap = $("save-batch-wrap");
  btn.disabled = true; btn.textContent = `Checking ${batchFiles.length}…`;
  sum.hidden = true; saveWrap.hidden = true; saveWrap.innerHTML = "";
  out.innerHTML = `<p class="hint">Reading ${batchFiles.length} labels…</p>`;
  try {
    const fd = new FormData();
    batchFiles.forEach((f) => fd.append("images", f));
    const appsText = $("batch-apps").value.trim();
    if (appsText) { JSON.parse(appsText); fd.append("applications", appsText); }
    const resp = await fetch("/verify/batch", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Batch failed.");
    lastBatch = data;
    sum.hidden = false; sum.innerHTML = batchSummaryHTML(data.summary);
    out.innerHTML = batchRowsHTML(data.results);
    saveWrap.hidden = false;
    mountSaveUI(saveWrap, "batch", data.results, defaultBatchName());
  } catch (e) {
    out.innerHTML = `<div class="alert alert--err">Could not check the batch: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Verify All Labels";
  }
};

function defaultBatchName() {
  const d = new Date();
  return `Batch — ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

// ---------- save-to-history UI ----------
function mountSaveUI(container, kind, results, defaultName) {
  const wrap = document.createElement("div");
  wrap.className = "save-wrap";
  wrap.innerHTML = `<button class="btn btn--success btn--sm save-open">💾 Save ${kind === "batch" ? "batch " : ""}to history as…</button>`;
  const openBtn = wrap.querySelector(".save-open");
  openBtn.onclick = () => {
    wrap.innerHTML = `
      <div class="save-row">
        <label for="save-name">Save as:</label>
        <input id="save-name" type="text" value="${esc(defaultName)}" />
        <button class="btn btn--success btn--sm save-confirm">Save</button>
        <button class="btn btn--outline btn--sm save-cancel">Cancel</button>
      </div>`;
    const input = wrap.querySelector("#save-name");
    input.focus(); input.select();
    wrap.querySelector(".save-cancel").onclick = () => mountSaveUI(container, kind, results, defaultName);
    const doSave = () => {
      const name = input.value.trim() || defaultName;
      addRecord({ name, kind, summary: summarize(results), results });
      wrap.innerHTML = `<div class="saved-toast">✓ Saved “${esc(name)}” to History.</div>`;
      updateBadge();
    };
    wrap.querySelector(".save-confirm").onclick = doSave;
    input.onkeydown = (e) => { if (e.key === "Enter") doSave(); };
  };
  // Replace existing save UI in this container (avoid duplicates).
  const existing = container.querySelector(".save-wrap");
  if (existing && existing !== container) existing.remove();
  if (container.id === "save-batch-wrap") { container.innerHTML = ""; container.appendChild(wrap); }
  else container.appendChild(wrap);
}

// ---------- history store (localStorage) ----------
const HKEY = "ttb_history_v1";
function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch { return []; }
}
function saveHistory(arr) { localStorage.setItem(HKEY, JSON.stringify(arr)); }
function addRecord(rec) {
  const arr = loadHistory();
  rec.id = "h" + Date.now() + Math.floor(Math.random() * 1000);
  rec.savedAt = new Date().toISOString();
  arr.unshift(rec);
  saveHistory(arr);
}
function deleteRecord(id) { saveHistory(loadHistory().filter((r) => r.id !== id)); renderHistory(); updateBadge(); }
function updateBadge() {
  const n = loadHistory().length;
  const badge = $("hist-badge");
  badge.textContent = n; badge.hidden = n === 0;
}

function renderHistory() {
  const arr = loadHistory();
  $("clear-history").hidden = arr.length === 0;
  const list = $("history-list");
  if (!arr.length) {
    list.innerHTML = `<div class="empty">No saved verifications yet.<br />
      Run a check, then choose <strong>“Save to history”</strong> to keep it here.</div>`;
    return;
  }
  list.innerHTML = arr.map((rec) => {
    const when = new Date(rec.savedAt).toLocaleString();
    const s = rec.summary || {};
    const body = rec.kind === "batch"
      ? batchSummaryHTML(s) + batchRowsHTML(rec.results)
      : singleResultHTML(rec.results[0] || {});
    return `<div class="hist-item">
      <div class="hist-item__head">
        <div>
          <div class="hist-item__name">${esc(rec.name)}</div>
          <div class="hist-item__time">🕒 ${esc(when)} · ${rec.kind === "batch" ? "Batch" : "Single label"}</div>
        </div>
        <div class="hist-item__counts">
          <span class="mini-chip pass">${s.pass || 0} pass</span>
          <span class="mini-chip fail">${(s.fail || 0) + (s.error || 0)} review</span>
        </div>
        <div class="hist-actions">
          <button class="linkbtn" data-view="${rec.id}">View ▾</button>
          <button class="linkbtn danger" data-del="${rec.id}">Delete</button>
        </div>
      </div>
      <div class="hist-item__body" id="body-${rec.id}" hidden>${body}</div>
    </div>`;
  }).join("");

  list.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => {
    const body = $("body-" + b.dataset.view);
    const show = body.hidden; body.hidden = !show;
    b.textContent = show ? "Hide ▴" : "View ▾";
  });
  list.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => {
    if (confirm("Delete this saved verification?")) deleteRecord(b.dataset.del);
  });
}

$("clear-history").onclick = () => {
  if (confirm("Delete ALL saved verifications? This cannot be undone.")) {
    saveHistory([]); renderHistory(); updateBadge();
  }
};

// ---------- service status + model tag ----------
fetch("/health").then((r) => r.json()).then((h) => {
  const dot = $("svc-dot"), txt = $("svc-status");
  if (h.status === "ok" && h.configured) { dot.classList.add("ok"); txt.textContent = "Service online"; }
  else { dot.classList.add("down"); txt.textContent = "Not configured"; }
  if (h.model) $("model-tag").textContent = `Model: ${h.model}`;
}).catch(() => { $("svc-dot").classList.add("down"); $("svc-status").textContent = "Service offline"; });

updateBadge();
