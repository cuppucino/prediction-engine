from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import secrets
import time
import uuid
from .models import Snapshot, ValidationError, number, integer, text
from .strategies import STRATEGIES, evaluate


class Engine:
    def __init__(self,config,store,clock=time.time):
        self.config,self.store,self.clock=config,store,clock
        self.snapshot=None
        self.received=0.
        self.paused=True
        self.last_issue='Waiting for MT5 bridge'
        self.last_received_utc=0.
        self._health=None

    def identity_issue(self,s):
        a=s.account
        if not a['demo']: return 'Refused: account is not demo'
        if self.config.account_login == 0: return 'Set account_login in config.toml to pin your demo account'
        if a['login'] != self.config.account_login: return 'Refused: account login mismatch'
        if a['server'] != self.config.account_server: return 'Refused: exact account server mismatch'
        if 'oanda' not in a['company'].lower(): return 'Refused: broker is not OANDA'
        identity=[a['login'],a['server'],a['currency']]
        if self.store.get('identity',identity)!=identity: return 'Refused: database belongs to another account/currency'
        symbols=list(self.config.symbols)
        if self.store.get('broker_symbols',symbols)!=symbols:
            return 'Refused: database is pinned to different broker symbols'
        if any(row['symbol'] not in symbols for row in self.store.db.execute('SELECT DISTINCT symbol FROM commands')):
            return 'Refused: database contains different broker symbols'
        return None

    def ingest(self,data,evaluate_signals=True):
        with self.store.lock:
            self.snapshot=None # malformed input must invalidate previous trading eligibility
            self.last_issue='Invalid or incomplete MT5 snapshot'
            s=Snapshot.parse(data, self.config.symbols)
            self.snapshot=s
            self.received=self.clock()
            issue=self.identity_issue(s)
            if issue:
                self.last_issue=issue
                self.paused=True
                return 'WAIT'
            if abs(s.utc-self.clock())>self.config.snapshot_max_age or s.utc<self.last_received_utc:
                self.last_issue='Stale or out-of-order snapshot'
                self.snapshot=None
                return 'WAIT'
            self.last_received_utc=s.utc
            self.store.set('identity',[s.account['login'],s.account['server'],s.account['currency']])
            self.store.set('broker_symbols',list(self.config.symbols))
            if s.account['equity']<=0:
                self.last_issue='Nonpositive account equity'
                self.paused=True
                return 'WAIT'
            day=datetime.fromtimestamp(self.clock(),timezone.utc).date().isoformat()
            baseline=self.store.get('day')
            if not baseline or baseline['date']!=day:
                if baseline:
                    last=baseline.get('last_equity',baseline['equity'])
                    self.store.enqueue('scorecard:'+baseline['date'],
                        f'DEMO daily recap {baseline["date"]} UTC\nLast observed equity {last:.2f} {s.account["currency"]}; change from daily baseline {last-baseline["equity"]:+.2f}.\nCumulative strategy totals:\n'+self.stats_text())
                baseline={'date':day,'equity':s.account['equity'],'tripped':False}
                self.store.set('day',baseline)
            floor=baseline['equity']*(1-self.config.daily_loss_fraction)
            if s.account['equity']<=floor:
                baseline['tripped']=True
                self.store.set('day',baseline)
                self.paused=True
                self.store.enqueue('daily-limit:'+day,'DEMO paused: daily equity loss limit reached. Existing broker SL/TP remain active.')
            baseline['last_equity']=s.account['equity']
            self.store.set('day',baseline)
            self._reconcile(s)
            self.last_issue=self._gate(include_pause=False) or 'Ready'
            if self.paused or not evaluate_signals: return 'WAIT'
            signals=[]
            for symbol in self.config.symbols:
                if symbol not in s.symbols: continue
                market=s.symbols[symbol]
                for agent,frame in STRATEGIES.items():
                    bars=market['bars'][frame]
                    event=evaluate(agent,symbol,bars)
                    if event: signals.append(event)
            return self.consider(signals)

    def _reconcile(self,s):
        with self.store.transaction() as db:
            for deal in s.deals:
                net=sum(deal[k] for k in ('profit','commission','swap','fee'))
                db.execute('INSERT OR IGNORE INTO deals VALUES(?,?,?,?,?,?,?)',
                           (deal['ticket'],deal['position_id'],deal['magic'],deal['entry'],deal['volume'],net,json.dumps(deal)))
                cmd=db.execute('SELECT * FROM commands WHERE magic=?',(deal['magic'],)).fetchone()
                if cmd and deal['entry']==0 and deal['symbol']==cmd['symbol']:
                    db.execute('INSERT OR IGNORE INTO ownership VALUES(?,?)',(deal['position_id'],cmd['id']))
                    db.execute("UPDATE commands SET state='filled' WHERE id=?",(cmd['id'],))
                    self.store.enqueue('fill:'+str(deal['ticket']),f'DEMO fill: {cmd["agent"]} {cmd["symbol"]}, {deal["volume"]:g} lots. Deal {deal["ticket"]}.')
            # Netting additions/reversals can retain an owned identifier while changing
            # whose exposure it represents. Exclude the entire mixed lifecycle.
            mixed=db.execute('''SELECT DISTINCT d.position_id FROM deals d
                JOIN ownership o ON o.position_id=d.position_id JOIN commands c ON c.id=o.command_id
                WHERE d.entry=2 OR (d.entry=0 AND d.magic!=c.magic)''').fetchall()
            for row in mixed:
                db.execute('INSERT OR IGNORE INTO quarantine VALUES(?,?)',(row['position_id'],'Manual/foreign addition or netting reversal'))
                self.store.enqueue('mixed:'+str(row['position_id']),f'DEMO mixed position {row["position_id"]}: foreign entry or netting reversal. Excluded from strategy P&L; new entries blocked while it remains open. Review MT5 history.')
            # Match plain exits by position identifier; broker/phone exits can carry magic=0.
            for deal in s.deals:
                if deal['entry'] not in (1,2,3): continue
                if db.execute('SELECT 1 FROM quarantine WHERE position_id=?',(deal['position_id'],)).fetchone(): continue
                row=db.execute('SELECT c.agent,c.symbol FROM ownership o JOIN commands c ON c.id=o.command_id WHERE o.position_id=?',(deal['position_id'],)).fetchone()
                if row:
                    net=sum(deal[k] for k in ('profit','commission','swap','fee'))
                    self.store.enqueue('exit:'+str(deal['ticket']),f'DEMO exit: {row["agent"]} {row["symbol"]}, {deal["volume"]:g} lots; deal net {net:.2f} {s.account["currency"]}.')

    def _gate(self,include_pause=True):
        s=self.snapshot
        if not s: return self.last_issue
        issue=self.identity_issue(s)
        if issue: return issue
        if self.clock()-self.received>self.config.snapshot_max_age or abs(self.clock()-s.utc)>self.config.snapshot_max_age:
            return 'MT5 snapshot is stale/disconnected'
        if not s.connected or not s.trade_allowed: return 'MT5 is disconnected or algorithmic trading is disabled'
        if not s.history_complete: return 'Broker history is incomplete; entries blocked'
        if s.account['equity']<=0: return 'Nonpositive equity'
        periods={'M15':900,'H1':3600,'H4':14400}
        usable=any(m['bid']>0 and m['ask']>=m['bid'] and 0<=m['tick_age']<=self.config.tick_max_age
                   and m['trade_mode'] in (1,2,4)
                   and any(len(m['bars'][frame])>=120 and 0<=m['bar_age'][frame]<=period+60 for frame,period in periods.items())
                   for m in s.symbols.values())
        if not usable: return 'No instrument has fresh quotes and sufficient completed candles'
        if self.store.get('day',{}).get('tripped'): return 'Daily loss limit is latched for this UTC day'
        if self.store.unresolved(): return 'Unresolved order outcome; reconcile broker history before resuming'
        if s.orders: return 'Pending broker orders exist; entries blocked'
        for pos in s.positions:
            if self.store.db.execute('SELECT 1 FROM quarantine WHERE position_id=?',(pos['identifier'],)).fetchone():
                return 'Mixed/manual position lifecycle is open; entries blocked'
            owned=self.store.db.execute('SELECT 1 FROM ownership WHERE position_id=?',(pos['identifier'],)).fetchone()
            if not owned: return 'Foreign or unreconciled position exists'
            if pos['risk']<0 or pos['sl']<=0: return 'Position has no verifiable protective stop'
        if len(s.positions)>=2: return 'Maximum two open positions reached'
        if s.account['margin_free']<s.account['equity']*(1-self.config.max_margin_fraction): return 'Margin use limit reached'
        if include_pause and self.paused: return 'Paused: new entries disabled'
        return None

    def consider(self,signals):
        with self.store.lock:
            command='WAIT'
            # Rotate priority with event time so one worker does not always win.
            names=list(STRATEGIES)
            candidates=sorted(signals,key=lambda s:(s.bar_time,(names.index(s.agent)-s.bar_time//900)%len(names),s.symbol))
            for signal in candidates:
                if self.store.db.execute('SELECT 1 FROM signals WHERE key=?',(signal.key,)).fetchone(): continue
                reason=self._gate()
                market=self.snapshot.symbols.get(signal.symbol) if self.snapshot else None
                if not reason:
                    reason=self._signal_gate(signal,market)
                if not reason and command!='WAIT': reason='Another command is already in flight'
                with self.store.transaction() as db:
                    db.execute('INSERT INTO signals VALUES(?,?,?,?,?,?,?)',(signal.key,signal.agent,signal.symbol,signal.bar_time,json.dumps(asdict(signal)),'rejected' if reason else 'dispatched',reason or 'accepted'))
                    if reason: continue
                    account=self.snapshot.account
                    risk=account['equity']*self.config.risk_fraction
                    open_risk=sum(p['risk'] for p in self.snapshot.positions)
                    if risk+open_risk>account['equity']*self.config.aggregate_risk_fraction+1e-8:
                        db.execute("UPDATE signals SET decision='rejected',reason='Aggregate stop-risk limit' WHERE key=?",(signal.key,))
                        continue
                    identifier=uuid.uuid4().hex[:24]
                    magic=700000000000+secrets.randbelow(100000000000)
                    distance=abs(signal.reference-signal.sl)
                    tick=market['tick_size']
                    # Stops round outward, targets inward to valid exchange ticks.
                    if signal.side=='BUY': sl=math.floor(signal.sl/tick+1e-8)*tick; tp=math.floor(signal.tp/tick+1e-8)*tick
                    else: sl=math.ceil(signal.sl/tick-1e-8)*tick; tp=math.ceil(signal.tp/tick-1e-8)*tick
                    floor=self.store.get('day')['equity']*(1-self.config.daily_loss_fraction)
                    parts=['OPEN',identifier,str(account['login']),signal.symbol,signal.side,f'{sl:.10f}',f'{tp:.10f}',f'{risk:.8f}',str(int(self.clock()+15)),str(magic),f'{distance*self.config.spread_stop_fraction:.10f}',f'{distance*self.config.drift_stop_fraction:.10f}',f'{floor:.8f}',str(self.config.max_margin_fraction)]
                    command='|'.join(parts)
                    db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?,NULL)',(identifier,magic,signal.key,signal.agent,signal.symbol,'dispatched',self.clock(),risk,command))
                self.store.enqueue('dispatch:'+identifier,f'DEMO order submitted to bridge: {signal.agent} {signal.side} {signal.symbol}. Intended stop risk {risk:.2f} {account["currency"]}; awaiting broker confirmation.')
            return command

    def _signal_gate(self,s,m):
        if s.symbol not in self.config.symbols or s.agent not in STRATEGIES or s.side not in ('BUY','SELL'): return 'Unknown strategy/instrument/direction'
        if not m or m['bid']<=0 or m['ask']<=0: return 'No valid market quote'
        if not 0<=m['tick_age']<=self.config.tick_max_age: return 'Stale market tick'
        frame=STRATEGIES[s.agent]
        if not 0<=m['bar_age'][frame]<={'M15':900,'H1':3600,'H4':14400}[frame]+60: return 'Stale completed candles'
        if len(m['bars'][frame])<120: return 'Insufficient completed candles'
        if m['trade_mode'] not in (4,1 if s.side=='BUY' else 2): return 'Instrument not open for this direction'
        if any(p['symbol']==s.symbol for p in self.snapshot.positions): return 'Instrument already occupied'
        if not all(math.isfinite(v) and v>0 for v in (s.sl,s.tp,s.reference)): return 'Invalid signal prices'
        price=m['ask'] if s.side=='BUY' else m['bid']
        side=1 if s.side=='BUY' else -1
        distance=abs(s.reference-s.sl)
        if not distance or side*(price-s.sl)<=0 or side*(s.tp-price)<=0: return 'Invalid protective levels'
        if abs(price-s.reference)>distance*self.config.drift_stop_fraction: return 'Price moved beyond signal entry tolerance'
        if m['ask']-m['bid']>distance*self.config.spread_stop_fraction: return 'Spread too wide'
        stop_min=m['stops_level']*m['point']+m['tick_size']
        liquidation=m['bid'] if s.side=='BUY' else m['ask']
        if min(side*(liquidation-s.sl),side*(s.tp-liquidation))<stop_min: return 'Broker minimum stop distance'
        return None

    def result(self,data):
        with self.store.lock:
            try:
                identifier=text(data['id'],'id',24)
                status=data['status']
                if status not in ('filled','rejected','uncertain'): raise ValidationError('Unknown execution status')
                for k in ('retcode','order','deal'): integer(data[k],k)
                for k in ('volume','price'): number(data[k],k,0)
                text(data.get('detail',''),'detail',500)
            except (KeyError,TypeError) as exc: raise ValidationError('Invalid execution result') from exc
            cmd=self.store.command(identifier)
            if not cmd: raise ValidationError('Unknown command id')
            if cmd['state'] in ('filled','rejected') or cmd['result'] is not None: return
            # A successful OrderSend is not proof of a deal: history confirms fills.
            state={'filled':'reported','rejected':'rejected','uncertain':'uncertain'}[status]
            with self.store.transaction() as db:
                db.execute('UPDATE commands SET state=?,result=? WHERE id=?',(state,json.dumps(data),identifier))
            self.store.enqueue('result:'+identifier,f'DEMO {cmd["agent"]} {cmd["symbol"]}: {status}; broker code {data["retcode"]}. '+('Waiting for deal reconciliation.' if state in ('reported','uncertain') else 'No automatic retry.'))

    def pause(self):
        with self.store.lock:
            self.paused=True
            return 'Paused new entries. Existing broker SL/TP remain active.'

    def resume(self):
        with self.store.lock:
            issue=self._gate(include_pause=False)
            if issue: raise ValueError(issue)
            self.paused=False
            return 'DEMO agents resumed; eligible signals will trade automatically.'

    def status(self):
        with self.store.lock:
            lines=['DEMO engine: '+('PAUSED' if self.paused else 'RUNNING'),self._gate(include_pause=False) or 'Ready for new signals']
            if self.snapshot:
                a=self.snapshot.account
                lines.append(f'{a["server"]} · {a["currency"]} · equity {a["equity"]:.2f}')
                lines.append(f'{len(self.snapshot.positions)} positions; {len(self.store.unresolved())} unresolved commands')
                for symbol,m in self.snapshot.symbols.items():
                    frames=', '.join(f'{frame}:{len(bars)} bars, age {m["bar_age"][frame]:g}s' for frame,bars in m['bars'].items())
                    lines.append(f'{symbol} tick age {m["tick_age"]:g}s; {frames}')
                for cmd in self.store.unresolved(): lines.append(f'Review command {cmd["id"]}: {cmd["agent"]} {cmd["symbol"]} ({cmd["state"]})')
            pending=self.store.db.execute('SELECT count(*) FROM outbox WHERE sent=0').fetchone()[0]
            lines.append(f'Telegram outbox: {pending} pending')
            return '\n'.join(lines)

    def monitor(self):
        with self.store.lock:
            health=self._gate(include_pause=False) or 'MT5 ready'
            if health!=self._health:
                self._health=health
                self.store.enqueue('health:'+uuid.uuid4().hex,'DEMO readiness: '+health)

    def stats_text(self):
        currency=self.snapshot.account['currency'] if self.snapshot else ''
        rows=self.store.stats()
        with self.store.lock:
            excluded=self.store.db.execute('SELECT count(*) FROM quarantine').fetchone()[0]
        return 'Recorded deal P&L (including fees/swap; not unrealized):\n'+('\n'.join(f'{r["agent"]} {r["symbol"]}: {r["net"]:.2f} {currency}; {r["closed"]} closed / {r["positions"]} positions' for r in rows) or 'No clean reconciled strategy trades yet.')+(f'\n{excluded} mixed position lifecycle(s) excluded; review MT5 history.' if excluded else '')

    def control(self,command):
        with self.store.lock:
            if command=='pause': return self.pause()
            if command=='resume': return self.resume()
            if command=='status': return self.status()
            if command in ('stats','leaderboard'): return self.stats_text()
            if command=='agents': return '\n'.join(f'{name} v1 · {frame} · {" + ".join(self.config.symbols)}' for name,frame in STRATEGIES.items())
            if command=='positions':
                return '\n'.join(f'{p["symbol"]} {p["side"]} {p["volume"]:g} lots · SL {p["sl"]} TP {p["tp"]}' for p in (self.snapshot.positions if self.snapshot else [])) or 'No positions in the latest snapshot.'
            return '/status /agents /positions /stats /pause /resume /help\nPause stops new entries only. Strategies are experimental; demo only.'
