# OANDA demo cloud handover

Target: your Google Cloud project, VM `forex-demo-vm`,
zone `asia-southeast1-b`, Ubuntu 24.04 LTS. Chrome Remote Desktop hosts Xfce;
MetaTrader 5 runs under Wine in the VM user's `~/.mt5` prefix.

The Mac and VM use the same OANDA demo account and private Telegram bot.
Only one engine may run during handover. The database lock protects one
machine only; it cannot prevent two machines from trading or polling Telegram.

## Transfer contents

The private transfer archive contains the Python engine, configuration and
Telegram/bridge secrets, a consistent SQLite journal backup, bridge v1.02,
the MT5 demo input preset with `EnableOrders=false`, and durable EA command
claim files. It does not contain the broker password or the full Wine profile.
Keep the archive private and upload it only to the intended VM over its SSH
connection. It is stored under ignored `build/cloud/` on the Mac.

Before packaging, pause the Mac engine, verify zero unresolved commands,
stop it gracefully, and acquire its database lock. Do not copy an actively
written SQLite database file directly. Preserve the journal's account/symbol
pins, daily risk baseline, signal deduplication and Telegram polling offset.
Preserve all bridge command claims; omit only the transient executor lock.
An outstanding EA `pending.json` requires reconciliation before packaging.

## Restore on the VM

1. Upload `forex-demo-transfer-20261016.tar.gz` using the browser SSH window.
2. Extract into the VM user's home directory. The archive has a single root
   directory, `prediction-engine`. Stop if that destination already contains
   an engine; do not overwrite another journal or configuration.
3. From `~/prediction-engine`, run `python3 -m prediction_engine doctor`.
4. Verify the hashes listed in `cloud/manifest.json`. The archive was built
   with owner-only file/directory permissions. Preserve those permissions.
5. Keep the Mac engine stopped throughout the cloud setup and afterward.

## Connect the VM's MT5 terminal

Use the existing OANDA demo login and exact server `OANDA_Global-Demo-1`.
In Symbols, show `EURUSD.sml` and `XAUUSD.sml` and open their charts.
The unsuffixed default EURUSD chart is not the intended instrument.

Confirm MT5's File > Open Data Folder before installing the bridge. With the
official Linux installer, the expected folder is
`~/.mt5/drive_c/Program Files/MetaTrader 5`.

Copy `mt5/PredictionBridge.ex5` to `MQL5/Experts/`,
`cloud/PredictionBridge-Demo.set` to `MQL5/Presets/`, and the contents of
`cloud/bridge-state/` to `MQL5/Files/PredictionBridge/` in that data folder.
Do not overwrite existing bridge state on the VM; investigate it first.

Allow `http://127.0.0.1:8787` in MT5's Expert Advisors WebRequest settings.
Attach exactly one PredictionBridge EA to one chart and load the preset.
It covers both instruments. The bridge port stays bound to loopback and
does not need a Google Cloud firewall rule.

Start the Python engine only after confirming the Mac copy is stopped.
It starts paused. Verify `/status`, `/stats`, account identity, both symbols,
fresh history and zero unresolved commands. Enable the EA's `EnableOrders`,
its algorithmic trading permission and the terminal's Algo Trading switch.
Then use `/resume` after checking readiness.

## Finish deployment

### Progress confirmed on 16 October 2026

- Transfer archive SHA-256 verified on the VM; all `doctor` checks passed.
- The user reports the Python user service is active and enabled.
- Telegram reports the cloud bridge is ready, engine paused, both `.sml`
  instruments with fresh ticks and 240 M15/H1/H4 bars, zero positions and
  zero unresolved commands.
- The migrated journal's closed-position count and net deal P&L match the
  pre-transfer records. Account balances and trade results are kept private.
- The Mac Python engine was paused and stopped before the archive was built.
- After an initial post-reboot wait for the bridge, the user reported that
  the engine resumed successfully. A subsequent Telegram status confirmed
  RUNNING, fresh quotes and zero unresolved commands. Backups and billing
  alerts remain to be configured.

The first successful connection is not the whole deployment. Configure the
Python service and MT5 desktop autostart, verify behavior after disconnecting
the remote desktop and rebooting the VM, and configure private backups and
Google Cloud budget alerts. Every engine restart deliberately starts paused;
Telegram `/resume` is required again. A billing alert is not a spending cap.

Before any rollback, pause and stop the cloud engine. If cloud trading has
occurred, export its newest database and bridge claim files before restarting
the Mac. Never restart the Mac from the old transfer snapshot.

Reference: [MetaQuotes Linux installation](https://www.metatrader5.com/en/terminal/help/start_advanced/install_linux).
