# Local demo engine implementation plan

Spec: ../specs/2026-10-16-local-demo-engine.md

Architecture: dependency-free Python coordinator plus MQL5 EA, shared SQLite journal, Telegram bot. Implement in current new repository; user explicitly authorized building here. No deployment, no live trades.

## Global constraints

Demo-only identity verified twice. No credentials in source/logs. No simulation as mandatory prerequisite. Fail closed on unknown broker outcome, malformed/stale market data and conflicting exposure. Only EURUSD/XAUUSD. Code/test before credentials. Keep decisions and evidence in `docs/IMPLEMENTATION_PROGRESS.md`.

## Task 1: MQL5 bridge

Files: `mt5/PredictionBridge.mq5`, `scripts/compile_mt5.sh`, `docs/MT5_BRIDGE.md`. Implement exact v1 wire contract from spec. Read primary MQL5 API docs, compile source with available MetaEditor and inspect diagnostics. MQL5 cannot be executed by Python tests; compiler plus explicit demo smoke-test runbook needed. No external account/file mutation beyond compilation without parent coordination. Own only these files. No subagents. Report compiler result and safety limitations.

## Task 2: Python domain and strategies

Files: `prediction_engine/models.py`, `strategies.py`, `config.py`, tests. Write failing behavior tests then implement. Validate snapshots, finite OHLC, freshness, immutable signals with identity. Four rules from spec. Config environment and TOML, no deps. Verify `python3 -m unittest discover -s tests -v`.

## Task 3: Journal and execution coordinator

Files: `store.py`, `engine.py`, tests. SQLite transactional command dispatch, unique signals, risk gates, day baseline/latch, result reconciliation, closed-position attribution via entry position_id, durable outbox. Test failures first: repeated same snapshot, late result, unknown command, broker deal evidence, mismatched demo, restart paused, concurrent signals. Use RLock plus SQLite transactions; single process owns DB lock.

## Task 4: Local service and Telegram

Files: `server.py`, `telegram.py`, `__main__.py`, tests. Authenticated loopback HTTP, strict limits/types, configurable startup, local CLI doctor/status/resume/pause, Telegram polling/outbox and allowlist. Test against localhost fixture HTTP and fake external Telegram transport. No accidental outgoing messages in tests.

## Task 5: Packaging and integration

Files: `README.md`, `config.example.toml`, `.env.example`, `.gitignore`, `pyproject.toml`, `docs/STRATEGIES.md`, setup scripts if useful. Local secret initializer, doctor redacted output, workflow from new bot to pinned MT5 demo to autonomous operation. Run complete offline suite, compile EA, fresh-context review and fix material findings. Capture limits (no broker smoke until login/configured, no news calendar/Telegram source reader). Leave runnable artifacts, not placeholders.

## Review focus

1. Lost HTTP acknowledgement and process kill during order dispatch: can they duplicate exposure?
2. MQL5 price, tick size, cash-risk and volume arithmetic across EURUSD and XAUUSD.
3. Historical deals whose exit magic/comment differs from entry, partial exits and fees.
4. EA compilation/runtime features in bundled macOS Wine and stale clock handling.
5. Switching between demo/live accounts, controller restart and Telegram replay/auth boundaries.
