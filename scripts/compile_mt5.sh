#!/bin/bash
# Compile only: never starts terminal64.exe, attaches an EA, or sends orders.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
wine_bin="${MT5_WINE:-/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine}"
editor="${MT5_METAEDITOR:-/Users/admin/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/metaeditor64.exe}"
prefix="${MT5_WINEPREFIX:-/Users/admin/Library/Application Support/net.metaquotes.wine.metatrader5}"
if [[ ! -x "$wine_bin" ]]; then
  echo "Wine executable not found: $wine_bin" >&2
  exit 1
fi
if [[ ! -f "$editor" ]]; then
  echo "MetaEditor executable not found: $editor" >&2
  exit 1
fi
source_file="$root/mt5/PredictionBridge.mq5"
log_file="$root/build/mt5/compile.log"
mkdir -p "$root/build/mt5"
rm -f "$log_file" "$root/mt5/PredictionBridge.ex5"
# Wine's Z: drive maps the macOS filesystem. Avoid winepath (starts another process).
win_source="Z:${source_file//\//\\}"
win_log="Z:${log_file//\//\\}"
WINEPREFIX="$prefix" WINEDEBUG=-all MVK_CONFIG_LOG_LEVEL=0 "$wine_bin" "$editor" "/compile:$win_source" "/log:$win_log" || true
# MetaEditor's exit code alone does not indicate compilation success.
python3 - "$log_file" "$root/mt5/PredictionBridge.ex5" <<'PY'
import pathlib, re, sys
log, binary = map(pathlib.Path, sys.argv[1:])
if not log.is_file():
    sys.exit('Compilation produced no diagnostic log; success is unconfirmed.')
raw = log.read_bytes()
encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
text = raw.decode(encoding, errors='replace')
print(text)
if not re.search(r'\b0 errors, 0 warnings\b', text) or not binary.is_file():
    sys.exit('Compilation failed or produced warnings/missing output; inspect diagnostics above.')
print(f'Compiled: {binary}')
PY
