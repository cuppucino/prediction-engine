from dataclasses import dataclass, fields
import math
import os
import re
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Config:
    account_login: int = 0
    account_server: str = 'OANDA_Global-Demo-1'
    eurusd_symbol: str = 'EURUSD'
    xauusd_symbol: str = 'XAUUSD'
    port: int = 8787
    database: str = 'data/engine.sqlite3'
    risk_fraction: float = .0025
    aggregate_risk_fraction: float = .005
    daily_loss_fraction: float = .02
    max_margin_fraction: float = .20
    snapshot_max_age: float = 15
    tick_max_age: float = 10
    spread_stop_fraction: float = .08
    drift_stop_fraction: float = .10
    bridge_token: str = ''
    telegram_token: str = ''
    telegram_chat_id: str = ''
    telegram_user_id: str = ''

    def __post_init__(self):
        for name, ceiling in [('risk_fraction',.0025),('aggregate_risk_fraction',.005),
                              ('daily_loss_fraction',.02),('max_margin_fraction',.20),
                              ('spread_stop_fraction',.2),('drift_stop_fraction',.2),
                              ('snapshot_max_age',30),('tick_max_age',30)]:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 < value <= ceiling:
                raise ValueError(f'{name} must be > 0 and <= {ceiling}')
        if type(self.account_login) is not int or self.account_login < 0:
            raise ValueError('account_login must be a nonnegative integer')
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError('port must be in 1024..65535')
        if not isinstance(self.account_server,str) or not self.account_server or '\n' in self.account_server:
            raise ValueError('account_server must be an exact nonempty MT5 server name')
        for field, base in (('eurusd_symbol','EURUSD'),('xauusd_symbol','XAUUSD')):
            value = getattr(self, field)
            if not isinstance(value,str) or len(value)>31 or not re.fullmatch(base+r'(?:\.[A-Za-z0-9_-]+)?',value):
                raise ValueError(f'{field} must be {base} or its exact dot-suffixed broker symbol (at most 31 characters)')
        if self.aggregate_risk_fraction < self.risk_fraction:
            raise ValueError('aggregate risk must cover a single trade')

    @property
    def symbols(self):
        return (self.eurusd_symbol, self.xauusd_symbol)


def load_env(path='.env'):
    """Read literal KEY=value only, without shell interpolation or printing secrets."""
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not key.replace('_','').isalnum():
            raise ValueError('Invalid .env entry; use literal KEY=value')
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def load_config(path='config.toml'):
    load_env()
    data = tomllib.loads(Path(path).read_text()) if Path(path).exists() else {}
    allowed = {x.name for x in fields(Config)} - {'bridge_token','telegram_token','telegram_chat_id','telegram_user_id'}
    if set(data) - allowed:
        raise ValueError('Unknown configuration keys: ' + ', '.join(sorted(set(data)-allowed)))
    return Config(**data, bridge_token=os.environ.get('BRIDGE_TOKEN',''),
                  telegram_token=os.environ.get('TELEGRAM_BOT_TOKEN',''),
                  telegram_chat_id=os.environ.get('TELEGRAM_CHAT_ID',''),
                  telegram_user_id=os.environ.get('TELEGRAM_USER_ID',''))
