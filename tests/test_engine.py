import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from prediction_engine.config import Config
from prediction_engine.models import Signal
from prediction_engine.store import Store
from prediction_engine.engine import Engine
from tests.fixtures import snapshot, NOW


def signal(symbol='EURUSD', agent='breakout', bar=NOW-900):
    price = 1.124 if symbol=='EURUSD' else 2600.
    distance = .002 if symbol=='EURUSD' else 20.
    return Signal(agent,symbol,bar,'BUY',price,price-distance,price+2*distance,'test')


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=self.tmp.name+'/db.sqlite'
        self.store=Store(self.path)
        self.config=Config(account_login=123456)
        self.engine=Engine(self.config,self.store,clock=lambda:NOW)
        self.engine.ingest(snapshot(),evaluate_signals=False)
        self.engine.resume()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_dispatch_is_durable_and_never_reissued(self):
        cmd=self.engine.consider([signal()])
        self.assertEqual(cmd.split('|')[0],'OPEN')
        self.assertEqual(len(cmd.split('|')),14)
        self.assertEqual(float(cmd.split('|')[7]),25.)
        self.assertEqual(self.engine.consider([signal()]),'WAIT')
        self.assertEqual(self.store.db.execute('select count(*) from commands').fetchone()[0],1)
        self.assertIn('unresolved',self.engine.status().lower())
        restart=Engine(self.config,self.store,clock=lambda:NOW)
        restart.ingest(snapshot(),evaluate_signals=False)
        self.assertTrue(restart.paused)
        with self.assertRaises(ValueError): restart.resume()

    def test_concurrent_signals_only_dispatch_once(self):
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:self.engine.consider([signal()]),range(8)))
        self.assertEqual(sum(x.startswith('OPEN') for x in results),1)

    def test_live_wrong_server_and_stale_snapshots_cannot_trade(self):
        for field,value in [('demo',False),('server','OANDA_Global-Live-1'),('login',654321),('company','Other Broker')]:
            data=snapshot(); data['account'][field]=value
            self.assertEqual(self.engine.ingest(data,evaluate_signals=False),'WAIT')
            self.assertEqual(self.engine.consider([signal()]),'WAIT')
        data=snapshot(); data['utc']=NOW-100
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal()]),'WAIT')
        self.assertEqual(self.store.db.execute('select count(*) from commands').fetchone()[0],0)

    def test_bad_snapshot_revokes_previous_fresh_trading_state(self):
        data=snapshot(); data['account']['equity']=float('nan')
        with self.assertRaises(ValueError): self.engine.ingest(data)
        self.assertEqual(self.engine.consider([signal()]),'WAIT')

    def test_unknown_outcome_blocks_even_after_expiry(self):
        cmd=self.engine.consider([signal()]); command_id=cmd.split('|')[1]
        self.engine.result(dict(id=command_id,status='uncertain',retcode=10012,order=0,deal=0,volume=0,price=0,detail='timeout'))
        self.engine.clock=lambda:NOW+3600
        data=snapshot(); data['utc']=NOW+3600
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal('XAUUSD')]),'WAIT')

    def test_duplicate_and_late_results_cannot_undo_broker_fill(self):
        cmd=self.engine.consider([signal()]).split('|')
        self.engine.result(dict(id=cmd[1],status='filled',retcode=10009,order=77,deal=88,volume=.1,price=1.1241,detail='done'))
        self.assertEqual(self.engine.consider([signal('XAUUSD')]),'WAIT') # history must confirm
        data=snapshot()
        data['deals']=[dict(ticket=88,order=77,position_id=77,magic=int(cmd[9]),entry=0,symbol='EURUSD',volume=.1,profit=0,commission=-.5,swap=0,fee=0,time=NOW)]
        data['positions']=[dict(ticket=77,identifier=77,symbol='EURUSD',magic=int(cmd[9]),side='BUY',volume=.1,sl=1.122,tp=1.128,profit=0,risk=21)]
        self.engine.ingest(data,evaluate_signals=False)
        self.engine.result(dict(id=cmd[1],status='rejected',retcode=10006,order=0,deal=0,volume=0,price=0,detail='late'))
        self.assertEqual(self.store.command(cmd[1])['state'],'filled')
        self.assertTrue(self.engine.consider([signal('XAUUSD',agent='trend')]).startswith('OPEN'))
        self.assertEqual(self.store.db.execute('select count(*) from deals').fetchone()[0],1)

    def test_daily_loss_latches_even_if_equity_recovers_and_restarts(self):
        data=snapshot(); data['account']['equity']=9799
        self.engine.ingest(data,evaluate_signals=False)
        self.assertTrue(self.engine.paused)
        self.engine.ingest(snapshot(),evaluate_signals=False)
        with self.assertRaises(ValueError): self.engine.resume()
        restart=Engine(self.config,self.store,clock=lambda:NOW)
        restart.ingest(snapshot(),evaluate_signals=False)
        with self.assertRaises(ValueError): restart.resume()

    def test_foreign_positions_and_pending_orders_block_account(self):
        data=snapshot(); data['orders']=[dict(ticket=99,symbol='EURUSD',magic=0)]
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal('XAUUSD')]),'WAIT')
        data=snapshot(); data['positions']=[dict(ticket=1,identifier=1,symbol='XAUUSD',magic=0,side='BUY',volume=.1,sl=2590,tp=2630,profit=0,risk=10)]
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal()]),'WAIT')

    def test_wide_spread_and_stale_tick_reject(self):
        for field,value in [('ask',1.13),('tick_age',20),('tick_age',-1)]:
            data=snapshot(); data['symbols']['EURUSD'][field]=value
            self.engine.ingest(data,evaluate_signals=False)
            self.assertEqual(self.engine.consider([signal()]),'WAIT')
        self.assertEqual(self.store.db.execute('select count(*) from commands').fetchone()[0],0)

    def test_exit_attribution_uses_position_id_even_with_zero_magic(self):
        cmd=self.engine.consider([signal()]).split('|')
        common=dict(order=77,position_id=77,symbol='EURUSD',volume=.1,commission=-.5,swap=0,fee=0,time=NOW)
        data=snapshot(); data['deals']=[dict(common,ticket=88,magic=int(cmd[9]),entry=0,profit=0),dict(common,ticket=89,magic=0,entry=1,profit=20)]
        self.engine.ingest(data,evaluate_signals=False)
        self.engine.ingest(data,evaluate_signals=False)
        stats=self.store.stats()
        self.assertEqual(stats[0]['agent'],'breakout')
        self.assertEqual(stats[0]['net'],19.)
        self.assertEqual(stats[0]['closed'],1)

    def test_rejected_signal_cannot_come_back_later_on_same_bar(self):
        data=snapshot(); data['symbols']['EURUSD']['ask']=1.13
        self.engine.ingest(data,evaluate_signals=False)
        self.engine.consider([signal()])
        self.engine.ingest(snapshot(),evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal()]),'WAIT')

    def test_fresh_quote_does_not_make_stale_candles_tradeable(self):
        data=snapshot(); data['symbols']['EURUSD']['bar_age']['M15']=3600
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal()]),'WAIT')

    def test_connection_alert_is_sent_once_per_transition(self):
        self.engine.monitor()
        before=self.store.db.execute('select count(*) from outbox').fetchone()[0]
        self.engine.clock=lambda:NOW+30
        self.engine.monitor();self.engine.monitor()
        self.assertEqual(self.store.db.execute('select count(*) from outbox').fetchone()[0],before+1)
        data=snapshot();data['utc']=NOW+30
        self.engine.ingest(data,evaluate_signals=False)
        self.engine.monitor()
        self.assertEqual(self.store.db.execute('select count(*) from outbox').fetchone()[0],before+2)

    def test_manual_addition_or_reversal_quarantines_agent_history(self):
        cmd=self.engine.consider([signal()]).split('|')
        common=dict(order=77,position_id=77,symbol='EURUSD',commission=0,swap=0,fee=0,time=NOW)
        data=snapshot()
        data['deals']=[dict(common,ticket=88,magic=int(cmd[9]),entry=0,volume=.1,profit=0),
                       dict(common,ticket=89,magic=0,entry=2,volume=.2,profit=15)]
        data['positions']=[dict(ticket=90,identifier=77,symbol='EURUSD',magic=0,side='SELL',volume=.1,sl=1.126,tp=1.12,profit=0,risk=20)]
        self.engine.ingest(data,evaluate_signals=False)
        self.assertIn('mixed',self.engine.status().lower())
        self.assertEqual(self.engine.consider([signal('XAUUSD')]),'WAIT')
        self.assertEqual(self.store.stats(),[])
        data['positions']=[]
        data['deals'].append(dict(common,ticket=90,magic=0,entry=1,volume=.1,profit=500))
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.store.stats(),[])
        self.assertIn('excluded',self.engine.stats_text())

    def test_manual_addition_with_original_magic_on_position_is_still_foreign(self):
        cmd=self.engine.consider([signal()]).split('|')
        common=dict(order=77,position_id=77,symbol='EURUSD',volume=.1,commission=0,swap=0,fee=0,time=NOW,entry=0,profit=0)
        data=snapshot();data['deals']=[dict(common,ticket=88,magic=int(cmd[9])),dict(common,ticket=89,magic=0)]
        data['positions']=[dict(ticket=77,identifier=77,symbol='EURUSD',magic=int(cmd[9]),side='BUY',volume=.2,sl=1.122,tp=1.128,profit=0,risk=20)]
        self.engine.ingest(data,evaluate_signals=False)
        self.assertEqual(self.engine.consider([signal('XAUUSD')]),'WAIT')
        self.assertEqual(self.store.stats(),[])

    def test_resume_needs_at_least_one_usable_market(self):
        data=snapshot();data['symbols']={}
        self.engine.ingest(data,evaluate_signals=False);self.engine.pause()
        with self.assertRaises(ValueError): self.engine.resume()
        data=snapshot()
        data['symbols']['XAUUSD']['tick_age']=-1
        self.engine.ingest(data,evaluate_signals=False)
        self.assertIn('resumed',self.engine.resume())

if __name__=='__main__': unittest.main()
