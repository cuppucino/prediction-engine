import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request


class TelegramError(Exception):
    """Redacted external error: never include the token-bearing URL."""


def telegram_ssl_context():
    context=ssl.create_default_context()
    paths=ssl.get_default_verify_paths()
    # Some python.org macOS installs have no CA bundle until the optional
    # certificate installer is run. Use the OS bundle only for that empty-store
    # case; never override an explicitly configured trust store or TLS checks.
    if (sys.platform=='darwin' and not paths.cafile and not paths.capath
            and 'SSL_CERT_FILE' not in os.environ and 'SSL_CERT_DIR' not in os.environ
            and context.cert_store_stats()['x509_ca']==0
            and Path('/etc/ssl/cert.pem').is_file()):
        context.load_verify_locations(cafile='/etc/ssl/cert.pem')
    return context


def telegram_failure(status):
    # Do not surface upstream descriptions: they may contain the token-bearing URL.
    messages={
        401:'Telegram rejected the bot token. Check TELEGRAM_BOT_TOKEN in the local .env file.',
        404:'Telegram could not find this bot endpoint. Check the bot token in the local .env file.',
        409:'Telegram polling conflicts with another poller or webhook. Stop the other bot process or remove its webhook.',
        429:'Telegram rate limit reached. Wait briefly and retry.',
        403:'Telegram denied access. Open the bot privately, send /start, and check that it is not blocked.',
    }
    return messages.get(status,'Telegram rejected the request. Check local bot settings and try again.')


def telegram_request(token,method,data):
    try:
        req=urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',
            data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=20,context=telegram_ssl_context()) as response:
            result=json.loads(response.read(2*1024*1024))
        if result.get('ok') is not True: raise TelegramError(telegram_failure(result.get('error_code')))
        return result['result']
    except TelegramError:
        raise
    except urllib.error.HTTPError as error:
        status=error.code
        error.close()
        raise TelegramError(telegram_failure(status)) from None
    except urllib.error.URLError as error:
        if isinstance(error.reason,ssl.SSLCertVerificationError):
            raise TelegramError('Telegram TLS certificate verification failed. Check Python/system trusted certificates and any SSL_CERT_FILE or SSL_CERT_DIR settings.') from None
        raise TelegramError('Telegram network connection failed. Check internet, DNS, proxy or VPN settings and retry.') from None
    except ssl.SSLError:
        raise TelegramError('Telegram TLS/certificate setup failed. Check Python/system trusted certificates.') from None
    except TimeoutError:
        raise TelegramError('Telegram network request timed out. Check connectivity and retry.') from None
    except Exception:
        raise TelegramError('Telegram request could not be completed. Check the local bot settings; credentials were not logged.') from None


class TelegramWorker:
    def __init__(self,engine,clock=time.time,transport=None):
        self.engine,self.store,self.config=engine,engine.store,engine.config
        self.clock=clock
        self.started=clock()
        self.transport=transport or self._request
        self.stop=threading.Event()
        self.last_error=None

    @property
    def configured(self):
        return bool(self.config.telegram_token and self.config.telegram_chat_id.isdigit() and self.config.telegram_user_id.isdigit())

    def _request(self,method,data):
        return telegram_request(self.config.telegram_token,method,data)

    def process(self,update):
        if not isinstance(update,dict): return
        uid=update.get('update_id')
        if type(uid) is not int or uid<self.store.get('telegram_offset',0): return
        # A crash can lose a control request, but cannot replay a consumed resume.
        self.store.set('telegram_offset',uid+1)
        message=update.get('message',{})
        if not isinstance(message,dict): return
        chat=message.get('chat',{});sender=message.get('from',{})
        if chat.get('type')!='private' or str(chat.get('id'))!=self.config.telegram_chat_id or str(sender.get('id'))!=self.config.telegram_user_id or sender.get('is_bot',False): return
        content=message.get('text','')
        if not isinstance(content,str) or not content.startswith('/'): return
        command=content.split()[0][1:].split('@')[0].lower()
        timestamp=message.get('date',0)
        if type(timestamp) is not int: return
        if command=='resume' and (timestamp<self.started or not 0<=self.clock()-timestamp<=60):
            reply='Ignored an old /resume. Send a fresh command after checking /status.'
        else:
            try: reply=self.engine.control(command)
            except ValueError as exc: reply='Cannot resume: '+str(exc)
        self.store.enqueue('telegram-update:'+str(uid),reply)

    def send_pending(self):
        with self.store.lock:
            rows=self.store.db.execute('SELECT * FROM outbox WHERE sent=0 AND next_attempt<=? ORDER BY id LIMIT 10',(self.clock(),)).fetchall()
        for row in rows:
            try:
                # Plain text avoids interpreting strategy/account values as markup.
                self.transport('sendMessage',{'chat_id':self.config.telegram_chat_id,'text':row['body'][:4000]})
            except TelegramError:
                attempts=row['attempts']+1
                with self.store.transaction() as db:
                    db.execute('UPDATE outbox SET attempts=?,next_attempt=? WHERE id=?',(attempts,self.clock()+min(300,5*2**min(attempts,6)),row['id']))
                self.last_error='Telegram delivery failed; durable retry pending'
                break
            else:
                with self.store.transaction() as db:
                    db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['id'],))
                self.last_error=None

    def run(self):
        if not self.configured: return
        while not self.stop.is_set():
            self.send_pending()
            try:
                updates=self.transport('getUpdates',{'offset':self.store.get('telegram_offset',0),'timeout':10,'allowed_updates':['message']})
                for update in sorted(updates,key=lambda x:x.get('update_id',0)):
                    self.process(update)
            except (TelegramError,ValueError,TypeError,AttributeError):
                self.last_error='Telegram polling failed; retrying'
                self.stop.wait(5)
