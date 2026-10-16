import copy

NOW = 1792152000


def candles(n=240, start=1.1, step=0.0001, width=0.0003, period=900):
    result = []
    for i in range(n):
        close = start + i * step
        opening = close - step / 2
        result.append(dict(time=NOW - (n - i) * period, open=opening,
                           high=max(close,opening) + width, low=min(close,opening) - width, close=close))
    return result


def snapshot():
    symbols = {}
    for name, price, point in [('EURUSD', 1.124, .00001), ('XAUUSD', 2600., .01)]:
        symbols[name] = dict(bid=price, ask=price + point * 10, tick_age=1,
                             point=point, tick_size=point, digits=5 if name == 'EURUSD' else 2,
                             stops_level=10, trade_mode=4,bar_age={'M15':1,'H1':1,'H4':1},
                             bars={p: candles(start=price, step=0, width=point * 30,
                                              period=t) for p, t in [('M15',900),('H1',3600),('H4',14400)]})
    return dict(version=1, utc=NOW, connected=True, trade_allowed=True, history_complete=True,
                account=dict(login=123456, server='OANDA_Global-Demo-1', company='OANDA Global Markets',
                             currency='USD', demo=True, balance=10000, equity=10000, margin_free=10000),
                positions=[], orders=[], deals=[], symbols=symbols)


def duplicate(data):
    return copy.deepcopy(data)
