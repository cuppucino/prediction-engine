import io
import os
from pathlib import Path
import ssl
import unittest
import urllib.error
from unittest.mock import patch

from prediction_engine.telegram import telegram_request, TelegramError


class TelegramTransportTests(unittest.TestCase):
    @unittest.skipUnless(Path('/etc/ssl/cert.pem').is_file(),'requires the macOS system CA bundle')
    def test_macos_missing_default_roots_uses_verified_system_bundle(self):
        # Simulate the actual python.org install: no default roots loaded.
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        defaults=ssl.get_default_verify_paths()._replace(cafile=None,capath=None)
        def receive(request,**kwargs):
            actual=kwargs.get('context')
            if actual is None or actual.cert_store_stats()['x509_ca']==0:
                raise urllib.error.URLError(ssl.SSLCertVerificationError(1,'missing trust roots'))
            self.assertEqual(actual.verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(actual.check_hostname)
            return io.BytesIO(b'{"ok":true,"result":{"is_bot":true}}')
        with patch.dict(os.environ,{},clear=True), \
             patch('sys.platform','darwin'), \
             patch('ssl.create_default_context',return_value=context), \
             patch('ssl.get_default_verify_paths',return_value=defaults), \
             patch('urllib.request.urlopen',side_effect=receive):
            self.assertEqual(telegram_request('123:private-test-token','getMe',{}),{'is_bot':True})

    def test_explicit_custom_ca_is_not_replaced_by_system_fallback(self):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        defaults=ssl.get_default_verify_paths()._replace(cafile=None,capath=None)
        def receive(request,**kwargs):
            actual=kwargs.get('context')
            self.assertIs(actual,context)
            self.assertEqual(actual.cert_store_stats()['x509_ca'],0)
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1,'custom CA unavailable'))
        with patch.dict(os.environ,{'SSL_CERT_FILE':'/missing/explicit-ca.pem'},clear=True), \
             patch('sys.platform','darwin'), \
             patch('ssl.create_default_context',return_value=context), \
             patch('ssl.get_default_verify_paths',return_value=defaults), \
             patch('urllib.request.urlopen',side_effect=receive):
            with self.assertRaisesRegex(TelegramError,'certificate'):
                telegram_request('123:private-test-token','getMe',{})

    def test_invalid_token_and_polling_conflict_are_actionable_without_leaking_url(self):
        token='123:private-test-token'
        for status,expected in [(401,'token'),(409,'another'),(429,'rate limit')]:
            with self.subTest(status=status):
                error=urllib.error.HTTPError('https://api.telegram.org/bot'+token+'/getMe',status,'upstream echoed '+token,{},None)
                with patch('urllib.request.urlopen',side_effect=error):
                    with self.assertRaises(TelegramError) as caught:
                        telegram_request(token,'getMe',{})
                self.assertIn(expected,str(caught.exception).lower())
                self.assertNotIn(token,str(caught.exception))
                self.assertNotIn('https://',str(caught.exception))

    def test_network_error_does_not_echo_credentials(self):
        token='123:private-test-token'
        with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('URL '+token)):
            with self.assertRaises(TelegramError) as caught:
                telegram_request(token,'getMe',{})
        self.assertIn('network',str(caught.exception).lower())
        self.assertNotIn(token,str(caught.exception))


if __name__=='__main__':unittest.main()
