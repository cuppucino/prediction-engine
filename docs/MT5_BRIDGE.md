# MT5 demo bridge

`mt5/PredictionBridge.mq5` is one EA for both **EURUSD** and **XAUUSD**, with orders disabled by default. It has no live-account execution path and never reads a broker password. It uses the existing macOS MT5 installation through bundled Wine.

## Build

From the repository root:

```sh
./scripts/compile_mt5.sh
```

The script invokes **MetaEditor only**, requires a fresh `.ex5` plus a compiler log with **0 errors, 0 warnings**, and leaves diagnostics in `build/mt5/compile.log`. Output is `mt5/PredictionBridge.ex5`. Wine may require permission to access its existing prefix. The script does not start the trading terminal or install/attach the EA. `MT5_WINE`, `MT5_METAEDITOR`, and `MT5_WINEPREFIX` can override installation paths.

## Configure and attach manually

1. Log into the authorized **OANDA demo account** in MT5. Verify the displayed login, exact server, company, currency, balance and equity. This account's verified server is `OANDA_Global-Demo-1`; the coordinator and EA must both match it exactly. Do not infer currency from the reported 10,000 balance.
2. Use **File → Open Data Folder**, then copy the built `.ex5` into `MQL5/Experts/`. Refresh Navigator. Installation is a separate manual action from compilation.
3. In **Tools → Options → Expert Advisors**, allow WebRequest for `http://127.0.0.1:8787` (or the exact chosen local port). Keep the service bound to loopback. The EA accepts only an explicit IPv4 loopback URL with a numeric port and no path/query/userinfo.
4. Attach to **one chart only**. Set `ExpectedLogin` to the verified account login, `ExpectedServer` to the exact pinned server, `CoordinatorURL` to the local service URL, and `LocalToken` to the same 32+ character bearer token as the coordinator. Set `EURUSDSymbol` / `XAUUSDSymbol` to the exact Market Watch names, matching `eurusd_symbol` / `xauusd_symbol` in `config.toml`. This account uses `EURUSD.sml` / `XAUUSD.sml`; open charts for these names rather than the unavailable unsuffixed variants. Leave `EnableOrders=false` while checking setup. Both exact symbols must exist.
5. Start the Python service. It starts paused. Confirm that account, history and all three timeframes for both instruments synchronize. The EA transmits 240 completed bars from `start_pos=1`, in chronological order. Missing history uses empty arrays. `bar_age` gives M15/H1/H4 seconds since the last completed candle's close, measured with the broker clock; unavailable/future values use `-1`. Bar/deal timestamps are broker clock identities; `utc`/command expiry use `TimeGMT()`.
6. After reviewing readiness, set `EnableOrders=true`, enable MT5 algorithmic trading, and resume through the authenticated coordinator control. This is a setup switch, not a confirmation for each trade. All identity, account and quote guards are checked again for each order.

The EA does not log the token or raw HTTP headers/body. MT5 may save EA inputs or presets to disk; protect local terminal/configuration files and avoid sharing presets containing `LocalToken`.

The engine and bridge accept EURUSD/XAUUSD, optionally followed by a dot and an explicit alphanumeric, underscore or hyphen suffix, up to 31 characters total. There is no fuzzy symbol discovery or suffix stripping: snapshots, commands, exposure and deal history retain the exact broker symbol. Python pins the configured pair in its journal after an accepted account snapshot and refuses a subsequent change; existing legacy commands also prevent a silent switch to other symbols. Preserve the journal and review any intended symbol migration rather than deleting this guard.

## Wire and execution

The authoritative wire contract is [the implementation specification](superpowers/specs/2026-10-16-local-demo-engine.md). Requests are authenticated JSON `POST /v1/snapshot` and `POST /v1/result`. Snapshot responses are exactly `WAIT` or the 14-field `OPEN` command; result acknowledgements must be exactly `OK`.

Execution requires `ACCOUNT_TRADE_MODE_DEMO`, exact login/server, company containing OANDA, connected terminal and all terminal/account/EA trading permissions. The EA checks strict command syntax, finite positive numeric fields, 24 lowercase hexadecimal id, per-command magic range, UTC expiry within 15 seconds, monotonic response age, fresh broker ticks, spread and drift from the submitted tick. Stops must already align with tick size and meet direction/distance requirements. Market, SL and TP order flags must all be supported. Symbols that delete stops at the broker's day boundary are refused.

The terminal applies fixed upper bounds: **0.25% of current equity per command, 0.5% aggregate open stop risk, two positions maximum, one per symbol, and at most 20% projected total margin**. The coordinator may impose lower limits. Existing positions require a bridge magic claim and a valid stop-risk calculation; all pending orders and foreign/unknown exposure block entry. Before each send, the EA also inspects each existing position's complete lifecycle with `HistorySelectByPosition`: an opening entry must match its claimed magic, any entry with another magic or any `ENTRY_INOUT` reversal blocks execution. Missing lifecycle history or failed property reads also block. Ordinary `ENTRY_OUT`/`ENTRY_OUT_BY` exits may have another magic. This detects manual additions/reversals that retain a netting position identifier; the coordinator persistently quarantines those mixed lifecycles from strategy attribution. Fresh quotes are required for the selected order symbol and every existing position. An unrelated instrument's stale quote (for example, gold during its daily closure) does not block a new EURUSD command when there is no gold position. The cash calculation uses `OrderCalcProfit` in the verified account currency at the adverse allowed entry price; volume is floored to the broker step and rejected below minimum. `OrderCheck` checks the complete request and projected total margin. Both stops are attached to the sole market request. FOK is preferred; IOC is accepted; RETURN is refused because it can leave an unfilled remainder.

`OrderSend` is called **once**. A confirmed deal with DONE/DONE_PARTIAL is reported filled. Known definitive broker refusals are rejected. Timeout, connection failures, PLACED or unfamiliar outcomes are uncertain. No retry, naked-order fallback, stop modification, averaging or close command exists.

The final lifecycle history selection finishes before the EA refreshes equity and reprices every existing position. That final cash-risk pass performs no further history selection; identity, fresh order quote, expiry and equity-floor checks follow immediately before `OrderSend`.

## Replay and restart state

State lives in the terminal's sandboxed `MQL5/Files/PredictionBridge/` directory, not the repository:

- `executor.lock` is held exclusively for the EA lifetime. A terminal-global CAS mutex adds a second executor guard. A second chart instance fails initialization. On an input/account/chart change, the EA releases its file handle and clears local ownership. Reinitialization reuses an existing temporary variable; only after obtaining the exclusive file can it recover an orphaned mutex flag. Pending acknowledgements and durable order claims are never cleared by this recovery. Terminal restart releases the exclusive handle and temporary mutex.
- `id_<id>.claim` and `magic_<magic>.claim` are flushed before sending, together with a flushed terminal-global command claim. Disk claims remain after terminal global variables expire. Keep these files permanently for this deployment.
- `pending.json` is flushed **as uncertain before the broker call**. The final result replaces it using a temporary file and move. A crash during sending therefore leaves an uncertain acknowledgement. The pending result is retried before any snapshot or next command, including across restarts. It is removed only after HTTP 200 and exact `OK`.

A write/flush/move failure halts new execution. A previously durable pending result still retries. An unreadable pending file prevents initialization. Filesystem persistence uses MQL5's flush/move APIs; it cannot promise recovery from physical disk corruption or storage rollback. Back up the coordinator journal and terminal state together. Do not delete claims or pending state to make an unresolved command disappear: inspect broker deals and use the coordinator's explicit review process. An uncertain acknowledgement remains blocked in Python until broker evidence or operator review resolves it; expiry alone never clears it.

## Demo smoke-test runbook

Compilation establishes language/API compatibility, not broker execution correctness. Perform these on the pinned demo account after manual installation:

1. With `EnableOrders=false`, confirm authenticated snapshots reach the paused coordinator and show the actual account currency, exact identity, both symbols, completed bars, `bar_age`, trade deals, orders and positions. Confirm no orders appear.
2. Attach a second bridge to a second chart; verify it refuses initialization because the executor lock is held. Remove the second instance.
3. Verify wrong token and account/server mismatch block entry; restore the matching local settings. Confirm stale/disconnected data blocks eligibility for affected symbols and readiness returns only after synchronization. On newly selected symbols/timeframes, verify missing bars eventually populate: `CopyRates`/`CopyTime` run before synchronization checks so they initiate history download/building, returning empty arrays/`-1` until ready. During gold's daily closure, fresh EURUSD can remain eligible when no gold position exists; an open gold position with unavailable stop-risk pricing must block all entries. Never switch to a live account for this test.
4. Enable orders and resume when ready to authorize autonomous demo execution. Inspect any strategy-triggered order's broker-held SL/TP, volume, cash risk, magic and single execution. Inspect both EURUSD and XAUUSD before relying on instrument-specific price/volume behavior.
5. During a known pending result, temporarily stop the local coordinator and restart the EA. Restore the service and verify the saved acknowledgement retries, the broker order is not resent, and broker deals reconcile the command. For a crash during `OrderSend`, expect uncertain until broker evidence arrives. Use a controlled demo test window; do not create fake coordinator commands against a broker session.
6. Confirm exits and partial fills attribute through position identifiers in coordinator history. A bridge pause/disconnection must stop new entries while existing broker-held SL/TP remain visible.

`WebRequest` is unavailable inside MT5 Strategy Tester, so this runbook requires the real demo terminal. No broker smoke test is implied by offline fixtures or a successful compile. Market/exchange execution may ignore the request's `deviation`: drift checks and adverse-price sizing constrain the **submitted** request, but broker fills and stop fills can exceed intended slippage/risk. The EA reports the broker result without retrying or attempting an unprotected repair order.

## Primary API references

- [WebRequest, headers, permissions and Strategy Tester limitation](https://www.mql5.com/en/docs/network/webrequest)
- [OrderSend and the distinction between accepted and filled](https://www.mql5.com/en/docs/trading/ordersend)
- [OrderCheck](https://www.mql5.com/en/docs/trading/ordercheck)
- [Symbol order flags, filling policies and execution modes](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants)
- [Atomic terminal-global compare-and-set](https://www.mql5.com/en/docs/globals/globalvariablesetoncondition)
- [Sandboxed FileOpen](https://www.mql5.com/en/docs/files/fileopen), [FileFlush](https://www.mql5.com/en/docs/files/fileflush)
- [TimeTradeServer broker-clock estimate](https://www.mql5.com/en/docs/dateandtime/timetradeserver)
- [CopyRates history initiation and partial results](https://www.mql5.com/en/docs/series/copyrates), [CopyTime](https://www.mql5.com/en/docs/series/copytime)

- [HistorySelectByPosition lifecycle selection](https://www.mql5.com/en/docs/trading/historyselectbyposition), [deal entry and position identity properties](https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties)
