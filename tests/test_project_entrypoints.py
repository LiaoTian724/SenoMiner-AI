"""Check the relocated launchers from outside the project directory."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import run_senolytics


ROOT = Path(__file__).resolve().parents[1]


class ProjectEntrypointsTest(unittest.TestCase):
    def test_launchers_resolve_the_root_from_another_working_directory(self):
        commands = [
            [sys.executable, str(ROOT / "run_senolytics.py"), "--help"],
            ["/bin/bash", str(ROOT / "启动项目.command"), "--help"],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for command in commands:
                with self.subTest(command=command[0]):
                    result = subprocess.run(
                        command, cwd=tmp,
                        env={**os.environ, "CHEM_PDF_EXTRACTOR_LOG_DIR": tmp},
                        text=True, capture_output=True, timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--no-auto-install", result.stdout)

    def test_launcher_rejects_a_different_environment(self):
        with patch.object(sys, "prefix", "/tmp/another-environment"):
            with self.assertRaisesRegex(SystemExit, "SenoMiner_AI"):
                run_senolytics.main()

    def test_package_identity_is_preserved(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["name"], "chem-pdf-extractor")
        self.assertEqual(data["project"]["version"], "0.4.0")


if __name__ == "__main__":
    unittest.main()
