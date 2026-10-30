import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from chem_pdf_extractor.single_instance import WebInstance
from chem_pdf_extractor.server import start_web_app


class SingleInstanceTest(unittest.TestCase):
    def test_second_process_cannot_start_until_owner_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner = WebInstance(Path(tmp))
            self.assertTrue(owner.acquire())
            owner.publish(8766)
            script = ('import sys;from pathlib import Path;'
                      'from chem_pdf_extractor.single_instance import WebInstance;'
                      'i=WebInstance(Path(sys.argv[1]));print(i.acquire());i.close()')
            result = subprocess.run([sys.executable, '-c', script, tmp], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), 'False')
            owner.close()
            result = subprocess.run([sys.executable, '-c', script, tmp], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), 'True')

    def test_crashed_owner_does_not_leave_a_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = ('import sys,os;from pathlib import Path;'
                      'from chem_pdf_extractor.single_instance import WebInstance;'
                      'i=WebInstance(Path(sys.argv[1]));assert i.acquire();i.publish(8767);os._exit(0)')
            subprocess.run([sys.executable, '-c', script, tmp], check=True)
            owner = WebInstance(Path(tmp))
            try:
                self.assertTrue(owner.acquire())
                owner.file.seek(0)
                self.assertEqual(owner.file.read(), b' ')
            finally:
                owner.close()

    def test_repeated_start_reuses_existing_url_without_loading_another_server(self):
        with patch('chem_pdf_extractor.single_instance.WebInstance') as cls, \
             patch('chem_pdf_extractor.server._serve_web_app') as serve, \
             patch('chem_pdf_extractor.server.webbrowser.open') as browser:
            instance = cls.return_value
            instance.acquire.return_value = False
            instance.existing_url.return_value = 'http://127.0.0.1:8766/catalog'
            self.assertEqual(start_web_app(8766, False, True), 0)
            serve.assert_not_called()
            browser.assert_called_once_with('http://127.0.0.1:8766/catalog')
            instance.close.assert_called_once()

    def test_startup_failure_releases_lock(self):
        with patch('chem_pdf_extractor.single_instance.WebInstance') as cls, \
             patch('chem_pdf_extractor.server._serve_web_app', side_effect=RuntimeError('bind failed')):
            cls.return_value.acquire.return_value = True
            with self.assertRaisesRegex(RuntimeError, 'bind failed'):
                start_web_app(8766, False)
            cls.return_value.close.assert_called_once()

    def test_registry_must_match_live_instance_and_current_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner, other = WebInstance(Path(tmp)), WebInstance(Path(tmp))
            try:
                self.assertTrue(owner.acquire());owner.publish(8766)
                self.assertFalse(other.acquire())
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps({'instance_id':owner.instance_id}).encode()
                with patch('urllib.request.urlopen', return_value=response):
                    self.assertEqual(other.existing_url(), 'http://127.0.0.1:8766/catalog')
                    other.generation = 'changed-code'
                    with self.assertRaisesRegex(RuntimeError, '旧服务仍在运行'):
                        other.existing_url()
                response.__enter__.return_value.read.return_value = b'{"instance_id":"unrelated-process"}'
                with patch('urllib.request.urlopen', return_value=response):
                    with self.assertRaisesRegex(RuntimeError, '不会重复启动'):
                        other.existing_url()
            finally:
                other.close();owner.close()
