import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from dataclasses import replace
from prediction_engine.config import Config
from prediction_engine.store import Store
from prediction_engine.engine import Engine
from prediction_engine.server import make_server
from prediction_engine.telegram import TelegramWorker, TelegramError
from tests.fixtures import snapshot,NOW
from tests.fixtures import candles


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name+'/db')
        self.config=Config(account_login=123456,bridge_token='x'*48,telegram_token='fake',telegram_chat_id='55',telegram_user_id='66')
        self.engine=Engine(self.config,self.store,clock=lambda:NOW)

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def test_http_auth_snapshot_and_control_roundtrip(self):
        server=make_server(self.engine,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}'
        def post(path,data,token='x'*48):
            req=urllib.request.Request(url+path,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=5) as response: return response.read().decode()
        try:
            with self.assertRaises(urllib.error.HTTPError) as err: post('/v1/snapshot',snapshot(),'bad')
            self.assertEqual(err.exception.code,401)
            self.assertEqual(post('/v1/snapshot',snapshot()),'WAIT')
            self.assertIn('resumed',post('/v1/control',{'command':'resume'}))
            self.assertIn('RUNNING',post('/v1/control',{'command':'status'}))
            self.assertIn('Paused',post('/v1/control',{'command':'pause'}))
            with self.assertRaises(urllib.error.HTTPError) as err: post('/v1/snapshot',{'version':1})
            self.assertEqual(err.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_telegram_ignores_other_users_groups_and_old_resumes(self):
        self.engine.ingest(snapshot(),evaluate_signals=False)
        worker=TelegramWorker(self.engine,clock=lambda:NOW,transport=lambda *a: [])
        def update(uid=66,chat=55,kind='private',date=NOW,text='/resume',n=1):
            return dict(update_id=n,message=dict(date=date,text=text,chat=dict(id=chat,type=kind),**{'from':dict(id=uid)}))
        for wrong in [update(uid=99),update(chat=88),update(kind='group'),update(date=NOW-3600)]:
            worker.process(wrong)
            self.assertTrue(self.engine.paused)
        worker.process(update(n=5))
        self.assertFalse(self.engine.paused)
        self.engine.pause()
        worker.process(update(n=5)) # redelivery must not resume again
        self.assertTrue(self.engine.paused)

    def test_failed_notification_stays_queued_and_retries_after_backoff(self):
        self.store.enqueue('one','DEMO test notification')
        calls=[]
        def transport(method,data):
            calls.append((method,data))
            if len(calls)==1: raise TelegramError('network')
            return {'message_id':1}
        now=[NOW]
        worker=TelegramWorker(self.engine,clock=lambda:now[0],transport=transport)
        worker.send_pending()
        self.assertEqual(self.store.db.execute('select sent from outbox').fetchone()[0],0)
        worker.send_pending(); self.assertEqual(len(calls),1)
        now[0]+=61;worker.send_pending()
        self.assertEqual(self.store.db.execute('select sent from outbox').fetchone()[0],1)
        self.assertEqual(calls[-1][0],'sendMessage')
        self.assertEqual(calls[-1][1]['chat_id'],'55')

    def test_telegram_replay_after_process_restart_cannot_resume(self):
        self.engine.ingest(snapshot(),evaluate_signals=False)
        self.store.set('telegram_offset',17)
        worker=TelegramWorker(self.engine,clock=lambda:NOW,transport=lambda *a: [])
        worker.process(dict(update_id=16,message={'date':NOW,'text':'/resume','chat':{'id':55,'type':'private'},'from':{'id':66}}))
        self.assertTrue(self.engine.paused)

    def test_http_strategy_order_ack_and_exit_reconcile_end_to_end(self):
        server=make_server(self.engine,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def post(path,data):
            request=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+'x'*48,'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=5) as response:return response.read().decode()
        try:
            post('/v1/snapshot',snapshot())
            post('/v1/control',{'command':'resume'})
            data=snapshot()
            data['symbols']['EURUSD']['bars']['M15']=candles(start=1.123,step=0,width=.0005)
            data['symbols']['EURUSD']['bars']['M15'][-1].update(close=1.124,high=1.1241)
            fields=post('/v1/snapshot',data).split('|')
            self.assertEqual(fields[0],'OPEN')
            self.assertEqual(fields[3:5],['EURUSD','BUY'])
            self.assertGreater(float(fields[6]),1.1241)
            self.assertLess(float(fields[5]),1.124)
            self.assertEqual(post('/v1/snapshot',data),'WAIT')
            self.assertEqual(post('/v1/result',dict(id=fields[1],status='filled',retcode=10009,order=10,deal=11,volume=.1,price=1.1241,detail='demo fixture')),'OK')
            deal=dict(order=10,position_id=10,symbol='EURUSD',volume=.1,commission=-.5,swap=0,fee=0,time=NOW)
            data['deals']=[dict(deal,ticket=11,magic=int(fields[9]),entry=0,profit=0),dict(deal,ticket=12,magic=0,entry=1,profit=10)]
            post('/v1/snapshot',data)
            self.assertIn('9.00 USD',post('/v1/control',{'command':'stats'}))
            self.assertEqual(self.store.db.execute('select count(*) from commands').fetchone()[0],1)
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
