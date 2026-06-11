# Approach, Tools, and Assumptions

## The problem, as I read it

The interview notes carry the real requirements (more than the bullet list does). I treated the
following as the spec:

1. **Match the label to the application** — brand name, alcohol content, and the government
   warning, plus class/type and net contents where given.
2. **The warning check must be strict** (Jenny): exact statutory text, `GOVERNMENT WARNING:`
   header in all-caps. Catch the common cheats — paraphrasing, title-case headers, omissions.
3. **But apply judgment elsewhere** (Dave): `STONE'S THROW` vs `Stone's Throw` is the *same* brand.
   Don't fail people on trivial case/punctuation differences.
4. **Fast** (Sarah): results in ~5 seconds, or agents won't use it. The prior vendor died at 30–40s.
5. **Dead simple** (Sarah): "my 73-year-old mother could use it." Half the team is 50+.
6. **Batch** (Janet): importers dump 200–300 applications at once.
7. **Robust to imperfect photos** (Jenny): angle, glare, lighting.
8. **Mind the environment** (Marcus): outbound firewalls block many ML endpoints; PII matters;
   don't store anything sensitive for a prototype.

## Architecture & key decision: extract with AI, decide with code

A vision LLM reads the label and returns the printed fields as strict JSON. **All the
pass/fail logic is then plain, deterministic Python** — not a second LLM call. This split matters:

- **Speed & cost** — one model round-trip per label keeps us inside the 5s budget.
- **Auditability & consistency** — a compliance decision shouldn't be a coin-flip. The same
  extracted text always yields the same verdict, and the rules are readable in `verification.py`.
- **The strict checks are exactly the kind of thing code does better than an LLM** — comparing a
  transcription to statutory text word-for-word, and confirming an all-caps header.

The model is asked to **transcribe verbatim** (preserve case/punctuation) so the warning check can
be exact; the *judgment* (case-insensitive brand matching) lives in code where it's explicit.

### The government-warning check

Canonical text is 27 CFR 16.21. A warning **passes** only if: it is present; the header
`GOVERNMENT WARNING:` appears in all-caps (model flag **and** literal uppercase match, tolerant of
line wraps); and the body matches the statutory wording token-for-token. On failure the user gets a
specific reason ("header not all-caps", "wording differs near …risk of birth defects").

### Brand / ABV / text fields

Brand and free-text fields normalize case, whitespace, curly→straight apostrophes, and `&`↔`and`
before comparing — so `STONE'S THROW` matches `Stone's Throw`. ABV is parsed to a number from either
side, tolerating `45`, `45%`, `45% Alc./Vol.`. A field absent from the application is `not_checked`,
never a failure. Overall verdict is **PASS** iff the warning passes and every *provided* field matches.

## Tools used

| Tool | Why |
| --- | --- |
| **FastAPI + Uvicorn** (Python) | Small, fast async service; trivial multipart handling; serves the static UI too. |
| **OpenRouter** (`anthropic/claude-sonnet-4.5`) | One OpenAI-compatible endpoint, swappable model, strong vision/OCR for fine print. |
| **Vanilla HTML/CSS/JS** | No build step, no framework risk; loads on any office browser; easy to keep simple. |
| **httpx** | Async HTTP to the model; mockable in tests. |
| **pytest** (24 tests) | Cover the matching logic, the mocked client, and JSON parsing. |
| **Pillow** | *Dev-only* — generates synthetic test labels. Not an app runtime dependency. |
| **Caddy + systemd + nip.io** | Automatic HTTPS and a persistent service for the deployed prototype. |
| **Gas Town** | Multi-agent orchestration harness used to run the project (see below). |

### Model choice & the 5-second budget

Measured end-to-end latency with Sonnet 4.5 is **~4–5s** (occasionally ~6s on the first/complex
call). I tested **Claude Haiku 4.5** for speed: it was faster (~3s) but **misread the fine-print
warning on a valid label and falsely rejected it**. For a compliance tool a false rejection is worse
than a second of latency, so Sonnet is the default. The model is a one-line `.env` change
(`LLM_MODEL`) if priorities shift. Latency is dominated by the model call, not our code (matching is
sub-millisecond).

## Assumptions

- **Single primary label image per application.** Real submissions may have multiple panels; the
  prototype verifies one image at a time (batch = many independent labels).
- **The application data is the source of truth** for brand/ABV; the label is checked against it.
- **ABV requires numeric equality.** TTB allows tolerances (e.g. ±0.25–1.5% by class); I flag any
  difference and note it rather than bake in class-specific tolerances — a deliberate, documented
  simplification a reviewer can tighten.
- **English-language labels.**
- **Batch applications** are matched to images by a `filename` key, else by upload order.
- **No persistence / no auth** — appropriate for a throwaway prototype; explicitly *not* production.

## Trade-offs & limitations

- **Cloud model vs. Marcus's firewall.** The strongest accuracy on glare/angled photos comes from a
  hosted vision model, but Marcus warned their network blocks ML endpoints. For the prototype I
  chose accuracy (OpenRouter) and isolated the dependency behind one module (`openrouter.py`). A
  production path could swap in a self-hosted/on-prem vision model or a local OCR (e.g. Tesseract)
  fallback without touching the verification rules — the seam is already there.
- **Imperfect images** are handled by the vision model (it reports `legibility_notes`), not by
  pre-processing. Good enough for a prototype; production could add deskew/denoise.
- **No COLA integration** by design (Marcus: separate authorization beast).
- **Warning matching is strict by intent.** It could be loosened (e.g. accept minor punctuation)
  but Jenny's requirement is exactness, so the default errs strict and explains every rejection.
- **Cost ceiling on huge batches** — a 300-label batch is 300 model calls; concurrency is bounded
  (`BATCH_CONCURRENCY`) to stay responsive and rate-limit-friendly.

## How this was built (Gas Town)

Per the project brief, the work ran through [**Gas Town**](https://github.com/gastownhall/gastown),
a multi-agent orchestration system. Concretely:

- Built `gt` from source and stood up a Gas Town **HQ** ("town"), then added this repo as a **rig**
  with a **crew** workspace and a **beads** issue ledger.
- The build was decomposed into beads (backend core, extraction, verification, API, frontend,
  samples, deploy, docs) and tracked through `claim → in_progress → close`.
- An autonomous **polecat** agent (`obsidian`) was dispatched on the backend-core bead and produced
  the first `app/` skeleton + mocked-client tests, merged into history.
- The autonomous daemon proved unreliable in this self-built environment (it would queue work but
  not always spawn the agent session), so the remaining work ran in Gas Town's documented
  **minimal mode** — the orchestrator tracks state in beads while a runtime instance does the work —
  which kept delivery reliable without losing the beads-tracked workflow.

## Interface: built to the U.S. Web Design System (USWDS)

To make the prototype look like a real federal tool (and to be familiar to TTB staff), the UI follows
the [U.S. Web Design System](https://designsystem.digital.gov/) — the official standard behind
`.gov` sites including ttb.gov and treasury.gov. I screenshotted those live sites for reference and
matched: the **official-government banner**, an **agency-seal header** with the Treasury/TTB wordmark,
a **navy primary-navigation bar** for the tabs, USWDS **alert** components for PASS/FAIL, USWDS
**buttons**, and the **Public Sans** typeface and federal color tokens (`#162e51`, `#005ea2`, …).

## History (client-side, privacy-preserving)

A **History** tab lets an agent save any single or batch result under a custom name; each entry is
stamped with the save time and can be viewed or deleted. History lives in the **browser's
localStorage** — deliberately *not* on the server — so no application data or PII is ever persisted
server-side (Marcus's constraint). It's per-browser, which is the right scope for a prototype; a
production version would move this to an authenticated per-user store.

## Browser automation note (Playwright MCP)

The [Playwright MCP](https://github.com/microsoft/playwright-mcp) server is installed and registered
for browser automation. Playwright's bundled browsers don't install on this host's OS (Ubuntu 26.04),
so it's configured to drive the system Chromium via `--executable-path`. Interactive UI testing in
this repo was done by connecting Playwright to that Chromium over the DevTools Protocol (CDP).
