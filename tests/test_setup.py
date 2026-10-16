import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prediction_engine.setup import telegram_candidates, save_env_values


class SetupTests(unittest.TestCase):
    def test_only_private_start_messages_can_supply_recipient(self):
        updates=[{'message':{'text':'/start','chat':{'id':55,'type':'private'},'from':{'id':66,'first_name':'Owner'}}},
                 {'message':{'text':'/start','chat':{'id':-55,'type':'group'},'from':{'id':99}}},
                 {'message':{'text':'hello','chat':{'id':88,'type':'private'},'from':{'id':77}}}]
        self.assertEqual(telegram_candidates(updates),[('55','66','Owner')])

    def test_local_env_update_preserves_secrets_without_printing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'.env'
            path.write_text('BRIDGE_TOKEN=private\nTELEGRAM_BOT_TOKEN=secret\nTELEGRAM_CHAT_ID=\n')
            save_env_values(path,{'TELEGRAM_CHAT_ID':'55','TELEGRAM_USER_ID':'66'})
            self.assertEqual(path.read_text(),'BRIDGE_TOKEN=private\nTELEGRAM_BOT_TOKEN=secret\nTELEGRAM_CHAT_ID=55\nTELEGRAM_USER_ID=66\n')
            self.assertEqual(path.stat().st_mode&0o777,0o600)

if __name__=='__main__':unittest.main()
