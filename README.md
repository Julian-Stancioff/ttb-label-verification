# TTB Alcohol Label Verification — Prototype

AI-assisted verification that an alcohol-beverage **label image** matches the data in its
**COLA application**, for the Alcohol and Tobacco Tax and Trade Bureau (TTB).

**🌐 Live demo:** https://51-81-34-160.nip.io
*(Prototype only. Not connected to COLA. Uses synthetic sample labels; see [Data & privacy](#data--privacy).)*

---

## What it does

An agent uploads a label image (or a batch of them) plus the expected application fields. Within a
few seconds the AI reads the label, a deterministic check compares it to the application, and the
result lands in a **review queue** where a human makes the final call — the workflow a compliance
team actually needs, not just a one-shot verdict.

Per field, the app reports whether the label matches:

- **Brand name** — case/punctuation-tolerant per agent judgment (`STONE'S THROW` == `Stone's Throw`)
- **Alcohol content (ABV)** — numeric match, tolerant of formatting (`45`, `45%`, `45% Alc./Vol.`)
- **Government Health Warning** — present **and exact**: `GOVERNMENT WARNING:` in all-caps,
  word-for-word per 27 CFR 16.21 (catches paraphrases, title-case headers, omissions)
- Plus **class/type** and **net contents** when supplied in the application

### Three screens: Submit → Review Queue → History

- **Submit** — drop one label or a whole batch (hundreds), with the expected application fields.
  Each label is run through the AI and dropped into the queue.
- **Review Queue** — an **exception-first** worklist: errors and FAILs float to the top, clean
  passes sink to the bottom and can be **one-click or bulk approved**. Opening an item shows a
  **side-by-side review station**: the label image annotated with **OCR bounding boxes** (every
  word faint, the located fields highlighted and hover-linked to the comparison rows) next to an
  **editable** expected-vs-extracted table. The reviewer can **Approve**, **Decline** (with a note),
  **Edit** either side inline (instant deterministic re-match, no AI call), or **Redo** the AI
  (optionally swapping in a better photo).
- **History** — every approved/declined item with its reviewer, timestamp, decision note, and a
  full **audit trail** of what happened to it.

The interface is built to the **U.S. Web Design System (USWDS)** — the official standard for
federal websites — so it reads as a genuine TTB/Treasury system: the official-government banner,
the agency seal header, navy primary navigation, and USWDS alert/button components.

## Screenshot

The single-label submit screen, in the federal design system — official banner, agency seal, navy nav:

![UI](docs/screenshot-home.png)

## How it works

```
Browser (static HTML/CSS/JS)
        │  multipart upload (image + expected fields)
        ▼
FastAPI ─┬─► OpenRouter (vision model) ──► strict-JSON label fields ─┐
         │                                                           ├─► deterministic match
         └─► Tesseract OCR ────────────► word boxes ──► alignment ───┘   (brand judgment · ABV · EXACT warning)
                                                                         │
                                                                         ▼
                              persist to SQLite review queue  ──►  human approve / decline
                                  (item + image + audit trail)        (≈4–5s to first verdict)
```

- One vision call per label extracts the printed fields as JSON; **Tesseract** independently reads
  word-level bounding boxes; matching is **deterministic Python** (no second LLM call) so verdicts
  are fast, auditable, and consistent.
- `alignment.py` links each extracted field value to the OCR words that printed it, so the review
  station can highlight the exact region on the image.
- The government-warning check is the strict one: it enforces the all-caps header and compares the
  body to the statutory text word-for-word.

See [`docs/SPEC.md`](docs/SPEC.md) for the full contract and [`docs/APPROACH.md`](docs/APPROACH.md)
for approach, tools, assumptions, and trade-offs.

## Project layout

```
backend/
  app/
    config.py        # .env-backed settings (incl. persistent data dir)
    openrouter.py    # async OpenRouter (OpenAI-compatible) client
    extraction.py    # image -> structured label fields (strict JSON)
    ocr.py           # Tesseract word-level OCR boxes
    alignment.py     # link extracted field values -> OCR word boxes
    verification.py  # deterministic matching rules (pure functions)
    service.py       # one-label pipeline: extract + OCR + match + align
    store.py         # SQLite review-queue store + audit trail
    main.py          # FastAPI: /health, /verify*, /api/items*, serves frontend
  tests/             # 38 unit tests (matching, alignment, store, API, mocked client)
frontend/            # single-page UI (index.html, style.css, app.js) — no build step
samples/             # generator + 15 synthetic test labels + applications.json
docs/                # SPEC.md, APPROACH.md
```

## Run it locally

Requires Python 3.12 (3.11–3.13 fine; 3.14 lacks some wheels) and the **Tesseract OCR** engine.
[`uv`](https://docs.astral.sh/uv/) recommended but plain `venv` works.

```bash
# Tesseract is a system package (not pip):
sudo apt-get install -y tesseract-ocr      # macOS: brew install tesseract

git clone https://github.com/Julian-Stancioff/ttb-label-verification.git
cd ttb-label-verification

# 1. Configure your OpenRouter key
cp .env.example .env        # then edit .env and set OPENROUTER_API_KEY

# 2. Install + run
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt          # or: pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. Open http://localhost:8000
```

The review queue is stored in a SQLite DB under a data directory (`./data` locally, or `DATA_DIR`);
it and the `data/images/` folder are created on first run.

### Tests

```bash
cd backend && source .venv/bin/activate
python -m pytest -q          # 38 passing
```

### Generate sample labels

```bash
cd backend && source .venv/bin/activate     # Pillow is already in requirements.txt
python ../samples/generate_samples.py       # writes samples/images/*.png + applications.json
```

## Configuration (`.env`)

| Key | Default | Notes |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | **required** |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `anthropic/claude-sonnet-4.5` | any OpenRouter vision model |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | server bind |
| `BATCH_CONCURRENCY` | `8` | parallel labels per batch request |
| `REQUEST_TIMEOUT` | `20` | per-label model timeout (s) |
| `DATA_DIR` | `/data` if present, else `./data` | SQLite DB + stored label images |

## API

**Review-queue API** (persistent — backs the UI):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/items` | Intake one label (runs AI, adds to queue) |
| `POST` | `/api/items/batch` | Intake many labels, one queue item each |
| `GET` | `/api/items?status=pending\|decided\|all` | List queue / history + counts |
| `GET` | `/api/items/{id}` | Full item (incl. OCR + alignment geometry) |
| `GET` | `/api/items/{id}/image` | The stored label image |
| `POST` | `/api/items/{id}/edit` | Reviewer corrects either side; deterministic re-match |
| `POST` | `/api/items/{id}/redo` | Re-run AI (optional replacement image) |
| `POST` | `/api/items/{id}/decide` | Approve / decline (with note) |
| `POST` | `/api/items/bulk-approve` | Approve many pending items |
| `DELETE` | `/api/items/{id}` | Remove an item + its image |
| `GET` | `/health` | `{status, model, configured}` |

**Legacy stateless endpoints** (kept for scripting/compatibility, no persistence):

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/verify` | `image` (file) + `application` (JSON string) | `{overall, fields[], extracted, elapsed_ms, warning_detail}` |
| `POST` | `/verify/batch` | `images[]` + `applications` (JSON array) | `{results[], summary{pass,fail,error,total}}` |

```bash
# stateless one-off
curl -s -X POST https://51-81-34-160.nip.io/verify \
  -F "image=@samples/images/01_pass_old_tom.png" \
  -F 'application={"brand_name":"Old Tom Distillery","alcohol_content":"45% Alc./Vol."}'

# send to the review queue
curl -s -X POST https://51-81-34-160.nip.io/api/items \
  -F "image=@samples/images/01_pass_old_tom.png" \
  -F 'application={"brand_name":"Old Tom Distillery","alcohol_content":"45% Alc./Vol."}'
```

## Data & privacy

To support a real human-review workflow with an audit trail, the prototype **does** persist each
submission server-side: the label image, the expected/extracted fields, the AI verdict, OCR
geometry, and every reviewer action go into a local SQLite DB on the host (`DATA_DIR`). Nothing is
sent anywhere except the one vision call to the configured model endpoint.

This is a deliberate prototype trade-off against the brief's "no sensitive PII storage" note:
the demo runs only on **synthetic sample labels**, and alcohol-label fields (brand, ABV, net
contents, the statutory warning) are public-facing text, not personal PII. The store is single-host
and unauthenticated — fine for a prototype, **not** production. A production version would add
authentication, per-user access control, encryption at rest, and a retention/redaction policy.

## Deployment

The live demo runs on a Linux VPS: a `systemd` unit runs `uvicorn` on `127.0.0.1:8000`, and
**Caddy** terminates HTTPS (automatic Let's Encrypt cert) at `51-81-34-160.nip.io`, reverse-proxying
to the app. The review-queue SQLite DB and stored images live in a data directory on the host
(`DATA_DIR`, default `./data`). A `Dockerfile` is included for container deployment, with the same
data directory mounted as a `/data` volume.

## Note on how this was built

This prototype was developed using [**Gas Town**](https://github.com/gastownhall/gastown), a
multi-agent orchestration system, as the workflow harness — the work was tracked as **beads**
(issues) in a Gas Town *rig*, and an autonomous *polecat* agent produced the initial backend-core
commit. See [`docs/APPROACH.md`](docs/APPROACH.md) for details.

## License

MIT — see [LICENSE](LICENSE).
