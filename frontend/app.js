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

function fieldsTable(fields) {
  const rows = fields.map((f) => `
    <tr>
      <td class="field-name">${esc(FIELD_LABELS[f.field] || titleize(f.field))}</td>
      <td>${esc(f.expected) || "<em>—</em>"}</td>
      <td>${esc(f.found) || "<em>—</em>"}</td>
      <td><span class="status-pill s-${esc(f.status)}">${esc(f.status.replace("_", " "))}</span>
          ${f.note ? `<span class="note">${esc(f.note)}</span>` : ""}</td>
    </tr>`).join("");
  return `<table class="fields">
    <thead><tr><th>Field</th><th>Application says</th><th>Label shows</th><th>Result</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function verdictBox(overall, ms) {
  const pass = overall === "PASS";
  const mark = pass ? "✓" : "✗";
  const word = pass ? "PASS" : "FAIL";
  const msTxt = ms != null ? `<span class="ms">${(ms / 1000).toFixed(1)}s</span>` : "";
  return `<div class="verdict ${pass ? "pass" : "fail"}">
            <span class="mark">${mark}</span><span>${word}</span>${msTxt}</div>`;
}

// ---------- tabs ----------
function showTab(which) {
  const one = which === "one";
  $("tab-one").classList.toggle("active", one);
  $("tab-batch").classList.toggle("active", !one);
  $("tab-one").setAttribute("aria-selected", one);
  $("tab-batch").setAttribute("aria-selected", !one);
  $("panel-one").hidden = !one;
  $("panel-batch").hidden = one;
}
$("tab-one").onclick = () => showTab("one");
$("tab-batch").onclick = () => showTab("batch");

// ---------- dropzone wiring ----------
function wireDrop(zoneId, inputId, onFiles) {
  const zone = $(zoneId), input = $(inputId);
  zone.onclick = () => input.click();
  zone.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault(); zone.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault(); zone.classList.remove("drag");
  }));
  zone.addEventListener("drop", (e) => onFiles(e.dataTransfer.files));
  input.addEventListener("change", () => onFiles(input.files));
}

// ---------- single ----------
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
  const btn = $("go-one"), out = $("result-one");
  btn.disabled = true; btn.classList.add("loading"); btn.textContent = "Checking…";
  out.hidden = false; out.innerHTML = `<p class="hint">Reading the label…</p>`;
  try {
    const fd = new FormData();
    fd.append("image", oneFile);
    fd.append("application", JSON.stringify(applicationFromForm()));
    const resp = await fetch("/verify", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Verification failed.");
    out.innerHTML = verdictBox(data.overall, data.elapsed_ms) + fieldsTable(data.fields);
  } catch (e) {
    out.innerHTML = `<div class="errbox">Could not check this label: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.classList.remove("loading"); btn.textContent = "Verify Label";
  }
};

// ---------- batch ----------
let batchFiles = [];
wireDrop("drop-batch", "file-batch", (files) => {
  batchFiles = Array.from(files || []);
  $("batch-count").textContent = batchFiles.length
    ? `${batchFiles.length} image${batchFiles.length === 1 ? "" : "s"} ready.` : "";
  $("go-batch").disabled = batchFiles.length === 0;
});

$("go-batch").onclick = async () => {
  if (!batchFiles.length) return;
  const btn = $("go-batch"), out = $("result-batch"), sum = $("batch-summary");
  btn.disabled = true; btn.classList.add("loading"); btn.textContent = `Checking ${batchFiles.length}…`;
  sum.hidden = true; out.innerHTML = `<p class="hint">Reading ${batchFiles.length} labels…</p>`;
  try {
    const fd = new FormData();
    batchFiles.forEach((f) => fd.append("images", f));
    const appsText = $("batch-apps").value.trim();
    if (appsText) {
      JSON.parse(appsText); // validate before sending
      fd.append("applications", appsText);
    }
    const resp = await fetch("/verify/batch", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Batch failed.");
    renderBatch(data);
  } catch (e) {
    out.innerHTML = `<div class="errbox">Could not check the batch: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.classList.remove("loading"); btn.textContent = "Verify All Labels";
  }
};

function renderBatch(data) {
  const s = data.summary || {};
  $("batch-summary").hidden = false;
  $("batch-summary").innerHTML = `
    <div class="chip total"><span class="n">${s.total || 0}</span>Total</div>
    <div class="chip pass"><span class="n">${s.pass || 0}</span>Passed</div>
    <div class="chip fail"><span class="n">${(s.fail || 0) + (s.error || 0)}</span>Need review</div>`;
  $("result-batch").innerHTML = (data.results || []).map((r) => {
    const isPass = r.overall === "PASS";
    const cls = isPass ? "s-match" : "s-mismatch";
    const word = r.overall === "ERROR" ? "ERROR" : (isPass ? "PASS" : "FAIL");
    const detail = r.error
      ? `<div class="errbox">${esc(r.error)}</div>`
      : (r.fields ? fieldsTable(r.fields) : "");
    return `<details class="brow">
      <summary><span class="bstatus ${cls}">${esc(word)}</span>
        <span class="bname">${esc(r.filename || "(unnamed)")}</span></summary>
      <div class="bdetail">${detail}</div></details>`;
  }).join("");
}

// ---------- model tag ----------
fetch("/health").then((r) => r.json()).then((h) => {
  if (h.model) $("model-tag").textContent = `Model: ${h.model}.`;
}).catch(() => {});
