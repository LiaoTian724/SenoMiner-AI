import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from chem_pdf_extractor import showcase
from chem_pdf_extractor import server as server_module


class ShowcaseTest(unittest.TestCase):
    def test_presents_only_the_fixed_single_paper_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = showcase.result_path(root)
            output.mkdir(parents=True)
            (root / "input_pdfs").mkdir()
            showcase.paper_path(root).write_bytes(b"%PDF-test")
            self.assertFalse(showcase.snapshot(root)["ready"])
            (output / "experiments.xlsx").write_bytes(b"xlsx")
            (output / "report.json").write_text(json.dumps({
                "llm": {"model": "test-model"},
                "records": [{
                    "compound_name": "Fisetin", "record_type": "chemical_candidate",
                    "needs_review": True, "evidence_status": "needs_review",
                    "pubchem_cid": 5281614, "related_pmids": "123; 456",
                    "field_evidence": '{"compound_name":"Fisetin"}',
                    "external_evidence": json.dumps({"components": [{
                        "query_name": "Dasatinib", "status": "resolved",
                        "pubchem": {"cid": 3062316}, "chembl": {"id": "CHEMBL1421"},
                        "api_key": "must-not-be-rendered",
                    }]}),
                    "cloud_api_key": "must-not-be-rendered",
                }],
            }), encoding="utf-8")
            data = showcase.snapshot(root)
            self.assertTrue(data["ready"])
            self.assertEqual(data["summary"]["records"], 1)
            self.assertEqual(data["summary"]["needs_review"], 1)
            self.assertEqual(data["summary"]["pubchem_cids"], 2)
            self.assertEqual(data["summary"]["related_pmids"], 2)
            self.assertEqual(data["records"][0]["components"], [{
                "name": "Dasatinib", "status": "resolved",
                "pubchem_cid": 3062316, "chembl_id": "CHEMBL1421",
            }])
            self.assertNotIn("must-not-be-rendered", json.dumps(data))
            self.assertIsNone(showcase.downloadable_file("../../.env", root))

    def test_page_has_no_unresolved_token_placeholder(self):
        html = showcase.render_page("local-test-token")
        self.assertIn("local-test-token", html)
        self.assertNotIn("__LOCAL_TOKEN__", html)
        self.assertIn("一篇 PDF 的完整提取流程", html)

    def test_showcase_api_keeps_report_and_downloads_behind_local_token(self):
        app = server_module.ChemExtractorApp(runtime=object())
        server = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.RequestHandler)
        app.port = server.server_address[1]
        app.server = server
        server_module.RequestHandler.app = app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{app.port}"
            with urllib.request.urlopen(base + "/showcase") as response:
                self.assertEqual(response.status, 200)
                page = response.read()
                self.assertIn(b"Senolytics Knowledge", page)
                self.assertIn(app.ui_token.encode(), page)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + "/api/showcase")
            self.assertEqual(denied.exception.code, 403)
            request = urllib.request.Request(
                base + "/api/showcase",
                headers={"X-Chem-PDF-Extractor-Token": app.ui_token},
            )
            with urllib.request.urlopen(request) as response:
                payload = json.load(response)
            self.assertEqual(payload["paper"]["pmcid"], "PMC6796530")
            request = urllib.request.Request(
                base + "/api/showcase/file?kind=../../.env",
                headers={"X-Chem-PDF-Extractor-Token": app.ui_token},
            )
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(request)
            self.assertEqual(missing.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
