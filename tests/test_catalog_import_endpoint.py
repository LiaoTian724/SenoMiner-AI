import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from chem_pdf_extractor import server as server_module


class CatalogImportEndpointTest(unittest.TestCase):
    def setUp(self):
        self.app=server_module.ChemExtractorApp(None)
        handler=type('CatalogHandler',(server_module.RequestHandler,),{'app':self.app})
        self.http=ThreadingHTTPServer(('127.0.0.1',0),handler)
        self.app.port=self.http.server_port
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join(2)

    def post(self,payload,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Chem-PDF-Extractor-Token']=self.app.ui_token
        request=urllib.request.Request(f'http://127.0.0.1:{self.app.port}/api/catalog/import',
            data=json.dumps(payload).encode(),headers=headers,method='POST')
        try:
            with urllib.request.urlopen(request) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as response:return response.code,json.load(response)

    def test_doi_starts_the_same_protected_pipeline_and_returns_initial_progress(self):
        fired=threading.Event();received=[]
        def worker(app,identifier):received.append(identifier);fired.set()
        with patch.object(server_module,'_run_catalog_import',side_effect=worker):
            status,data=self.post({'identifier':'https://doi.org/10.1234/test'})
            self.assertTrue(fired.wait(2))
        self.assertEqual(status,200)
        self.assertEqual(received,['DOI:10.1234/test'])
        self.assertTrue(data['running'])
        self.assertEqual(data['task']['stage'],'loading')
        self.assertEqual(self.post({'pmid':'123'})[0],409)

    def test_invalid_identifiers_and_missing_token_do_not_start_a_task(self):
        with patch.object(server_module,'_run_catalog_import') as run:
            self.assertEqual(self.post({'identifier':'https://example.com/file'})[0],400)
            self.assertEqual(self.post({'identifier':'DOI:10.1234/test'},token=False)[0],403)
        run.assert_not_called()
        self.assertIsNone(self.app.catalog_status()['task'])
