# Tollgate

A **local-first LLM gateway** for one person with too many machines. It fronts your
provider API keys (Anthropic, OpenAI, any OpenAI-compatible endpoint, and offline
LLM servers like Ollama / MLX / LM Studio / llama.cpp / vLLM), issues its own
**virtual keys**, meters every request — tokens, estimated cost with cache-aware
pricing, latency — enforces limits you set, and shows it all in a Logfire-style
dashboard. Mac and Windows each run their own instance, and **bidirectional merge
sync** keeps both dashboards showing combined stats.

```
your project ──tg-… virtual key──▶ Tollgate ──real key──▶ Anthropic / OpenAI / local
                                      │
                                      ├─ every request logged: tokens, cost, latency
                                      ├─ limits: {requests, tokens, USD} × {hour, day, …}
                                      └─ dashboard + sync between machines
```

Your projects never see a real provider key. Local models get the same metering,
limits, and latency stats as cloud ones.

## Install

All paths are **per-user — no administrator rights anywhere**, on either OS.

| How | What |
|---|---|
| **Installer** (once Releases exist) | Windows: `tollgate-setup-<ver>.exe` → `%LOCALAPPDATA%\Programs\Tollgate`, no UAC prompt. See [docs/WINDOWS.md](docs/WINDOWS.md). |
| **Portable zip** | Unzip anywhere, run `Tollgate`. Same page as above. |
| **From source** (works today) | Below. |

```bash
git clone <this-repo> tollgate && cd tollgate
uv sync                      # or: uv sync --extra desktop  (adds the native window)
uv run tollgate desktop      # native window (WKWebView / WebView2)
# …or headless + browser:
uv run tollgate serve        # gateway + dashboard at http://127.0.0.1:8787
```

Requires Python 3.12+ (the python.org Windows installer has a per-user mode).
Data lives in `~/Library/Application Support/Tollgate` (mac) / `%LOCALAPPDATA%\Tollgate`
(win): one SQLite file plus encrypted secrets (OS keychain when available,
Fernet-encrypted-file fallback).

## First five minutes

```bash
uv run tollgate serve                              # terminal 1, keep it running
uv run tollgate key admin-token                    # dashboard login token
uv run tollgate key create --name my-project       # a virtual key (shown ONCE)
```

1. Open `http://127.0.0.1:8787`, log in with the admin token.
2. **Providers** → add your real upstreams (cloud presets, or a local one like
   `http://localhost:11434/v1` for Ollama). API keys go into the OS keychain —
   they never appear in the DB or the UI again.
3. **Keys** → create a virtual key, optionally with limits.
4. Point a project at the gateway:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="tg-…")
```

```python
import anthropic
client = anthropic.Anthropic(base_url="http://127.0.0.1:8787", api_key="tg-…")
```

Claude Code / env-var tools: `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`,
`ANTHROPIC_API_KEY=tg-…` (or the `OPENAI_*` pair).

5. Make a request, then watch the **Overview** live tail and the **Logs** page.

## Features

- **Proxy, both wire formats** — Anthropic-native `/v1/messages` (+ count_tokens),
  OpenAI `/v1/chat/completions`, `/v1/models`. Byte-faithful SSE streaming
  passthrough; errors come back in each provider's native shape so SDKs parse
  them; every response carries `x-tollgate-*` headers (key, provider, resolved
  alias).
- **Virtual keys** — `tg-` + 40 random chars, SHA-256-hashed at rest, shown once
  at creation. Disable / block / unblock / extend / rotate (old key keeps a
  1-hour grace window). Per-key allowlists for providers and models/aliases.
- **Limits** — `{requests, tokens_in, tokens_out, tokens_total, cost_usd}` ×
  `{minute, hour, day, month, total}` × per-key or global. Fail-closed precheck
  returns a native-shaped 429 with the window-reset time; optional auto-block on
  breach; warn events at 80 % (dashboard + optional webhook).
- **Metering & cache-aware pricing** — provider-reported usage preferred
  (Anthropic cache tokens, OpenAI `cached_tokens` — injected server-side for
  streams via `stream_options.include_usage`); keyless local servers without
  usage get a flagged chars÷4 estimate. Costs come from the **vendored LiteLLM
  community price map** (4.4k models incl. cache-read/write rates), stored as
  **effective-dated price bands**: when a price changes, old logs keep their old
  cost — frozen at log time with the band id on the row. Live refresh (LiteLLM or
  OpenRouter) with a diff you review before applying; manual entries always win.
- **Aliases & fallback** — map `model-a` → (provider, upstream model) with an
  ordered fallback chain tried on connect/5xx failures; each hop is logged.
  Swap a benchmark suite between Claude and a local model without touching it.
- **Dashboard** (React, dark) — Overview with cards / stacked token charts /
  live SSE tail; Keys with wizard and usage drill-down; Logs with filters, the
  exact token-and-cost math per request, CSV/JSON export; Providers with
  test-connection; Pricing with band history and refresh diffs; Aliases; Sync;
  Settings. A **global scope selector** filters everything by key, provider,
  model, or machine.
- **Benchmarks made honest** — every request logs `upstream_ms` separately from
  total, and the Overview surfaces the gateway's own **overhead p50/p95** so you
  can subtract the hop (typically ~1–5 ms).
- **Multi-machine sync (Mode C)** — each machine keeps its own SQLite (fast,
  offline-safe). Usage rows merge as an idempotent union — conflicts are
  impossible by construction; config changes sync last-writer-wins with a
  **visible audit log** (who-changed-what-when, tombstones included). Exchange
  runs every minute over HTTP with shared pairing tokens, plus offline
  JSON-file export/import. Dashboards default to merged stats; filter to one
  machine in the scope selector.
- **Privacy-first logging** — request/response bodies are **never** stored unless
  you opt in; when on, previews are truncated and scrubbed of secret patterns.

## Remote access & VMs

The gateway binds `127.0.0.1` by default — loopback is never touched by OS
firewalls. For LAN / VM / off-LAN access (including the UTM Windows setup, the
no-admin Mac tunnel workaround, and benchmarking rules of thumb) see
[docs/remote-and-benchmarks.md](docs/remote-and-benchmarks.md) and
[docs/WINDOWS.md](docs/WINDOWS.md).

## CLI

```
tollgate serve [--host H] [--port P]   # gateway + dashboard (foreground)
tollgate desktop                       # native window app
tollgate key create|list|admin-token   # virtual-key management
tollgate db upgrade                    # apply migrations
tollgate version
```

Everything the CLI does is also in the dashboard (`/admin/*` REST API, bearer
admin token — see the OpenAPI docs at `/docs` when the server runs).

## Configuration

Environment variables (prefix `TOLLGATE_`), or `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `TOLLGATE_DATA_DIR` | platform data dir | DB + secrets + backups |
| `TOLLGATE_HOST` / `TOLLGATE_PORT` | `127.0.0.1` / `8787` | binding (see remote docs before changing) |
| `TOLLGATE_ADMIN_TOKEN` | generated once | fixed admin token override |
| `TOLLGATE_SECRETS_BACKEND` | `auto` | `auto` / `keyring` / `file` |
| `TOLLGATE_RETENTION_DAYS` | `90` | request-log retention |
| `TOLLGATE_LOG_BODIES` | `false` | opt-in redacted previews |
| `TOLLGATE_UPDATE_MANIFEST_URL` | *(empty)* | enables the in-app update check |
| `TOLLGATE_DATABASE_URL` | derived | override (tests) |

Retention, body previews, and the warn webhook URL can also be changed at runtime
in **Settings** (stored in the DB, wins over env).

## Project layout

```
src/tollgate/
├─ main.py            # FastAPI assembly, lifespan, admin-token bootstrap
├─ cli.py             # typer CLI
├─ proxy/             # /v1/* pipeline, adapters (anthropic/openai/local), routing
├─ auth/              # virtual keys: hashing, lookup, rotation, auth dependency
├─ limits/            # window math, atomic counters, enforcement, auto-block
├─ metering/          # usage extraction, finalize (log row + events + counters)
├─ pricing/           # temporal bands, vendored LiteLLM map, refresh/diff
├─ admin/             # /admin/* REST + SSE live tail + stats aggregation
├─ sync/              # peers, events pull/push, LWW merge, file transport
├─ security/          # keyring/file secrets, redaction
├─ store/             # SQLAlchemy models, Alembic migrations, retention
└─ desktop/           # pywebview shell
web/                  # React dashboard (Vite → builds into src/tollgate/static)
tests/                # 83 pytest tests + Playwright smoke (tests/e2e)
packaging/            # PyInstaller spec, Inno Setup script, build scripts
docs/                 # Windows install, remote access & benchmarking
plans/                # design plan + per-task implementation tracker
```

## Development

```bash
uv sync --extra desktop --dev
make test          # pytest (83 tests; upstreams fully mocked, no network)
make lint          # ruff check + format check
make build-web     # build the dashboard into src/tollgate/static
make dev           # run the dev server

# UI end-to-end smoke (real browser):
cd tests/e2e && npm install && npx playwright install chromium
TOLLGATE_E2E_TOKEN=$(uv run tollgate key admin-token) npm run smoke
```

Python 3.12+, uv, Node 18+ for the dashboard. Tests spin up isolated app
instances against temp SQLite files; the proxy suite pins byte-fidelity of SSE
passthrough, usage injection, fallback hops, limit math, price-band immutability
("old logs keep the old cost"), and two-instance sync (idempotency, LWW,
tombstones).

## Releases

Per-user packaging for both OSes via GitHub Actions: macOS `.app` (ad-hoc
signed) + zip, Windows Inno installer (`PrivilegesRequired=lowest`) + portable
zip, plus `latest.json` for the update check. Checklist and owner steps:
[RELEASE.md](RELEASE.md) · history: [CHANGELOG.md](CHANGELOG.md).

## Status

All 62 tracked tasks complete (M0–M6 of the plan). Design decisions, per-task
status, and honest deviation notes: [plans/01_build_plan.md](plans/01_build_plan.md)
· [plans/02_implementation_breakdown.md](plans/02_implementation_breakdown.md).
Parking lot (explicitly later): billed-cost reconciliation via provider Admin
APIs, S3 sync relay, semantic caching, `brew`/`winget`, tray icon, code signing.

---

*Costs are estimates labeled as such; provider bills remain the source of truth.*
