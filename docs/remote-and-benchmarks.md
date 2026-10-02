# Remote access & benchmarking

How to reach one Tollgate instance from another machine — and how to benchmark
through it without the gateway skewing your numbers.

## Bind first

Everything below assumes the gateway runs with `tollgate serve --host 0.0.0.0`
(default port 8787). Localhost-only (`127.0.0.1`) is the safe default and is
never touched by OS firewalls on mac or Windows.

## LAN (trusted networks)

Other machines use the gateway machine's IP, e.g. `http://192.168.1.7:8787`:

- Dashboard: browse there, log in with the admin token.
- Projects: `OPENAI_BASE_URL=http://192.168.1.7:8787/v1` (+ `tg-…` key), or
  `ANTHROPIC_BASE_URL=http://192.168.1.7:8787` for Anthropic-style clients.

**macOS firewall caveat:** the application firewall must *allow* the running
Python/Tollgate binary. On a no-admin Mac this can't be changed — use a tunnel
(below) instead.

## UTM Windows VM → Mac host

Depends on the VM's Network mode (UTM → VM → Settings → Network), check with
`ipconfig` inside Windows:

| ipconfig shows | Mode | Host address |
|---|---|---|
| `192.168.1.x` | Bridged | `http://192.168.1.7:8787` (Mac's LAN IP) |
| `192.168.64.x` | Shared (vmnet) | `http://192.168.64.1:8787` |
| `10.0.2.x` | QEMU User Mode | `http://10.0.2.2:8787` |

The **QEMU User Mode** row is special: slirp proxies host connections via the
Mac's loopback, so it **bypasses the macOS application firewall entirely** —
the one networking path that works on a locked-down, no-admin Mac without any
tunnel.

Whichever mode the *Mac* runs in, it must listen on the **configured port**
(8787) — peers dial that fixed address. `tollgate serve` does this naturally,
and the desktop window also binds it, falling back to a random port (with a
warning) only when another Tollgate instance already holds 8787. The machine
that is never dialed (Windows, in this topology) can run on any port.

## Locked-down Mac (no admin): outbound tunnels

The macOS app firewall blocks inbound connections to the dev Python and can't
be changed without admin. Outbound is unrestricted, so:

```bash
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:8787
# → https://random-words.trycloudflare.com  (use as base URL anywhere)
```

or raw-TCP `bore` (`brew install bore-cli && bore local 8787 --to bore.pub`).
URLs are unguessable and everything stays token-gated, but treat them as
temporary: they change on restart, and traffic transits a third party.

## Tailscale (off-LAN, encrypted)

Install Tailscale on both machines (needs admin/MDM approval on locked-down
Macs), then use the Mac's 100.x.y.z address exactly like a LAN IP. Encrypted
WireGuard end-to-end.

## Benchmarking through the gateway

The local gateway hop adds real, small latency (~1–5 ms non-streaming and
stream TTFB; no measurable effect on streaming throughput). Tollgate measures
it for you: every request logs `latency_total_ms` vs `upstream_ms`, and the
Overview page shows **overhead p50/p95** — subtract it, or verify it's noise.

Rules of thumb:

- **Run the benchmarking client on the machine hosting the gateway** — a
  VM→host hop (UTM shared networking) adds its own sub-ms noise.
- Logs carry `instance_id`, so multi-machine runs can be isolated in the
  dashboard's machine scope selector.
- Escape hatch for provider-exact TTFB: hit the provider directly with the
  real key for that run (it leaves a gap in Tollgate's logs — by design).
