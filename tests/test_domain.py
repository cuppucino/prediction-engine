import unittest
from prediction_engine.models import Snapshot, ValidationError, Bar
from prediction_engine.config import Config
from prediction_engine.strategies import evaluate, STRATEGIES
from tests.fixtures import snapshot, candles, NOW


class SnapshotTests(unittest.TestCase):
    def test_rejects_nonfinite_prices_and_invalid_candle(self):
        for invalid in [float('nan'), float('inf'), -1]:
            data = snapshot()
            data['symbols']['EURUSD']['bid'] = invalid
            with self.assertRaises(ValidationError):
                Snapshot.parse(data)
        data = snapshot()
        data['symbols']['EURUSD']['bars']['M15'][-1]['high'] = .1
        with self.assertRaises(ValidationError):
            Snapshot.parse(data)

    def test_rejects_unsorted_bars_and_boolean_account_login(self):
        data = snapshot()
        data['symbols']['EURUSD']['bars']['M15'].reverse()
        with self.assertRaises(ValidationError):
            Snapshot.parse(data)
        data = snapshot()
        data['account']['login'] = True
        with self.assertRaises(ValidationError):
            Snapshot.parse(data)

    def test_preserves_demo_false_for_execution_gate(self):
        data = snapshot()
        data['account']['demo'] = False
        self.assertFalse(Snapshot.parse(data).account['demo'])

    def test_risk_config_cannot_disable_limits_with_nan(self):
        with self.assertRaises(ValueError):
            Config(risk_fraction=float('nan'))


class StrategyTests(unittest.TestCase):
    def bars(self, data):
        return tuple(Bar(**x) for x in data)

    def test_four_agents_ignore_flat_or_insufficient_data(self):
        self.assertEqual(len(STRATEGIES), 4)
        for agent in STRATEGIES:
            self.assertIsNone(evaluate(agent, 'EURUSD', self.bars(candles(step=0))))
            self.assertIsNone(evaluate(agent, 'EURUSD', self.bars(candles(n=10))))

    def test_breakout_uses_prior_range_and_protects_both_directions(self):
        for direction in [1, -1]:
            data = candles(step=0)
            last = data[-1]
            last.update(close=1.1 + direction*.002, high=1.103, low=1.097)
            signal = evaluate('breakout', 'EURUSD', self.bars(data))
            self.assertIsNotNone(signal)
            self.assertEqual(signal.side, 'BUY' if direction == 1 else 'SELL')
            self.assertGreater(direction * (signal.reference - signal.sl), 0)
            self.assertGreater(direction * (signal.tp - signal.reference), 0)
            self.assertEqual(signal.bar_time, NOW-900)
            self.assertEqual(signal.key, evaluate('breakout','EURUSD',self.bars(data)).key)

    def test_breakout_does_not_reenter_an_already_broken_range(self):
        data = candles(step=.001, width=.0001)
        self.assertIsNone(evaluate('breakout', 'EURUSD', self.bars(data)))

    def test_trend_cross_is_event_not_perpetual_above_ma(self):
        data = candles(start=1.2, step=-.0001, width=.0001)
        data[-1].update(close=1.25, high=1.251, low=1.17)
        self.assertEqual(evaluate('trend','EURUSD',self.bars(data)).side, 'BUY')
        self.assertIsNone(evaluate('trend','EURUSD',self.bars(candles())))

    def test_pullback_requires_recovery_in_existing_trend(self):
        data = candles(step=.0001)
        data[-2].update(close=1.1215, low=1.121)
        data[-1].update(close=1.124, high=1.125)
        signal = evaluate('pullback','EURUSD',self.bars(data))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, 'BUY')
        self.assertIsNone(evaluate('pullback','EURUSD',self.bars(candles())))

    def test_range_requires_reentry_and_reward_room(self):
        data = candles(step=0, width=.00005)
        for i in range(len(data)):
            close = 1.1 + (.001 if i % 2 else -.001)
            data[i].update(open=close,close=close,high=close+.00005,low=close-.00005)
        # Wide band and mean create enough reward relative to the stop.
        data[-2].update(open=1.095,close=1.095,high=1.09505,low=1.09495)
        data[-1].update(open=1.096,close=1.096,high=1.09605,low=1.09595)
        # Actual acceptance depends on the explicitly frozen band and reward rule.
        # A continuing move outside the band must never trigger catching a fall.
        data[-1].update(open=1.094,close=1.094,high=1.09405,low=1.09395)
        self.assertIsNone(evaluate('range','EURUSD',self.bars(data)))

    def test_range_recross_generates_mirrored_entries_with_mean_target(self):
        for direction in (1,-1):
            data=candles(step=0,width=.0002)
            # Frozen band: mean1.1, population std sqrt(.000008/20).
            for index,delta in [(-22,.002),(-21,-.002),(-2,-.0015),(-1,-.0012)]:
                close=1.1+direction*delta
                data[index].update(open=close,close=close,high=close+.0002,low=close-.0002)
            event=evaluate('range','EURUSD',self.bars(data))
            self.assertIsNotNone(event)
            self.assertEqual(event.side,'BUY' if direction==1 else 'SELL')
            self.assertAlmostEqual(event.tp,1.1)

    def test_trend_and_pullback_sell_mirror_is_not_buy_biased(self):
        for agent in ('trend','pullback'):
            if agent=='trend':
                data=candles(start=1.2,step=-.0001,width=.0001)
                data[-1].update(close=1.25,high=1.251,low=1.17)
            else:
                data=candles(step=.0001)
                data[-2].update(close=1.1215,low=1.121)
                data[-1].update(close=1.124,high=1.125)
            mirrored=[dict(time=b['time'],open=3-b['open'],close=3-b['close'],high=3-b['low'],low=3-b['high']) for b in data]
            self.assertEqual(evaluate(agent,'EURUSD',self.bars(mirrored)).side,'SELL')

    def test_all_agents_accept_gold_price_scale_in_both_directions(self):
        examples={}
        examples['trend']=candles(start=1.2,step=-.0001,width=.0001)
        examples['trend'][-1].update(close=1.25,high=1.251,low=1.17)
        examples['pullback']=candles(step=.0001)
        examples['pullback'][-2].update(close=1.1215,low=1.121)
        examples['pullback'][-1].update(close=1.124,high=1.125)
        examples['breakout']=candles(step=0)
        examples['breakout'][-1].update(close=1.102,high=1.103,low=1.097)
        examples['range']=candles(step=0,width=.0002)
        for index,delta in [(-22,.002),(-21,-.002),(-2,-.0015),(-1,-.0012)]:
            close=1.1+delta
            examples['range'][index].update(open=close,close=close,high=close+.0002,low=close-.0002)
        for name,rows in examples.items():
            gold=[dict(time=b['time'],**{k:2000*b[k] for k in ('open','high','low','close')}) for b in rows]
            buy=evaluate(name,'XAUUSD',self.bars(gold))
            self.assertEqual(buy.side,'BUY')
            self.assertGreater(buy.reference,2000)
            self.assertLess(buy.sl,buy.reference)
            self.assertGreater(buy.tp,buy.reference)
            mirror=[dict(time=b['time'],open=6000-b['open'],close=6000-b['close'],high=6000-b['low'],low=6000-b['high']) for b in gold]
            sell=evaluate(name,'XAUUSD',self.bars(mirror))
            self.assertEqual(sell.side,'SELL')
            self.assertGreater(sell.sl,sell.reference)
            self.assertLess(sell.tp,sell.reference)

if __name__ == '__main__':
    unittest.main()
