import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import urllib.error
import urllib.request
from .config import load_config
from .engine import Engine
from .server import make_server
from .store import Store
from .telegram import TelegramWorker
from .setup import telegram_setup


def init():
    source=Path('config.example.toml')
    if not Path('config.toml').exists():
        Path('config.toml').write_text(source.read_text())
        os.chmod('config.toml',0o600)
    if not Path('.env').exists():
        with open('.env','x',opener=lambda path,flags:os.open(path,flags,0o600)) as file:
            file.write('BRIDGE_TOKEN='+secrets.token_urlsafe(48)+'\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\nTELEGRAM_USER_ID=\n')
    print('Local config.toml and .env ready. Existing values preserved; secrets were not printed.')


def control(config,command):
    req=urllib.request.Request(f'http://127.0.0.1:{config.port}/v1/control',data=json.dumps({'command':command}).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+config.bridge_token})
    try:
        with urllib.request.urlopen(req,timeout=5) as response: print(response.read().decode())
    except urllib.error.HTTPError:
        print('Command blocked or local authentication failed. Run status/doctor and check MT5 settings.',file=sys.stderr)
        return 1
    except OSError:
        print('Local service is unavailable. Start it with: python3 -m prediction_engine run',file=sys.stderr)
        return 1
    return 0


def doctor(config):
    checks=[('Python 3.11+',sys.version_info>=(3,11)),('Pinned demo login',config.account_login>0),
            ('Exact server configured',bool(config.account_server)),('Local bridge token',len(config.bridge_token)>=32),
            ('Telegram bot token set',bool(config.telegram_token)),('Private Telegram chat ID',config.telegram_chat_id.isdigit()),
            ('Telegram user allowlist',config.telegram_user_id.isdigit()),('Compiled MT5 bridge',Path('mt5/PredictionBridge.ex5').exists())]
    for label,ok in checks: print(('OK     ' if ok else 'NEEDED ')+label)
    print(f'Expected server: {config.account_server}; risk/trade {config.risk_fraction:.2%}; daily loss limit {config.daily_loss_fraction:.1%}')
    print('Exact broker symbols: '+', '.join(config.symbols))
    print('Checks verify local settings only. Broker connection and Telegram delivery still need a smoke test.')
    return 0 if all(ok for _,ok in checks) else 1


def run(config):
    os.umask(0o077)
    store=Store(config.database)
    engine=Engine(config,store)
    server=make_server(engine)
    worker=TelegramWorker(engine)
    store.enqueue('startup:'+secrets.token_hex(12),'DEMO engine started PAUSED. Use /status then /resume after the MT5 bridge is ready. Existing broker stops remain active.')
    thread=threading.Thread(target=worker.run,name='telegram',daemon=True)
    thread.start()
    print(f'Local demo service: http://127.0.0.1:{server.server_port}; starts PAUSED.',flush=True)
    print('Telegram '+('configured.' if worker.configured else 'not configured; complete .env before autonomous operation.'),flush=True)
    def shutdown(*_):
        engine.pause()
        worker.stop.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGINT,shutdown)
    signal.signal(signal.SIGTERM,shutdown)
    try: server.serve_forever(poll_interval=.5)
    finally:
        worker.stop.set()
        server.server_close()
        thread.join(timeout=25)
        store.close()
    return 0


def main():
    parser=argparse.ArgumentParser(description='Local OANDA MT5 demo strategy engine')
    parser.add_argument('--config',default='config.toml')
    parser.add_argument('command',choices=['init','doctor','telegram-setup','run','status','agents','positions','stats','pause','resume'])
    args=parser.parse_args()
    try:
        if args.command=='init': init();return 0
        config=load_config(args.config)
        if args.command=='telegram-setup': return telegram_setup(config)
        if args.command=='doctor': return doctor(config)
        if args.command=='run': return run(config)
        return control(config,args.command)
    except (ValueError,OSError) as exc:
        # Configuration errors contain field names only; external URLs are never emitted.
        print('Setup error: '+str(exc),file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
