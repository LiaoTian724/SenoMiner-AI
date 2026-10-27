import json
import threading
import unittest
import urllib.error
import urllib.request
from chem_pdf_extractor import server as server_module


class PresentationRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app=server_module.ChemExtractorApp(None)
        handler=type('PresentationHandler',(server_module.RequestHandler,),{'app':self.app})
        self.http=server_module.ThreadingHTTPServer(('127.0.0.1',0),handler)
        self.app.port=self.http.server_port
        self.base=f'http://127.0.0.1:{self.app.port}'
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join(2)

    def test_old_page_links_lead_to_one_simple_page(self):
        for path in ['/','/showcase','/catalog']:
            with self.subTest(path=path), urllib.request.urlopen(self.base+path) as response:
                page=response.read().decode()
                self.assertEqual(response.url,self.base+'/catalog')
                self.assertIn('上传并提取',page)
                self.assertIn('提取进展',page)
                self.assertIn('化合物列表',page)
                self.assertIn(self.app.ui_token,page)
                self.assertNotIn('__LOCAL_TOKEN__',page)
                for old in ['原始提取记录','PDF 工作台','id="cloudApiKey"','id="fieldTemplateSelect"','id="paperReviewRows"']:
                    self.assertNotIn(old,page)

    def test_retired_raw_record_apis_cannot_start_jobs_or_download_reports(self):
        for method,path in [('GET','/api/showcase'),('GET','/api/showcase/file?kind=json'),('POST','/api/showcase/start')]:
            with self.subTest(method=method,path=path):
                request=urllib.request.Request(self.base+path,method=method,
                    data=b'{}' if method=='POST' else None,
                    headers={'X-Chem-PDF-Extractor-Token':self.app.ui_token})
                with self.assertRaises(urllib.error.HTTPError) as exc:urllib.request.urlopen(request)
                self.assertEqual(exc.exception.code,404)
        self.assertIsNone(self.app.catalog_status()['task'])

    def test_retired_api_still_requires_the_local_token(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(self.base+'/api/showcase')
        self.assertEqual(exc.exception.code,403)
