import json
import csv
import io
from unittest.mock import patch
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


    def test_structured_records_api_filters_and_export_keeps_the_same_source(self):
        records=[{'id':'r1','compound_name':'Fisetin','study_type':'in_vitro','effect_type':'senolytic',
                  'model':'HCT116','dose':'20 µM','pubchem_cids':['5281614'],'source':{'title':'Paper','pmid':'123'}},
                 {'id':'r2','compound_name':'Fisetin','study_type':'in_vivo','effect_type':'senolytic',
                  'model':'Mouse','dose':'500 ppm','pubchem_cids':['5281614'],'source':{'title':'Paper','pmid':'123'}}]
        dataset={'compounds':[{'papers':[{'experiment_records':records}]}]}
        def request(suffix):
            return urllib.request.Request(self.base+'/api/catalog/records'+suffix,headers={'X-Chem-PDF-Extractor-Token':self.app.ui_token})
        with patch.object(server_module.catalog,'build_catalog',return_value=dataset):
            with urllib.request.urlopen(request('?q=HCT116&study_type=in_vitro')) as response:
                data=json.load(response)
            self.assertEqual(data['count'],1)
            self.assertEqual(data['records'][0]['id'],'r1')
            with urllib.request.urlopen(request('?format=csv&study_type=in_vitro')) as response:
                self.assertIn('attachment',response.headers['Content-Disposition'])
                rows=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['来源文献'],'Paper')
            self.assertEqual(rows[0]['PMID'],'123')
            with self.assertRaises(urllib.error.HTTPError) as exc:urllib.request.urlopen(self.base+'/api/catalog/records')
            self.assertEqual(exc.exception.code,403)
