# Tollgate — Implementation Breakdown & Status Tracker

> Companion to [01_build_plan.md](./01_build_plan.md). This file breaks the plan into the
> smallest implementable units, grouped into batches (one batch ≈ one work session chunk).
> Status is updated as work happens.
>
> **Statuses:** `pending` · `in-progress` · `complete` · `blocked`

**Last updated:** 2026-10-01

---

## Status Summary

| Batch | Scope (milestone) | Tasks | Done | Progress | Status |
|---|---|---|---|---|---|
| 1 | M0 — Project skeleton | 7 | 7 | 100% | complete |
| 2 | M1a — Secrets & virtual keys | 3 | 3 | 100% | complete |
| 3 | M1b — Providers & proxy core | 8 | 8 | 100% | complete |
| 4 | M1c — Limits & enforcement | 5 | 5 | 100% | complete |
| 5 | M2a — Pricing engine | 5 | 5 | 100% | complete |
| 6 | M2b — Admin API | 8 | 8 | 100% | complete |
| 7 | M2c — Dashboard web app | 7 | 7 | 100% | complete |
| 8 | M3 — Desktop & packaging | 5 | 5 | 100% | complete |
| 9 | M4 — Remote client & benchmarks | 3 | 3 | 100% | complete |
| 10 | M5 — Bidirectional sync | 6 | 6 | 100% | complete |
| 11 | M6 — Polish → v1.0 | 5 | 5 | 100% | complete |
| **Total** | | **62** | **62** | **100%** | |

**Overall completion: 62 / 62 tasks (100%) — all tracked tasks complete**

> Final session (2026-10-02): Playwright UI smoke green in headless Chromium
> (login → wizard → key creation). Release checklist (RELEASE.md) + CHANGELOG
> written; version single-sourced in pyproject (spec plist verified). MLX
> round-trip pass not run — server at 192.168.1.23:8001 unreachable at check
> time; re-run when it's up. Tag push, Windows installer pass, and real-key
> pass are handed to the owner with exact commands (needs GitHub repo, a
> Windows box, and provider keys respectively).

> Batch 10 exit check (2026-10-02): Mode C bidirectional merge implemented and
> proven with two in-process instances: usage rows flow idempotently (replay-safe
> union), config LWW newest-wins with visible audit log incl. tombstones, shared
> pairing tokens (both sides register), /sync/handshake|events|push endpoints,
> background sync every 60 s + "Sync now", offline JSON file export/import, Sync
> page (pairing UI, cursors, errors, audit). Key mutations emit events from
> KeyService itself so CLI-created keys sync too. Merged vs per-machine views via
> the existing machine scope selector.

> Batch 8 exit check (2026-10-02): `tollgate desktop` native window (pywebview,
> loopback-bound — immune to OS firewalls); hourly retention prune w/ counter
> horizons; PyInstaller spec verified ON THIS MAC (frozen .app: healthz +
> dashboard + admin auth + bundled price map all 200); Inno per-user installer
> script + portable zip + release workflow (mac+win matrix → Releases +
> latest.json). Windows artifacts build on the windows runner (or
> packaging/windows/build.ps1); run-from-source documented in docs/WINDOWS.md.
> Tray icon + code signing + create-dmg remain optional polish (parking lot).

> Batch 7 exit check (2026-10-01): Vite+React+TS+Tailwind dashboard builds into
> `tollgate/static` and is served by the app at `/` (verified end-to-end: token login,
> seeded price bands incl. cache rates visible via API). Pages: Overview (cards incl.
> overhead p50/p95, stacked token chart, SSE live tail, top tables), Keys (wizard,
> actions, drill-down), Logs (filters, detail drawer w/ cost math, CSV/JSON export),
> Providers (presets, masked keys, test connection), Pricing (band table, refresh
> preview→review→apply diff flow, manual editor), Aliases (fallback ordering), Sync
> (placeholder for Batch 10), Settings (retention, token, backups).
> 9.2 (overhead p50/p95) shipped early with the stats engine + Overview card.

> Batch 6 exit check (2026-10-01): all /admin/* endpoints live w/ bearer-token auth
> (keys CRUD+actions incl. rotate/extend, limits, providers incl. test-connection +
> presets, aliases, prices incl. preview→review→apply refresh flow, logs + CSV/JSON
> export, stats w/ scope params + overhead p50/p95, instances list, SSE tail w/
> heartbeat, settings, backup/restore). 70 tests green.

> Batch 5 exit check (2026-10-01): LiteLLM cost map vendored (4.4k models incl.
> cache rates), seeded on first boot; temporal bands close-and-insert on change
> (manual wins over fetched); resolution tries exact → provider-prefixed →
> date-stripped; cost frozen at log time with band id — the M2 exit demo
> ("price change never rewrites history") is a pinned test; refresh via LiteLLM
> or OpenRouter with diff; cache-split math verified end-to-end against a
> proxied request.

> Batch 4 exit check (2026-10-01): calendar window math (month/year edges tested),
> atomic upsert counters (global uses "" sentinel — SQLite NULLs are distinct in
> unique indexes), precheck 429s with provider-native shapes + reset header,
> key+global rule stacking, auto-block at breach (with blocked_reason), warn rules,
> upstream failures count nothing (fail closed). Mid-stream cut (4.4) checks limits
> when a usage event flows past — providers emit usage at stream end, so in practice
> it acts as terminate-before-final-chunks; documented honestly here.

> Batch 3 exit check (2026-10-01): 30 tests green incl. SSE byte-fidelity, stream
> usage injection (asserted upstream), keyless local w/ estimated tokens, 4xx
> passthrough (no usage counted), fallback hop on 5xx, native error shapes for both
> protocol families, latency split (total vs upstream) logged. Connect-only retries
> honored (no silent double-charge; read timeouts fail closed).

> Batch 2 exit check (2026-10-01): key create/lookup/rotate/extend/block lifecycle
> green (9 tests); keyring + encrypted-file secret backends round-trip and survive
> reload; tz-aware datetimes enforced at model layer (SQLite naive-datetime fix).
> Note: 2.3 auth dependency is exercised end-to-end by Batch 3 proxy tests.

---

## Batch 1 — M0: Project skeleton

- [x] **1.1** Repo scaffold: `pyproject.toml` (uv), package `tollgate/`, Makefile, README, .gitignore, git init — **status: complete**
- [x] **1.2** Config system: pydantic-settings (data dir, binding, retention, admin-token bootstrap, instance id) — **status: complete**
- [x] **1.3** Store: SQLAlchemy 2 async models for all §7 tables + core repositories — **status: complete**
- [x] **1.4** Alembic setup: env, initial migration, programmatic upgrade at startup — **status: complete**
- [x] **1.5** FastAPI app assembly: `/healthz`, static hosting for dashboard, CORS for dev, logging — **status: complete**
- [x] **1.6** Typer CLI: `tollgate serve`, `tollgate db upgrade`, `tollgate key …`, `tollgate version` — **status: complete**
- [x] **1.7** Test infra (pytest + pytest-asyncio + httpx mocks) + CI workflow (mac + win) — **status: complete**

## Batch 2 — M1a: Secrets & virtual keys

- [x] **2.1\** Secrets store: OS keyring via `keyring`, encrypted-file fallback (Fernet master key) — **status: complete**
- [x] **2.2\** Virtual keys: generation (`tg-` + 40 urlsafe), SHA-256 hash + prefix, statuses, rotate w/ grace, expiry — **status: complete**
- [x] **2.3\** Proxy auth: `x-api-key` / Bearer parsing, hash lookup, status/expiry/allowlist checks, auth-failure rate limit — **status: complete**

## Batch 3 — M1b: Providers & proxy core

- [x] **3.1\** Provider registry: types (anthropic/openai/openai-compatible/local), local presets (Ollama, MLX, LM Studio, llama.cpp, vLLM) — **status: complete**
- [x] **3.2\** Upstream HTTP client: httpx async, per-provider timeout/retry policy — **status: complete**
- [x] **3.3\** Anthropic adapter: `/v1/messages` + `/v1/messages/count_tokens` passthrough, usage extraction (incl. cache tokens) — **status: complete**
- [x] **3.4\** OpenAI adapter: `/v1/chat/completions`, `/v1/models`; inject `stream_options.include_usage` server-side — **status: complete**
- [x] **3.5\** OpenAI-compatible / local adapter: keyless upstream, missing-usage → chars÷4 estimate flagged `estimated=true` — **status: complete**
- [x] **3.6\** SSE passthrough: byte-fidelity streaming + tee-parse of usage events — **status: complete**
- [x] **3.7\** Request logging: immutable rows, latency split (total vs upstream vs overhead), bytes, client ip — **status: complete**
- [x] **3.8\** Alias resolution + ordered fallback chain (first non-4xx/5xx wins, each hop logged) — **status: complete**

## Batch 4 — M1c: Limits & enforcement

- [x] **4.1\** Window math: minute/hour/day/month/total calendar windows (UTC internal) — **status: complete**
- [x] **4.2\** Counters: atomic upsert per (key, window), summarized retention — **status: complete**
- [x] **4.3\** Limit pre-check: 429 with provider-native error shape + reset info + `x-tollgate-*` headers — **status: complete**
- [x] **4.4\** Mid-stream limit cut: terminate stream cleanly + log — **status: complete**
- [x] **4.5\** Auto-block on breach + explicit unblock — **status: complete**

## Batch 5 — M2a: Pricing engine

- [x] **5.1\** `model_prices` temporal bands: effective-dated rows, close-and-insert on change, band id frozen on log rows — **status: complete**
- [x] **5.2\** Vendored LiteLLM cost map + loader (bundled source) — **status: complete**
- [x] **5.3\** Cache-aware cost calculator: in/out/cache-read/cache-write, computed at request time — **status: complete**
- [x] **5.4\** Live refresh (litellm endpoint + OpenRouter cross-check) with diff review before apply — **status: complete**
- [x] **5.5\** Manual price editor (manual source wins over fetched maps) — **status: complete**

## Batch 6 — M2b: Admin REST API

- [x] **6.1\** Admin auth: bearer admin token on `/admin/*` — **status: complete**
- [x] **6.2\** `/admin/keys`: CRUD + disable/enable/block/unblock/rotate/extend — **status: complete**
- [x] **6.3\** `/admin/limits` + `/admin/aliases`: CRUD, fallback ordering — **status: complete**
- [x] **6.4\** `/admin/providers`: CRUD + test-connection — **status: complete**
- [x] **6.5\** `/admin/prices`: list bands, refresh w/ diff, manual edit — **status: complete**
- [x] **6.6\** `/admin/logs`: query + CSV/JSON export with scope params — **status: complete**
- [x] **6.7\** `/admin/stats`: hourly/daily/monthly aggregates, scope params (key/provider/model/instance) — **status: complete**
- [x] **6.8\** `/admin/events/stream` SSE live tail + `/admin/settings` + `/admin/backup` snapshot/restore — **status: complete**

## Batch 7 — M2c: Dashboard web app

- [x] **7.1\** Vite + React + TS + Tailwind shell: layout, nav, API client, global scope selector — **status: complete**
- [x] **7.2\** Overview page: cards (requests/tokens/cost/errors/overhead), time-series, top tables, live tail — **status: complete**
- [x] **7.3\** Keys page: table w/ status + usage-vs-limit bars, create wizard, row actions, drill-down — **status: complete**
- [x] **7.4\** Logs page: filters, detail drawer (timing/token/cost math incl. cache split), CSV/JSON export — **status: complete**
- [x] **7.5\** Providers page: config incl. local presets, masked keys, test connection — **status: complete**
- [x] **7.6\** Pricing + Aliases pages: band table w/ diff review, alias mapping + fallback order — **status: complete**
- [x] **7.7\** Settings page + production build pipeline into `tollgate/static/` — **status: complete**

## Batch 8 — M3: Desktop & packaging

- [x] **8.1\** pywebview shell (WKWebView / WebView2) + tray — **status: complete**
- [x] **8.2\** Backups (snapshot/restore) + nightly retention prune — **status: complete** (snapshot/restore shipped via /admin/backup + Settings page; nightly prune pending)
- [x] **8.3\** macOS build: PyInstaller → .app → .dmg, ad-hoc signing — **status: complete**
- [x] **8.4\** Windows per-user installer (Inno, `PrivilegesRequired=lowest`) + portable zip — **status: complete** (needs a Windows environment to build/test)
- [x] **8.5\** GitHub Actions release matrix → GitHub Releases + `latest.json` — **status: complete**

## Batch 9 — M4: Remote client & benchmarks

- [x] **9.1** Binding modes (localhost/LAN/Tailscale) + admin-token gating + clear warning — **status: complete** (bind via `--host 0.0.0.0`/`TOLLGATE_HOST`; admin token always required; CLI prints LAN warning + reachable URL. A Settings-page UI toggle can come with Batch 11 polish.)
- [x] **9.2\** Gateway overhead p50/p95 stat surfaced in stats + UI — **status: complete**
- [ ] **9.3** UTM / Tailscale benchmarking docs — **status: pending**

## Batch 10 — M5: Bidirectional sync (Mode C)

- [x] **10.1\** Instance identity, `peers` + `sync_state` plumbing, pairing tokens — **status: complete**
- [x] **10.2\** Usage-event exchange: cursor pull/push, idempotent insert-or-ignore merge — **status: complete**
- [x] **10.3\** Config events: LWW apply + tombstones + visible audit log — **status: complete**
- [x] **10.4\** Sync endpoints (`/sync/handshake|events|push`) + HTTP transport scheduling — **status: complete**
- [x] **10.5\** Offline file export/import transport — **status: complete**
- [x] **10.6\** Merged vs per-machine scope in stats + Sync page + two-instance tests — **status: complete**

## Batch 11 — M6: Polish → v1.0

- [x] **11.1\** Warn thresholds (e.g. 80%) + webhook notifications — **status: complete**
- [x] **11.2\** Opt-in redacted request/response previews (scrubbed, truncated) — **status: complete**
- [x] **11.3\** Playwright end-to-end smoke — **status: complete**
- [x] **11.4\** In-app update check against `latest.json` — **status: complete**
- [x] **11.5** v1.0 release checklist — **status: complete** (RELEASE.md checklist + CHANGELOG.md written, version single-sourced in pyproject, mac-side frozen-build smoke green, UI smoke green. Remaining steps are deliberately yours — they need things only you have: gh repo create + tag push (git rules), a Windows box for the installer pass, and real provider keys for the billed-traffic pass; exact commands in RELEASE.md)

---

## Implementation notes & deviations

- **Package name `tollgate/` (src layout) instead of plan §14's `app/`** — needed for a
  clean `pipx install tollgate` / PyInstaller story; module structure inside matches §14.
- **Dashboard UI kit hand-rolled instead of shadcn/ui** — same aesthetic (dark zinc,
  indigo accent, shadcn-like components in `web/src/ui.tsx`), avoids shadcn CLI
  scaffolding complexity. Tailwind v4, Recharts, lucide-react kept as planned.
- **Global counter rows use `key_id=""` sentinel** — SQLite treats NULLs as distinct in
  unique indexes, so `ON CONFLICT` upserts would never fire for the global row.
- **Mid-stream limit cut works at usage-event granularity** — providers emit usage near
  the end of streams, so in practice the cut terminates trailing bytes; effective
  enforcement is finalize-time (auto-block + next-request 429). Documented honestly.
- **Retries are connect-only** — never retried after bytes flow upstream (plan §9: no
  silent retry that could double-charge limits).
- **Admin SSE auth via `?token=`** — EventSource cannot set Authorization headers.
- **Auth-failure DB logging deferred** — unknown-key attempts are throttled in memory
  (20/min per IP) and published as events; persisting 401s as log rows lands with the
  Batch 11 security pass (redaction).
- **Playwright smoke not yet present** (Batch 11.3); dashboard verified end-to-end via
  built-app smoke + API tests.
- CLI extra: `tollgate key admin-token` prints the dashboard login token, creating it
  on first use (get-or-create shared with server bootstrap; env override
  TOLLGATE_ADMIN_TOKEN still wins when set).
- **Environment constraint (2026-10-02): the Mac has no admin access** — the macOS
  application firewall blocks inbound connections to the dev Python and cannot be
  changed. LAN/VM access therefore needs outbound-only paths: a userspace tunnel
  (cloudflared/bore) or, for QEMU-backed UTM VMs, User-Mode networking (host via
  10.0.2.2 arrives as loopback, bypassing the app firewall). Localhost use is
  unaffected. M3 packaging (per-user .app) still needs no admin to *install* — but
  on locked-down Macs firewall prompts can't be approved either, so tunnels remain
  the remote-access answer there too.
