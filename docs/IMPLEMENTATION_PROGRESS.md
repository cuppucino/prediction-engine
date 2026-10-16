# Implementation progress — 2026-10-16 local demo engine

Plan: docs/superpowers/plans/2026-10-16-local-demo-engine.md

Ruling: implement in existing unborn empty repository without worktree/commits — no commit exists to branch from; user explicitly requested this local repository — cost: changes remain uncommitted and visible for review.
Ruling: native MQL5 EA instead of Windows-only Python MetaTrader5 package — installed macOS MT5 includes Wine/MetaEditor — cost: EA must be compiled, attached, and allowed localhost WebRequest once.
Ruling: direct demo with 0.25% initial cash risk, 0.5% aggregate stop risk, 2% daily equity drawdown and one position per symbol — user has not specified risk; adjustable conservative demo defaults — cost: fewer trades and imperfect independent strategy comparison.
Ruling: deterministic agents, no LLM entry decisions or group ingestion in v1 — reproducibility and current build scope — cost: Telegram source interpretation remains future work.

Preflight interfaces: bridge → model follows v1 snapshot; coordinator → EA is 14-field OPEN; result → journal has immutable id and status; strategy → coordinator returns versioned signal with absolute SL/TP; journal → Telegram uses durable outbox. No shared-file ownership conflicts. Tasks agree with spec; compile-only MQL5 verification cannot establish broker execution behavior and will be reported separately.

Task 1 implemented: native bridge compiled with zero errors/warnings. Component reviewer passed spec/quality. Parent integration caught history loading short-circuit and unnecessary gold-tick dependency; implementer fixed both and recompiled successfully (2645 ms, X64 Regular). MQL runtime broker smoke remains unperformed.
Task 2 implemented: malformed/nonfinite OHLC and chronological validation; versioned four rules, long/short/flat cases. Initial missing-module failures observed, implementation made tests green.
Task 3 implemented: SQLite dispatch/reconciliation, day-loss latch, positions/risk, account pinning, restart pause and unknown outcome block. Tests observed failures before implementing gates. Explicit fresh-bar-age extension added to wire to avoid stale history behind fresh quotes.
Task 4 implemented: loopback auth/limits and Telegram private-chat/user allowlist, offset replay protection, durable notification retry, local CLI/secret initializer. Loopback test initially denied by sandbox; approved escalated offline test run passed all26 then-current tests, with no external requests.
Task 5 in progress: docs/config/new-bot setup, enhanced regression tests, whole-system fresh-context review. Local init executed; doctor confirms required remaining user settings are pinned demo login and new bot token/chat/user IDs. Bridge token generated without printing it. No broker account or Telegram bot connected yet.

Ruling: no automatic/remote clearing of uncertain orders in v1 — proving nonexecution from missing evidence is unsafe — cost: rare lost-response cases without broker deals require explicit evidence review and repair.
Ruling: no local news/calendar or Telegram group reader in initial executable — current request is four strategies plus outbound bot — cost: economic event avoidance is not automatic.

Whole-system review: two P2 findings reproduced with failing tests, then fixed: (1) quarantine mixed manual/netting lifecycles and exclude them from strategy P&L; (2) require at least one fresh, sufficiently populated market/timeframe for readiness/resume. Both Python and EA now detect contaminated position histories. Ordinary manual exits remain attributable. All37 offline tests pass, including new compiler-wrapper tests shipped in the repository. Final reviewer independently reran37/37 and tested real database reopening for quarantine persistence.

Final review follow-up complete: terminal lifecycle history validation finishes first, then current equity is refreshed and existing positions repriced without another history lookup before immediate identity/quote/expiry/floor checks. Independent reviewer final verdict: PASS. Final MetaEditor diagnostics independently read: 0 errors, 0 warnings, 3128 ms, X64 Regular; compiled bridge 68,550 bytes. Exact MQL source SHA256: `7c46332553b17d16034c50e20dde6474707b721b257fd3b4807c0f81b4568b2f`.

Final verification: reviewer independently ran all37 offline tests successfully; parent observed36/36 followed by the added compiler-wrapper test passing. A redundant final37-test rerun was interrupted, so it is not used as success evidence. Python compileall and shell syntax check passed. Both configuration files have0600 permissions and are Git-ignored. Source remains local and uncommitted in the initially empty repository. Broker and Telegram smoke tests remain pending local credentials/EA attachment; this is not a claim of running autonomous trading.
