# Releasing Tollgate

Everything below needs **no admin rights** on either OS.

## Checklist (v1.0)

- [x] Full test suite green (`uv run pytest -q` — 83 tests)
- [x] Lint clean (`uv run ruff check src tests`)
- [x] Dashboard built into `src/tollgate/static` (`make build-web`)
- [x] Frozen macOS app verified locally: healthz + dashboard + admin auth +
      bundled price map (ad-hoc signed)
- [x] Playwright UI smoke green (`tests/e2e` — see below)
- [x] Version single-sourced in `pyproject.toml` (spec + installer read it)
- [ ] **Real-key pass** (needs your keys): one Anthropic + one OpenAI +
      one local model round-trip through the gateway; check the Logs page shows
      tokens/cost/latency as expected
- [ ] **Two-machine sync pass**: Mac + Windows paired via the Sync page; make a
      request on each; both dashboards show merged totals; machine scope filter
      isolates them
- [ ] **Windows install pass**: installer runs without UAC; app launches;
      portable zip works (build via CI or `packaging/windows/build.ps1`)

## Cutting a release

1. Create the GitHub repo and add it as `origin` (first time only):
   ```bash
   gh repo create tollgate --private --source . --push
   ```
2. Bump `version` in `pyproject.toml` **and** `__version__` in
   `src/tollgate/__init__.py` (kept in lockstep), update CHANGELOG.md.
3. Tag and push:
   ```bash
   git tag v1.0.0 && git push origin v1.0.0
   ```
   The [release workflow](.github/workflows/release.yml) builds both platforms,
   smoke-tests the frozen app, and publishes: macOS zip, Windows per-user
   installer `.exe`, portable zips, and `latest.json` (consumed by the in-app
   update check once `update_manifest_url` points at it).
4. Install on Windows from the Release page; run the Windows install pass above.
5. Local (no CI) builds: `packaging/macos/build.sh` / `packaging/windows/build.ps1`.

## Playwright UI smoke (local)

```bash
uv run tollgate serve &                       # or a second instance on another port
cd tests/e2e
npm install && npx playwright install chromium
TOLLGATE_E2E_TOKEN=$(uv run tollgate key admin-token) npm run smoke
```

## Known deferred items (parking lot)

- App icon + code signing / notarization (ad-hoc only for now; SmartScreen
  warns on the unsigned Windows binaries — *More info → Run anyway*)
- Tray icon for the desktop shell
- `brew` / `winget` distribution
- Monthly billed-cost reconciliation via provider Admin APIs
- S3-compatible sync relay for machines never online together
