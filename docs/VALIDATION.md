# Local implementation validation — 2026-10-16

Scope: four deterministic strategy agents for EURUSD/XAUUSD; local Python service, MQL5 OANDA demo bridge, SQLite journal, outbound Telegram bot and controls. This document distinguishes implemented behavior from account integration that has not run.

## Verified locally

- Python 3.13.9 on this Mac; no third-party runtime packages required.
- **52 offline tests passed**, including actual SQLite transactions/reconciliation, an authenticated temporary localhost HTTP server, complete fixture signal→dispatch→acknowledgement→broker-history→exit/P&L flow, all four strategies at forex/gold price scales in both directions, stale/malformed inputs, demo identity, duplicate/concurrent dispatch, daily loss latch, mixed manual/netting quarantine, Telegram allowlist/replays/retries, private setup-file updates, compiler-wrapper failure behavior, verified macOS TLS handling, and exact broker suffix configuration. Six symbol regressions failed before the suffix fix and passed afterward, covering EURUSD.sml/XAUUSD.sml dispatch, fee-inclusive attribution, rejection of other variants, foreign positions, and journal symbol pinning.
- Tests sent **no external Telegram requests and no broker orders**. Compiler-wrapper tests use a stub compiler in a temporary folder, not the real terminal.
- Five lifecycle tests execute the EA's actual `OnInit`/`OnDeinit` bodies in a C++ harness with a deterministic terminal API fake. Three restart/orphaned-lock cases failed before the v1.02 fix; all five pass afterward, including duplicate-chart rejection and cleanup after failed initialization. This harness verifies bridge decisions, not actual Wine/MQL5 API behavior. The Mac harness uses the selected Xcode compiler's SDK via `xcrun` to avoid this host's mismatched default CLT SDK.
- Real MetaEditor compilation through installed macOS MT5/Wine succeeded with **zero errors and zero warnings**, 3119 ms, X64 Regular. The generated v1.02 bridge is `mt5/PredictionBridge.ex5` (71,452 bytes); actual diagnostics are in ignored `build/mt5/compile.log`. Source SHA256: `f00b7faac20ae6c2d8f0ea422414b3ea1f2afa59285f80add17345a036c33a04`. The installed Experts binary matches the compiled output.
- Independent code review found mixed-netting attribution and false-readiness issues. Both have regression tests and fixes. The review also prompted a terminal guard refresh after potentially blocking history synchronization. Final source-review verdict: **PASS**; the reviewer independently ran all37 offline tests successfully. A redundant final parent rerun was interrupted and is not counted as success evidence.
- Local initialization created ignored `.env` and `config.toml` with restrictive permissions; generated bridge secret was not printed. Git ignores local credentials, database and compiled artifacts.

## Still requires your local account setup

The demo login, Telegram token, private recipient and authorized user are configured. The user received Telegram startup/status messages. An accepted OANDA snapshot confirmed `OANDA_Global-Demo-1`, USD 10,000 equity, zero positions/unresolved commands, and fresh EURUSD.sml/XAUUSD.sml quotes with 240 bars for each M15/H1/H4 series. The subsequent `EnableOrders` change caused the v1.01 bridge to fail initialization with `Executor mutex unavailable`, confirmed in terminal logs. The v1.02 fix is now installed; reattachment and a successful input-change restart in the real terminal remain to be verified. Actual demo fills, broker SL/TP placement and broker restart/disconnection execution behavior remain unverified.

Follow the [setup guide](../README.md) and [demo smoke-test runbook](MT5_BRIDGE.md). The engine starts paused on every launch and will only resume with a pinned, eligible OANDA demo snapshot. No strategy backtest or evidence of profitability is implied by these software checks.

## Deliberate v1 limits

One position per symbol, shared account balance, fixed broker stops/targets, no news filter, no trailing/time exit, no third-party group ingestion. Unproven order outcomes require broker evidence or explicit manual review; there is no remote bypass. Full account history is bounded to 2000 trade deals, after which the bridge blocks new entries pending a pagination enhancement. Account cash adjustments not linked to position deals are visible in equity but cannot be attributed to individual agents.
