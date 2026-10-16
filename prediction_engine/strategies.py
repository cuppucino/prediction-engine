"""Versioned deterministic rules on chronological, completed candles."""
from statistics import fmean, pstdev
from .models import Signal

STRATEGIES = {'trend':'H4', 'breakout':'M15', 'pullback':'H1', 'range':'M15'}


def ema(values, period):
    seed = fmean(values[:period])
    result = [None] * (period - 1) + [seed]
    alpha = 2 / (period + 1)
    for value in values[period:]:
        seed += alpha * (value - seed)
        result.append(seed)
    return result


def atr(bars, period=14):
    return fmean(max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close))
                 for a,b in zip(bars[-period-1:-1],bars[-period:]))


def evaluate(agent, symbol, bars):
    if agent not in STRATEGIES:
        raise ValueError('Unknown strategy')
    if len(bars)<120:
        return None
    close = [bar.close for bar in bars]
    fast, slow = ema(close,20), ema(close,50)
    volatility = atr(bars)
    if volatility <= 0:
        return None
    side, stop_mult, target_mult, target = 0, 1.5, 3., None
    if agent == 'trend':
        stop_mult = 2.
        if fast[-2]<=slow[-2] and fast[-1]>slow[-1]: side=1
        elif fast[-2]>=slow[-2] and fast[-1]<slow[-1]: side=-1
    elif agent == 'breakout':
        if close[-1] > max(b.high for b in bars[-21:-1]) and close[-2] <= max(b.high for b in bars[-22:-2]): side=1
        elif close[-1] < min(b.low for b in bars[-21:-1]) and close[-2] >= min(b.low for b in bars[-22:-2]): side=-1
    elif agent == 'pullback':
        if fast[-2]>slow[-2] and fast[-1]>slow[-1] and close[-2]<=fast[-2] and close[-1]>fast[-1]: side=1
        elif fast[-2]<slow[-2] and fast[-1]<slow[-1] and close[-2]>=fast[-2] and close[-1]<fast[-1]: side=-1
    elif agent == 'range':
        # Freeze the band before both the excursion and the recovery candle.
        window = close[-22:-2]
        mean, std = fmean(window), pstdev(window)
        if std>0 and abs(fast[-1]-slow[-1]) < .5*volatility:
            if close[-2] < mean-2*std and mean-2*std <= close[-1] < mean: side=1
            elif close[-2] > mean+2*std and mean < close[-1] <= mean+2*std: side=-1
            target=mean
    if not side:
        return None
    reference=close[-1]
    sl=reference-side*stop_mult*volatility
    tp=target if target is not None else reference+side*target_mult*volatility
    if sl<=0 or tp<=0 or side*(tp-reference)<.8*abs(reference-sl):
        return None
    return Signal(agent,symbol,bars[-1].time,'BUY' if side==1 else 'SELL',reference,sl,tp,
                  f'{agent} {STRATEGIES[agent]} completed-bar rule')
