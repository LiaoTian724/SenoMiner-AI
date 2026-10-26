import os
import re
import subprocess
import sys
import tempfile
import unittest
from importlib import resources
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PackageDataTest(unittest.TestCase):
    def test_pyproject_declares_console_script(self):
        content = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("[project.scripts]", content)
        self.assertRegex(
            content,
            re.compile(
                r'^chem-pdf-extractor\s*=\s*"chem_pdf_extractor\.entrypoint:run"$',
                re.MULTILINE,
            ),
        )

    def test_pyproject_declares_html_template_package_data(self):
        content = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("[tool.setuptools.package-data]", content)
        self.assertRegex(
            content,
            re.compile(
                r'^chem_pdf_extractor\s*=\s*\["templates/index\.html", "templates/showcase\.html", "templates/catalog\.html", "static/catalog\.css", "static/catalog\.js", "static/3Dmol-min\.js", "static/3Dmol-LICENSE\.txt"\]$',
                re.MULTILINE,
            ),
        )

    def test_template_file_resolves_from_package_resources(self):
        template = resources.files("chem_pdf_extractor").joinpath("templates", "index.html")

        content = template.read_text(encoding="utf-8")

        self.assertIn("<!doctype html>", content.lower())
        self.assertIn("Chem-PDF-Extractor", content)

    def test_server_import_and_template_load_succeeds(self):
        from chem_pdf_extractor.server import load_html_template

        content = load_html_template()

        self.assertIn("Chem-PDF-Extractor", content)
        self.assertIn("__DEFAULT_FIELDS_JSON__", content)

    def test_python_module_entrypoint_still_supports_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["CHEM_PDF_EXTRACTOR_LOG_DIR"] = tmp
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [sys.executable, "-m", "chem_pdf_extractor", "--help"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--cli", result.stdout)

if __name__ == "__main__":
    unittest.main()
