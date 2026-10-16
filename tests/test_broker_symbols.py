import tempfile
import unittest
from dataclasses import replace

from prediction_engine.config import Config
from prediction_engine.engine import Engine
from prediction_engine.models import ValidationError
from prediction_engine.store import Store
from tests.fixtures import NOW, candles, snapshot


class BrokerSymbolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + '/engine.sqlite')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def configured_engine(self):
        try:
            config = Config(account_login=123456, eurusd_symbol='EURUSD.sml',
                            xauusd_symbol='XAUUSD.sml')
        except (TypeError, ValueError) as error:
            self.fail(f'Exact OANDA symbol configuration was rejected: {error}')
        return Engine(config, self.store, clock=lambda: NOW)

    def broker_snapshot(self):
        data = snapshot()
        data['symbols'] = {name + '.sml': market for name, market in data['symbols'].items()}
        return data

    def breakout(self, engine, symbol):
        data = self.broker_snapshot()
        engine.ingest(data)
        engine.resume()
        market = data['symbols'][symbol]
        point, price = market['point'], market['bid']
        bars = candles(start=price - 100 * point, step=0, width=50 * point)
        bars[-1].update(close=price, high=price + 10 * point)
        market['bars']['M15'] = bars
        return engine.ingest(data).split('|'), data

    def test_euro_orders_and_reconciled_history_keep_exact_broker_symbol(self):
        engine = self.configured_engine()
        fields, data = self.breakout(engine, 'EURUSD.sml')
        self.assertEqual(fields[0], 'OPEN')
        self.assertEqual(fields[3:5], ['EURUSD.sml', 'BUY'])
        self.assertEqual(float(fields[7]), 25.)
        deal = dict(order=10, position_id=10, symbol='EURUSD.sml', volume=.1,
                    commission=-.5, swap=0, fee=0, time=NOW)
        data['deals'] = [dict(deal, ticket=11, magic=int(fields[9]), entry=0, profit=0),
                         dict(deal, ticket=12, magic=0, entry=1, profit=10)]
        engine.ingest(data, evaluate_signals=False)
        self.assertEqual(self.store.command(fields[1])['state'], 'filled')
        stats = self.store.stats()
        self.assertEqual((stats[0]['symbol'], stats[0]['net'], stats[0]['closed']),
                         ('EURUSD.sml', 9., 1))
        self.assertIn('EURUSD.sml', engine.status())
        self.assertIn('XAUUSD.sml', engine.control('agents'))

    def test_gold_breakout_dispatches_the_exact_configured_symbol(self):
        fields, _ = self.breakout(self.configured_engine(), 'XAUUSD.sml')
        self.assertEqual(fields[0], 'OPEN')
        self.assertEqual(fields[3:5], ['XAUUSD.sml', 'BUY'])
        self.assertLess(float(fields[5]), 2600.)
        self.assertGreater(float(fields[6]), 2600.)

    def test_unconfigured_quote_variant_revokes_trading_readiness(self):
        engine = self.configured_engine()
        engine.ingest(self.broker_snapshot())
        engine.resume()
        for name in ('EURUSD', 'EURUSD.other', 'GBPUSD.sml'):
            with self.subTest(symbol=name):
                data = self.broker_snapshot()
                data['symbols'][name] = data['symbols'].pop('EURUSD.sml')
                with self.assertRaises(ValidationError):
                    engine.ingest(data)
                self.assertIsNone(engine.snapshot)
                with self.assertRaises(ValueError):
                    engine.resume()
        self.assertEqual(self.store.db.execute('select count(*) from commands').fetchone()[0], 0)

    def test_foreign_unsuffixed_position_is_not_mapped_to_owned_variant(self):
        engine = self.configured_engine()
        data = self.broker_snapshot()
        data['positions'] = [dict(ticket=1, identifier=1, symbol='EURUSD', magic=0,
                                  side='BUY', volume=.1, sl=1.122, tp=1.128, profit=0, risk=20)]
        engine.ingest(data)
        self.assertIn('Foreign', engine.status())
        with self.assertRaises(ValueError):
            engine.resume()

    def test_symbol_configuration_is_pinned_across_engine_restarts(self):
        engine = self.configured_engine()
        engine.ingest(self.broker_snapshot())
        changed = replace(engine.config, eurusd_symbol='EURUSD.other')
        restart = Engine(changed, self.store, clock=lambda: NOW)
        data = self.broker_snapshot()
        data['symbols']['EURUSD.other'] = data['symbols'].pop('EURUSD.sml')
        self.assertEqual(restart.ingest(data), 'WAIT')
        self.assertIn('symbol', restart.status().lower())
        with self.assertRaises(ValueError):
            restart.resume()

    def test_config_rejects_other_instruments_and_command_delimiters(self):
        config = self.configured_engine().config
        for name in ('GBPUSD', 'XAUUSD.sml', 'EURUSD.', 'EURUSD|BUY', 'EURUSD.sml\n',
                     'EURUSD.sml extra', 'eurusd.sml', 'EURUSD.' + 'a' * 30):
            with self.subTest(symbol=name), self.assertRaises(ValueError):
                replace(config, eurusd_symbol=name)
        with self.assertRaises(ValueError):
            replace(config, xauusd_symbol='EURUSD.sml')


if __name__ == '__main__':
    unittest.main()
