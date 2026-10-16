# Prediction engine — local OANDA demo

Four strategy agents trade **EURUSD and XAUUSD** through your local **OANDA MT5 demo account**, with a new Telegram bot for updates and controls. No frontend, VPS or paid AI API is required. The Python service runs on your Mac; a compiled MQL5 bridge runs in desktop MT5. Your phone can monitor the same demo account.

The agents are **trend, breakout, pullback and range reversion**. They share a risk coordinator and SQLite trade journal. Orders go directly to the broker's demo account after setup and `/resume`; there is no required simulated-wallet stage. There is no live-account execution path.

## First setup

From this folder, using Python 3.11 or later:

```sh
python3 -m prediction_engine init
python3 -m prediction_engine doctor
```

There are no Python runtime dependencies to install. `init` creates ignored `config.toml` and `.env` files with restrictive permissions and a random local bridge token. It preserves existing configuration.

1. **Log into OANDA demo in desktop MT5.** In `config.toml`, set `account_login` to that demo login and `account_server` to the exact displayed server (`OANDA_Global-Demo-1` for this account). Set `eurusd_symbol` and `xauusd_symbol` to the exact available Market Watch names; this account uses `EURUSD.sml` and `XAUUSD.sml`. The engine reads actual equity and currency from MT5; it does not assume USD. Never place your broker password in this project.
2. **Create your new bot** in Telegram using the verified [BotFather](https://t.me/BotFather), `/newbot`. Save its token locally in `.env` as `TELEGRAM_BOT_TOKEN`. Start a private conversation with your new bot and send `/start`.
3. **Set the Telegram recipient and authorized user.** Run `python3 -m prediction_engine telegram-setup` after saving the token. It reads only `/start` messages sent privately to your new bot, shows nonsecret candidate chat/user IDs, and lets you select your own chat. The IDs are saved to `.env`. Do not run another poller for this bot. No token should be pasted into chat, committed to Git, or put in a shell command.
4. **Install the MT5 bridge.** The built file is `mt5/PredictionBridge.ex5`. Rebuild with `./scripts/compile_mt5.sh` if needed. In MT5 use File → Open Data Folder and copy it into `MQL5/Experts/`; refresh Navigator. Allow `http://127.0.0.1:8787` under Options → Expert Advisors → allowed WebRequest URLs. Attach **one** PredictionBridge EA to **one** chart; it handles both symbols. Set `ExpectedLogin`, `ExpectedServer`, and `LocalToken` (the `BRIDGE_TOKEN` value from `.env`). Set `EURUSDSymbol` and `XAUUSDSymbol` to exactly match the Python configuration, including `.sml` when applicable. Leave `EnableOrders=false` for the initial connection check.
5. **Run the local service** in a terminal:

```sh
caffeinate -i python3 -m prediction_engine run
```

6. Check `/status` in Telegram, or `python3 -m prediction_engine status`. Verify the account, currency, synchronized bars and both instruments. Then set the EA's `EnableOrders=true`, enable MT5 Algo Trading, and send `/resume`. Eligible strategy signals will execute automatically on demo. There is no approval for individual trades.

Keep MT5 and the Python process running. `caffeinate -i` prevents idle system sleep while the command runs; closing the laptop lid or losing connectivity can still stop operation. Broker-held SL/TP remain on existing positions when the engine stops. Neither the phone app nor Telegram hosts the strategy process.

## Controls

| Command | Purpose |
|---|---|
| `/status` | Engine pause/readiness, account equity, connection and unresolved orders |
| `/agents` | Four strategies, versions and timeframes |
| `/positions` | Current broker positions and protective levels |
| `/stats` | Cumulative strategy deal P&L and closed-position counts |
| `/pause` | Stop new entries; keep existing broker SL/TP |
| `/resume` | Resume automatic demo entries when all account guards pass |
| `/help` | Command reminder |

The same names work as local CLI commands, e.g. `python3 -m prediction_engine pause`. Telegram commands are accepted only from the configured user in the configured private chat. Old `/resume` messages are discarded. Every process restart starts paused; it never silently resumes overnight.

## Initial limits and recovery

- Intended stop risk: **0.25% equity per entry**, **0.5% aggregate**, **2% UTC daily equity loss limit**; at most 20% total margin use. You can lower these in config. The EA independently enforces hard upper bounds.
- One position per instrument, maximum two positions total. Unknown/manual exposure and any pending orders block new entries. No martingale, averaging down or unprotected order fallback.
- Manual additions/reversals mixed into an agent position are flagged and excluded from agent statistics. They block new entries while open. Plain manual closes remain attributable.
- Every command is recorded before delivery. Lost responses, timeouts and unknown outcomes block further entries. Broker trade history reconciles actual fills. Expiry never causes automatic resubmission.
- If `/status` reports an unresolved command without a matching broker deal, keep the engine paused and inspect MT5 History and the SQLite command record. This v1 deliberately has **no automatic or remote “clear uncertainty” command**. Preserve both journals; have the recorded evidence reviewed before any explicit repair. Do not delete the database, pending EA acknowledgement or claim files to bypass the block.
- Telegram notifications use a durable outbox. Delivery can be duplicated if Telegram accepted a message but its response was lost; broker orders are never retried for that reason. Telegram outages do not automatically liquidate positions.

Strategies and metric definitions: [docs/STRATEGIES.md](docs/STRATEGIES.md). EA installation, recovery details and demo smoke-test checklist: [docs/MT5_BRIDGE.md](docs/MT5_BRIDGE.md).

## Verify the software

```sh
python3 -m unittest discover -s tests -v
./scripts/compile_mt5.sh
python3 -m prediction_engine doctor
```

Tests exercise real SQLite and a temporary loopback HTTP service with broker fixtures; they send no Telegram messages and no broker orders. MetaEditor compilation checks MQL5 syntax/API compatibility. Actual demo fills, stops, disconnections and Telegram delivery still require the configured terminal smoke test. These experimental rules have not been backtested or proven profitable. V1 has no economic-news filter, trailing/time exits, third-party Telegram group ingestion, or independent strategy wallets.
