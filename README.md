# METATRON

One end-to-end seller-recruitment flow built with **CrewAI Flow**.
Sellers are loaded from a file. A **Data Crew** cleans the data and writes a JSON data contract that is
validated before training. A **Model Crew** trains and compares two lead-scoring models that rank the sellers.
An agent drafts the outreach message, **the broker approves every message** in Streamlit, the message is
sent on WhatsApp (or a simulator), the reply is handled (including **"הסר"**), and a meeting is booked.
No voice calls.

> Final project for the AI course. Planning docs (Hebrew, Obsidian vault): [`docs/00 - MOC.md`](docs/00%20-%20MOC.md)

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate                     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.lock && pip install -e . --no-deps
cp .env.example .env                       # optional: ANTHROPIC_API_KEY, WhatsApp keys

python -m metatron.data.generate           # synthetic training file -> data/raw/sellers.csv
python -m metatron.data.generate --out data/raw/new_sellers.csv --n-rows 60 --seed 7 --no-label
python -m metatron.train --config config.yaml
streamlit run app/streamlit_app.py
pytest
```

Without `ANTHROPIC_API_KEY`, everything runs in **offline mode**: the same deterministic tools run, and
templates write the prose. With the key, the CrewAI agents run the tools and write the insights,
model card and messages.

## The flow

```
TrainingFlow (offline)
  ingest_file ──► DataCrew ──► validate_contract ──┬─ failed ──► STOP + validation_report.json
                                                  └─ valid  ──► ModelCrew ──► model + MODEL_CARD.md

OutreachFlow (one event per run, per seller)
  draft ──► approval queue (Streamlit) ──► approve ──► send (WhatsApp / simulator)
  reply ──► handle_reply ──┬─ "הסר"         ──► confirm once, block the number forever
                           ├─ not interested ──► close, log_outcome(0)
                           ├─ question       ──► drafted answer ──► approval queue again
                           ├─ interested     ──► propose 3 slots
                           └─ slot chosen    ──► book meeting, log_outcome(1)
```

| Crew | Agents (≥3 each) | Artifacts |
|---|---|---|
| **Data Crew** | Data Cleaner · EDA Analyst · Insights Writer · Contract Author | `clean.parquet`, `cleaning_log.json`, `eda/`, `insights.md`, `data_contract.json` |
| **Model Crew** | Feature Engineer · Model Trainer · Evaluator · Model Card Writer | `features.parquet`, `models/v1`, `models/v2`, `metrics.json`, `MODEL_CARD.md` |

**Principle:** agents orchestrate, analyze and write. Cleaning, validation and training are fixed code
that the agents call as tools (`src/metatron/crews/tools.py`). The LLM never writes training code.

## Data contract gate

`data_contract.json` defines the schema, types, ranges, allowed values, a unique `seller_id`, minimum rows
and a target-rate range. The contract itself is validated with `jsonschema`, then every rule is checked
against the data. **Any failure stops the flow before training**, writes `validation_report.json` (what
failed and how to fix it) and shows it in red in Streamlit. Exit code `2`.

## Model: seller lead scoring

- **Target:** `agreed_to_meeting`, i.e. will the seller agree to a recruitment meeting within 14 days.
- **Data:** synthetic (`src/metatron/data/generate.py`). The generating function and the injected
  data-quality problems (duplicates, missing values, price typos, city spellings, numbers as text) are
  documented in the file. Every outreach logs a real outcome (`outcomes` table) for a future v3.
- **Versions:** v1 Logistic Regression (baseline) vs. v2 Gradient Boosting.
- **Metrics:** ROC-AUC, PR-AUC, **Precision@20%** (the broker contacts only the top 20%), Brier,
  5-fold CV, calibration. Selection by PR-AUC; ties go to the simpler model.

## Reproducibility

- One `config.yaml`, one `seed` used everywhere.
- Each run gets `runs/<run_id>/` with a copy of the input, its SHA-256, the full config and library
  versions (`run.json`).
- `requirements.lock` pins the environment.
- The same command on the same file gives the same metrics (`tests/test_training_flow.py`).

## WhatsApp

- `outreach.channel: simulation` (default) or `whatsapp` (Cloud API).
- In `whatsapp` mode, messages go **only** to `outreach.allowed_numbers`. During the course these are
  our own numbers, so no real sellers are contacted.
- The first message outside the 24-hour window uses the approved template (`seller_outreach`). Inside
  the window (the seller wrote first) the broker's approved text is sent as-is.
- Webhook: `uvicorn metatron.channels.webhook:app --port 8000`, exposed with `cloudflared tunnel`.
- Use a **separate number** from nadlan-pro's worker, otherwise replies go to the old webhook.

## The installed product (Windows)

The same OutreachFlow also runs as an installable app for a solo broker. The course demo stays in
Streamlit; the product has its own dashboard.

```
METATRON-Setup.exe            per-user install, no admin; asks for the broker's name and WhatsApp number
  python/                     private Python runtime with the product's packages
  gateway/ + node/            WhatsApp linked device (Baileys), listens on 127.0.0.1 only
  launcher                    starts the gateway, the local API and the outbox; tray icon; opens the browser
%LOCALAPPDATA%\METATRON\      settings.json · metatron.db · WhatsApp link · logs (kept on uninstall)
```

- **Setup wizard**: name → link WhatsApp (8-character code by phone number, or QR) → import the client
  list (Excel/CSV, Hebrew or English headers, mapping and problems shown before saving) → meeting hours.
- **Every first message is approved by the broker** (single or bulk, editable). The opt-out line is
  always added.
- **Outbox pacing**: a linked device is not the official WhatsApp API, so first messages go out only in
  working hours, with a random gap and a daily cap (default 15). Replies inside a conversation are sent
  at once after a short "typing" pause. A message still waiting is dropped if the seller opts out.
- **Privacy**: messages from numbers METATRON never contacted (family, other clients) are not stored.
  When the broker writes to a seller from the phone, METATRON stops auto-replying to that seller.
- **AI**: the app never holds an API key. With a license key it calls the relay (`relay/`, a Cloudflare
  Worker that holds the key and limits use per license); without one, messages come from the broker's
  template and everything else still works.

```bash
cd web && npm install && npm run build                 # dashboard -> src/metatron/product/web
cd gateway && npm install
python -m metatron.product.demo --home var/demo-home    # optional demo data
METATRON_HOME=var/demo-home python -m metatron.product.launcher
python installer/build.py                              # -> dist/METATRON-Setup-1.0.0.exe (Inno Setup 6)
```

## What existed before vs. what was built here

| Before the course (nadlan-pro) | Built in this repo |
|---|---|
| CRM app: properties, clients, calendar (`tasks`) | Everything in this repository |
| Firebase Auth + Firestore | CrewAI Flows, Data Crew, Model Crew |
| Worker with a WhatsApp agent for buyers | Synthetic data, contract, gate, models, Model Card |
| | Outreach writer, reply handling, "הסר", scheduling, Streamlit |

The only optional touch point: `calendar.backend: nadlan_pro` also writes the meeting to
`users/{uid}/tasks`, so it appears in the nadlan-pro calendar. nadlan-pro's code is not changed.

## Project layout

```
config.yaml                     single config
src/metatron/
  data/        generate · cleaning · eda · contract
  model/       features · train · evaluate
  crews/       data_crew · model_crew · tools
  flows/       training_flow · outreach_flow
  outreach/    store (SQLite) · scoring · drafting · replies · scheduling
  channels/    whatsapp · webhook · calendar
  product/     settings · contacts · outbox · gateway client · server (API) · launcher · demo
  pipeline.py  deterministic steps over runs/<run_id>/
  train.py     CLI
app/streamlit_app.py            5 screens: data · model · approval queue · conversations · calendar
web/                            product dashboard (React + Tailwind, Hebrew RTL)
gateway/                        WhatsApp linked-device gateway (Node, Baileys)
relay/                          Cloudflare Worker that holds the Claude API key
installer/                      build.py + Inno Setup script
tests/
docs/                           planning vault (Hebrew)
```
