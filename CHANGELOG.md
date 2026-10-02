# Changelog

## 0.1.2 (2026-10-02)

- Fix: release workflow's latest.json step crashed on a missing datetime
  import (builds and the frozen-app smoke were green; only the manifest
  step failed).

## 0.1.1 (2026-10-02)

- Fix: the vendored LiteLLM price map was never committed (unanchored `data/`
  gitignore pattern also matched `src/tollgate/pricing/data/`) — CI and the
  packaged app had no prices. Ignore patterns anchored to the repo root.

## 0.1.0 (2026-10-02)

Initial implementation of the full plan (M0–M6). Highlights:

- **Gateway**: Anthropic (`/v1/messages`), OpenAI + any OpenAI-compatible
  (`/v1/chat/completions`, `/v1/models`), and local servers (Ollama/MLX/LM
  Studio/llama.cpp/vLLM presets) with byte-faithful SSE passthrough and
  provider-native error shapes.
- **Virtual keys**: `tg-…` hashed at rest, rotate with grace window,
  disable/block/unblock/extend, provider/model allowlists.
- **Limits**: {requests, tokens, cost} × {minute…total} × {key, global},
  fail-closed precheck with 429 + reset info, auto-block, warn events and
  optional webhooks.
- **Metering & pricing**: cache-aware cost from the vendored LiteLLM map
  (4.4k models), temporal price bands (old logs keep their old cost),
  refresh with diff review, manual overrides, chars÷4 estimation for keyless
  local servers, gateway overhead p50/p95.
- **Dashboard**: React (dark, Logfire-style) — Overview with live SSE tail,
  Keys wizard, Logs with cost math + CSV/JSON export, Providers with
  test-connection, Pricing with band history, Aliases with fallback ordering,
  Settings; global scope selector (key/provider/model/machine).
- **Sync (Mode C)**: peer pairing with shared tokens, idempotent usage merge,
  config last-writer-wins with visible audit + tombstones, 60 s background
  exchange, offline file export/import.
- **Desktop & packaging**: pywebview shell (`tollgate desktop`), per-user
  PyInstaller builds, macOS `.app` (ad-hoc signed), Windows Inno installer
  (`PrivilegesRequired=lowest`) + portable zip, release workflow with
  `latest.json`.
- **Ops**: retention prune, backups/restore, redacted opt-in body previews,
  update check, keyring-backed secrets with encrypted-file fallback.
