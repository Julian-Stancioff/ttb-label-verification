# TTB Alcohol Label Verification — Prototype

AI-assisted verification that an alcohol-beverage **label image** matches the data in its
**COLA application**, for the Alcohol and Tobacco Tax and Trade Bureau (TTB).

> Take-home prototype. Not connected to COLA; stores nothing sensitive.

## What it does

An agent uploads a label image (or a batch of them) plus the expected application fields.
The app extracts the label's text with a vision model and reports, in a few seconds, whether
each field matches:

- **Brand name** — match (case/punctuation-tolerant per agent judgment, e.g. `STONE'S THROW` == `Stone's Throw`)
- **Alcohol content (ABV)** — match
- **Government Health Warning** — present and **exact**: `GOVERNMENT WARNING:` in all-caps, word-for-word per 27 CFR 16.21
- Plus class/type, net contents, etc. where present

## Design targets (from stakeholder interviews)

| Requirement | Source |
| --- | --- |
| Result in **≤ 5 seconds** | Sarah Chen |
| **Dead-simple UI** ("my 73-yo mother could use it") | Sarah Chen |
| **Batch upload** (200–300 at once) | Sarah / Janet |
| Warning check **exact** (catch font/wording cheats) | Jenny Park |
| Apply **judgment** on trivial mismatches | Dave Morrison |
| Tolerate **imperfect photos** (angle, glare) | Jenny Park |
| Mind **firewall / no sensitive storage** | Marcus Williams |

## Status

🚧 Under construction — being built and tracked via [Gas Town](https://github.com/gastownhall/gastown)
multi-agent orchestration. Setup, run, and approach docs land as the build completes.

## Layout

```
backend/    FastAPI service: /verify, /verify/batch, vision extraction + matching
frontend/   Single-page, large-control UI for upload + results
docs/        APPROACH.md — approach, tools, assumptions, trade-offs
samples/     Example labels + application manifests for testing
```

## License

MIT — see [LICENSE](LICENSE).
