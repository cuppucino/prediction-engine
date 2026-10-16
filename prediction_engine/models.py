from dataclasses import dataclass
import hashlib
import math

SYMBOLS = ('EURUSD', 'XAUUSD')


class ValidationError(ValueError):
    pass


def number(value, name, minimum=None):
    if type(value) not in (int,float) or not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValidationError(f'Invalid {name}')
    return value


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValidationError(f'Invalid {name}')
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise ValidationError(f'Invalid {name}')
    return value


def text(value, name, limit=128):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 for c in value):
        raise ValidationError(f'Invalid {name}')
    return value


@dataclass(frozen=True)
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self):
        integer(self.time,'bar time',1)
        for field in ('open','high','low','close'):
            if number(getattr(self,field),field,0) == 0:
                raise ValidationError('Nonpositive candle')
        if not self.low <= min(self.open,self.close) <= max(self.open,self.close) <= self.high:
            raise ValidationError('Invalid candle range')


@dataclass(frozen=True)
class Signal:
    agent: str
    symbol: str
    bar_time: int
    side: str
    reference: float
    sl: float
    tp: float
    reason: str
    version: str = 'v1'

    @property
    def key(self):
        return hashlib.sha256(f'{self.agent}:{self.version}:{self.symbol}:{self.bar_time}'.encode()).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    utc: float
    connected: bool
    trade_allowed: bool
    history_complete: bool
    account: dict
    positions: tuple
    orders: tuple
    deals: tuple
    symbols: dict

    @classmethod
    def parse(cls, data, allowed_symbols=SYMBOLS):
        try:
            return cls._parse(data, allowed_symbols)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValidationError('Incomplete snapshot') from exc

    @classmethod
    def _parse(cls, data, allowed_symbols):
        if type(data.get('version')) is not int or data['version'] != 1:
            raise ValidationError('Unsupported protocol version')
        account = dict(data['account'])
        integer(account['login'],'login',1)
        boolean(account['demo'],'demo')
        for k in ('server','company','currency'):
            if not text(account[k],k):
                raise ValidationError(f'Missing {k}')
        for k in ('balance','equity','margin_free'):
            number(account[k],k)
        symbols = {}
        for symbol, raw in data['symbols'].items():
            if symbol not in allowed_symbols:
                raise ValidationError('Unexpected symbol')
            value = dict(raw)
            for field in ('bid','ask','point','tick_size'):
                number(value[field],field,0)
            if value['ask'] < value['bid'] or value['point']<=0 or value['tick_size']<=0:
                raise ValidationError('Invalid quote or tick size')
            number(value['tick_age'],'tick_age',-1)
            integer(value['digits'],'digits')
            integer(value['stops_level'],'stops_level')
            integer(value['trade_mode'],'trade_mode')
            value['bars'] = {}
            value['bar_age'] = dict(raw['bar_age'])
            for timeframe in ('M15','H1','H4'):
                number(value['bar_age'][timeframe],'bar_age',-1)
                rows = raw['bars'].get(timeframe,[])
                if not isinstance(rows,list) or len(rows)>500:
                    raise ValidationError('Invalid bar count')
                bars = tuple(Bar(**row) for row in rows)
                if any(a.time >= b.time for a,b in zip(bars,bars[1:])):
                    raise ValidationError('Bars must be strictly chronological')
                value['bars'][timeframe] = bars
            symbols[symbol] = value
        arrays = {}
        for key in ('positions','orders','deals'):
            rows = data[key]
            if not isinstance(rows,list) or len(rows) > (2000 if key=='deals' else 100):
                raise ValidationError(f'Invalid {key} count')
            arrays[key] = tuple(dict(row) for row in rows)
            for row in arrays[key]:
                integer(row['ticket'],'ticket',1)
                integer(row['magic'],'magic')
                text(row['symbol'],'symbol')
                if key == 'positions':
                    integer(row['identifier'],'identifier',1)
                    if row['side'] not in ('BUY','SELL'):
                        raise ValidationError('Invalid position side')
                    for name in ('volume','sl','tp'):
                        number(row[name],name,0)
                    number(row['profit'],'profit')
                    number(row['risk'],'risk',-1)
                if key == 'deals':
                    for name in ('order','position_id','entry','time'):
                        integer(row[name],name)
                    for name in ('volume','profit','commission','swap','fee'):
                        number(row[name],name)
        return cls(number(data['utc'],'utc',1), boolean(data['connected'],'connected'),
                   boolean(data['trade_allowed'],'trade_allowed'), boolean(data['history_complete'],'history_complete'),
                   account,arrays['positions'],arrays['orders'],arrays['deals'],symbols)
