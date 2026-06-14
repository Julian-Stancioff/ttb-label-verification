# TTB Label Verification — Build Spec (shared contract)

All agents build against this contract. Keep it authoritative; update it if a decision changes.

## Goal

Given a **label image** and the **expected COLA application fields**, return — in **≤ 5 seconds** —
a per-field verdict (match / mismatch / missing) plus an overall PASS/FAIL, through a UI a
non-technical 70-something agent can use, with **batch** support for hundreds of labels.

## Architecture

- **Backend:** Python 3, **FastAPI** + Uvicorn. Single service also serves the static frontend.
- **Vision/extraction:** **OpenRouter** (OpenAI-compatible Chat Completions API), model from
  `LLM_MODEL` (default `anthropic/claude-sonnet-4.5`), one multimodal call per label that returns
  **strict JSON** of the fields read off the label image.
- **OCR:** **Tesseract** (`pytesseract`) reads word-level boxes locally; `alignment.py` links each
  extracted field value to the OCR words that printed it, for image highlighting in the review UI.
- **Matching:** deterministic Python — no second LLM call (keeps us under 5s and auditable).
- **Frontend:** static HTML/CSS/JS (no build step), three tabs: Submit / Review Queue / History.
- **Storage:** SQLite (`store.py`) on a data volume (`DATA_DIR`) persists the review queue — each
  item, its image, OCR/alignment geometry, reviewer edits, the decision, and an audit trail. (v1 was
  stateless; v2 added the persistent queue because the workflow needs a durable, auditable record.
  Synthetic labels only; label text is public, not PII — see APPROACH.md.)

## Config (`.env`, loaded by backend; never commit)

```
OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=anthropic/claude-sonnet-4.5
HOST=0.0.0.0
PORT=8000
```

## Extraction contract

Call OpenRouter chat/completions with a text instruction + the image (as a `data:` URL).
Demand strict JSON (use `response_format={"type":"json_object"}`). Expected shape:

```json
{
  "brand_name": "string|null",
  "class_type": "string|null",
  "alcohol_content": "string|null",      // verbatim, e.g. "45% Alc./Vol. (90 Proof)"
  "abv_percent": 45.0,                     // numeric ABV if determinable, else null
  "net_contents": "string|null",
  "producer_name_address": "string|null",
  "country_of_origin": "string|null",
  "government_warning_text": "string|null",// verbatim transcription, preserve case
  "government_warning_is_allcaps_header": true, // is the "GOVERNMENT WARNING:" header literally uppercase on the label
  "legibility_notes": "string|null"        // glare/angle/blur observations
}
```

The model must transcribe the warning **verbatim** (exact case/punctuation) — do not normalize.

## Verification rules

Input: `expected` application fields + `extracted` fields. Produce a list of field results
`{field, expected, found, status, note}` where status ∈ `match | mismatch | missing | not_checked`.

- **brand_name** — apply judgment (Dave): compare case-insensitively, collapse whitespace, treat
  curly/straight apostrophes and `&`/`and` as equal, ignore trailing punctuation. `STONE'S THROW`
  == `Stone's Throw` ⇒ match. Genuinely different names ⇒ mismatch.
- **abv** — parse a percentage from both expected and `abv_percent`/`alcohol_content`; match if
  within **±0.0** by default, but tolerate formatting (e.g. `45`, `45%`, `45.0% Alc./Vol.`). Note
  TTB ABV tolerances exist but for the prototype require numeric equality and flag differences.
- **government_warning** — the strict one (Jenny). PASS only if ALL hold:
  1. A warning is present.
  2. The header `GOVERNMENT WARNING:` appears in **all caps** (`government_warning_is_allcaps_header == true`
     AND the transcribed text contains the literal uppercase `GOVERNMENT WARNING:`).
  3. The body matches the canonical statutory text **word-for-word** (see below), after collapsing
     internal whitespace/newlines only. Any paraphrase, omission, or title-case header ⇒ FAIL with a
     specific reason (e.g. "header not all caps", "wording differs at: …").
- **net_contents / class_type / producer / country** — checked when provided in the application;
  case-insensitive, whitespace-tolerant; mismatch flagged, absence in application ⇒ `not_checked`.

Overall verdict = **PASS** iff government_warning passes AND every *provided* expected field matches.

### Canonical Government Warning (27 CFR 16.21)

```
GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.
```

## API

**Core / frontend**

- `GET /health` → `{"status":"ok", model, configured}`
- `GET /` → the frontend page

**Review-queue API (persistent — backs the UI)**

- `POST /api/items` — intake one label (runs the pipeline, persists a pending queue item).
- `POST /api/items/batch` — intake many; one queue item each.
- `GET /api/items?status=pending|decided|all` — list queue/history + status counts.
- `GET /api/items/{id}` — full item incl. OCR + alignment geometry.
- `GET /api/items/{id}/image` — the stored label image.
- `POST /api/items/{id}/edit` — reviewer corrects either side; deterministic re-match (no AI).
- `POST /api/items/{id}/redo` — re-run the AI pipeline (optional replacement image).
- `POST /api/items/{id}/decide` — approve / decline (with note); appended to audit trail.
- `POST /api/items/bulk-approve` — approve many pending items at once.
- `DELETE /api/items/{id}` — remove an item + its image.

**Legacy stateless endpoints (kept for scripting/compatibility)**

- `POST /verify` — multipart: `image` (file) + `application` (JSON string of expected fields).
  Returns `{overall, fields[], extracted, elapsed_ms, warning_detail}`.
- `POST /verify/batch` — multipart: many `images[]` + `applications` (JSON array, matched by
  filename or index). Returns `{results:[{filename, overall, fields[], ...}], summary:{pass,fail,error,total}}`.
  Process concurrently (bounded) so batches stay responsive.

## UX requirements (Sarah / Dave / Jenny)

- One screen. Giant "Upload Label" drop zone + button. Expected-fields form with clear labels.
- Result is unmistakable: big green ✓ PASS or red ✗ FAIL, then a plain-language per-field table.
- The warning result spells out *why* it failed in human terms.
- Batch tab: drop many files, table of pass/fail, click a row for detail. Show a running count.
- No jargon, no hunting for buttons. Works on a plain office browser.

## Non-functional

- p50 latency ≤ 5s per label (single OpenRouter call; stream nothing, ask for compact JSON).
- Graceful errors: unreadable image, model timeout, bad JSON → clear message, never a stack trace.
- Tests for the matching logic (pure functions) incl. STONE'S THROW and warning-cheat cases.
