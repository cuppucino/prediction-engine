"""Exercise the build wrapper without launching Wine or touching the real binary."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class CompilerWrapperTests(unittest.TestCase):
    def test_rejects_missing_compiler_and_unconfirmed_builds(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'scripts').mkdir();(root/'mt5').mkdir()
            script=root/'scripts/compile_mt5.sh'
            shutil.copy2(Path(__file__).resolve().parents[1]/'scripts/compile_mt5.sh',script)
            (root/'mt5/PredictionBridge.mq5').write_text('// build-wrapper fixture only\n')
            editor=root/'metaeditor.exe';editor.touch()
            wine=root/'wine'
            env={**os.environ,'MT5_METAEDITOR':str(editor),'MT5_WINE':str(wine),'MT5_WINEPREFIX':str(root)}
            def invoke(extra=None):
                return subprocess.run(['bash',str(script)],env={**env,**(extra or {})},capture_output=True,text=True,timeout=10)
            missing=invoke()
            self.assertNotEqual(missing.returncode,0)
            self.assertIn('Wine executable not found',missing.stderr)
            wine.write_text('''#!/usr/bin/env python3
import sys,pathlib,os
source=next(x[9:] for x in sys.argv if x.startswith('/compile:'))
log=next(x[5:] for x in sys.argv if x.startswith('/log:'))
convert=lambda s:s[2:].replace(chr(92),'/')
s=pathlib.Path(convert(source)); l=pathlib.Path(convert(log))
l.write_text('Result: '+os.environ.get('TEST_DIAGNOSTIC','0 errors, 0 warnings'),encoding='utf-16')
if not os.environ.get('TEST_NO_BINARY'): s.with_suffix('.ex5').write_bytes(b'compiled fixture')
''')
            wine.chmod(0o755)
            self.assertEqual(invoke().returncode,0)
            for extra in ({'TEST_DIAGNOSTIC':'1 errors, 0 warnings'},
                          {'TEST_DIAGNOSTIC':'0 errors, 1 warnings'},
                          {'TEST_NO_BINARY':'1'}):
                with self.subTest(extra=extra): self.assertNotEqual(invoke(extra).returncode,0)

if __name__=='__main__':unittest.main()
