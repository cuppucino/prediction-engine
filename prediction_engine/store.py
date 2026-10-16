"""SQLite journal; broker outcomes and notifications survive process restarts."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading


class Store:
    def __init__(self,path):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self._file=open(str(path)+'.lock','a')
        try:
            fcntl.flock(self._file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            raise ValueError('Another engine owns this database') from None
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        os.chmod(path,0o600)
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS signals(key TEXT PRIMARY KEY,agent TEXT,symbol TEXT,bar_time INTEGER,payload TEXT,decision TEXT,reason TEXT);
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,magic INTEGER UNIQUE,signal_key TEXT UNIQUE,agent TEXT,symbol TEXT,state TEXT,created REAL,risk REAL,wire TEXT,result TEXT);
            CREATE TABLE IF NOT EXISTS deals(ticket INTEGER PRIMARY KEY,position_id INTEGER,magic INTEGER,entry INTEGER,volume REAL,net REAL,payload TEXT);
            CREATE TABLE IF NOT EXISTS ownership(position_id INTEGER PRIMARY KEY,command_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS quarantine(position_id INTEGER PRIMARY KEY,reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,dedupe TEXT UNIQUE,body TEXT,attempts INTEGER DEFAULT 0,next_attempt REAL DEFAULT 0,sent INTEGER DEFAULT 0);
        ''')

    @contextmanager
    def transaction(self):
        with self.lock,self.db:
            yield self.db

    def get(self,key,default=None):
        with self.lock:
            row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self,key,value):
        with self.transaction() as db:
            db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))

    def enqueue(self,key,body):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO outbox(dedupe,body) VALUES(?,?)',(key,body))

    def command(self,command_id):
        with self.lock:
            return self.db.execute('SELECT * FROM commands WHERE id=?',(command_id,)).fetchone()

    def unresolved(self):
        with self.lock:
            return self.db.execute("SELECT * FROM commands WHERE state IN ('dispatched','reported','uncertain') ORDER BY created").fetchall()

    def stats(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('''
                SELECT c.agent, c.symbol, count(*) as positions, sum(p.closed) as closed, sum(p.net) as net
                FROM (SELECT d.position_id, sum(d.net) as net,
                             CASE WHEN sum(CASE WHEN d.entry=0 THEN d.volume ELSE -d.volume END)<=0.00000001 THEN 1 ELSE 0 END as closed
                      FROM deals d JOIN ownership o ON d.position_id=o.position_id
                      WHERE NOT EXISTS(SELECT 1 FROM quarantine q WHERE q.position_id=d.position_id)
                      GROUP BY d.position_id) p
                JOIN ownership o ON p.position_id=o.position_id JOIN commands c ON c.id=o.command_id
                GROUP BY c.agent,c.symbol ORDER BY c.agent,c.symbol
            ''')]

    def close(self):
        with self.lock:
            self.db.close()
            self._file.close()
