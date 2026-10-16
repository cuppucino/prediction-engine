"""Interactive local setup; credentials never appear in shell arguments."""
import os
from pathlib import Path
import tempfile
from .telegram import telegram_request,TelegramError


def telegram_candidates(updates):
    result={}
    for update in updates:
        m=update.get('message',{})
        chat=m.get('chat',{});user=m.get('from',{})
        if chat.get('type')!='private' or m.get('text','').split(' ')[0]!='/start' or user.get('is_bot'): continue
        chat_id,user_id=chat.get('id'),user.get('id')
        if type(chat_id) is not int or type(user_id) is not int or min(chat_id,user_id)<=0: continue
        name=''.join(c for c in str(user.get('first_name','Telegram user')) if c.isprintable())[:80]
        result[(str(chat_id),str(user_id))]=name
    return [(chat,user,name) for (chat,user),name in result.items()]


def save_env_values(path,values):
    path=Path(path)
    lines=path.read_text().splitlines() if path.exists() else []
    remaining=dict(values);output=[]
    for line in lines:
        key=line.partition('=')[0]
        if key in values:
            if key in remaining: output.append(key+'='+remaining.pop(key))
        else: output.append(line)
    output.extend(k+'='+v for k,v in remaining.items())
    fd,temp=tempfile.mkstemp(prefix='.env-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as file:
            file.write('\n'.join(output)+'\n');file.flush();os.fsync(file.fileno())
        os.chmod(temp,0o600)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def telegram_setup(config):
    if not config.telegram_token:
        raise ValueError('Save TELEGRAM_BOT_TOKEN in the local .env file first; do not paste it into chat')
    try:
        bot=telegram_request(config.telegram_token,'getMe',{})
        print('Connected to bot @'+bot.get('username','unknown'))
        print('Send /start privately to this bot, then press Enter here. Stop any running engine first.')
        input()
        updates=telegram_request(config.telegram_token,'getUpdates',{'timeout':0,'allowed_updates':['message']})
        candidates=telegram_candidates(updates)
        if not candidates: raise ValueError('No private /start found. Send a new /start and run telegram-setup again')
        for i,(chat,user,name) in enumerate(candidates,1):
            print(f'{i}: {name}, chat {chat}, user {user}')
        selection=input('Choose your own chat number: ').strip()
        if not selection.isdigit() or not 1<=int(selection)<=len(candidates): raise ValueError('Invalid chat selection')
        chat,user,_=candidates[int(selection)-1]
        save_env_values('.env',{'TELEGRAM_CHAT_ID':chat,'TELEGRAM_USER_ID':user})
        print('Recipient and authorized user saved locally. Start the engine to receive its startup message.')
        return 0
    except TelegramError as exc:
        raise ValueError(str(exc)) from None
