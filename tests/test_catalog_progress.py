import copy
import json
import ssl
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from chem_pdf_extractor.catalog_progress import CatalogProgress
from chem_pdf_extractor.server import ChemExtractorApp, _run_catalog_import, _run_catalog_pdf, _catalog_report_complete
from chem_pdf_extractor.sources import normalize_identifier, resolve_pubmed_identifier
from chem_pdf_extractor.network import tls_context, subprocess_tls_env
from chem_pdf_extractor.llm import cloud_chat_completion, TransientCloudAPIError


class CatalogProgressTest(unittest.TestCase):
    def test_counts_follow_finished_work_and_stop_elapsed_time_on_failure(self):
        t=CatalogProgress()
        with patch('chem_pdf_extractor.catalog_progress.time.time',return_value=100):
            self.assertTrue(t.start('paper.pdf','pdf'))
            self.assertFalse(t.start('other.pdf','pdf'))
            t.update('extracting',completed=0,total=3,message='正在提取')
        with patch('chem_pdf_extractor.catalog_progress.time.time',return_value=120):
            t.update('extracting',completed=2,total=3)
            self.assertEqual(t.snapshot()['task']['elapsed_seconds'],20)
            t.log('completed 2')
            t.finish('网络失败，请重试')
        with patch('chem_pdf_extractor.catalog_progress.time.time',return_value=160):
            state=t.snapshot()
            self.assertFalse(state['running'])
            self.assertEqual(state['task']['status'],'failed')
            self.assertEqual(state['task']['elapsed_seconds'],20)
            self.assertEqual(state['task']['completed'],2)
            self.assertEqual(len(state['task']['events']),1)
            self.assertTrue(t.start('paper.pdf','pdf'))
            self.assertEqual(t.snapshot()['task']['completed'],0)

    def test_phase_changes_reset_segment_counter_and_bound_logs(self):
        t=CatalogProgress();t.start('paper.pdf','pdf')
        t.update('extracting',completed=5,total=5)
        t.update('reviewing',message='核对全文')
        for i in range(40):t.log(str(i))
        state=t.snapshot()['task']
        self.assertEqual(state['total'],0)
        self.assertEqual(len(state['events']),30)
        self.assertEqual(state['stage_label'],'核对原文')
        t.finish()
        self.assertEqual(t.snapshot()['task']['status'],'complete')

    def test_abstract_only_doi_is_not_sent_to_model_and_requests_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=ChemExtractorApp(None);app.catalog_task.start('DOI:10.1234/test','identifier')
            with patch('chem_pdf_extractor.server.PROJECT_ROOT',Path(tmp)), \
                 patch('chem_pdf_extractor.server._catalog_config',return_value={}), \
                 patch('chem_pdf_extractor.science_skills.ScienceSkills'), \
                 patch('chem_pdf_extractor.sources.resolve_pubmed_identifier',return_value='123'), \
                 patch('chem_pdf_extractor.sources.load_paper',return_value={'scope':'abstract_only'}), \
                 patch('chem_pdf_extractor.biomedical.extract_article') as extract:
                _run_catalog_import(app,'DOI:10.1234/test')
            extract.assert_not_called()
            self.assertEqual(app.catalog_status()['task']['status'],'needs_pdf')
            self.assertIn('PDF',app.catalog_status()['error'])

    def test_partial_report_is_retried_and_never_marked_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'report.json').write_text('{}')
            (out/'claim_review.json').write_text(json.dumps({'status':'error','error':'network'}))
            (out/'evidence_cards.json').write_text(json.dumps({'status':'complete'}))
            self.assertFalse(_catalog_report_complete(out))
            app=ChemExtractorApp(None);app.catalog_task.start('paper.pdf','pdf')
            with patch('chem_pdf_extractor.server._catalog_config',return_value={}), \
                 patch('chem_pdf_extractor.science_skills.ScienceSkills'), \
                 patch('chem_pdf_extractor.sources.load_paper',return_value={'text':'全文'}), \
                 patch('chem_pdf_extractor.biomedical.extract_article',return_value=[]) as extract:
                _run_catalog_pdf(app,Path('paper.pdf'),out)
            extract.assert_called_once()
            self.assertEqual(app.catalog_status()['task']['status'],'failed')
            self.assertIn('原始提取已保存',app.catalog_status()['error'])


class IdentifierTest(unittest.TestCase):
    def test_normalization_allows_only_identifiers(self):
        self.assertEqual(normalize_identifier('https://doi.org/10.1038/s41467-017-00314-z'),'DOI:10.1038/s41467-017-00314-z')
        self.assertEqual(normalize_identifier('123456'),'PMID:123456')
        for bad in ['https://example.com/paper','/tmp/paper.pdf','DOI:10.1234/invalid query']:
            with self.assertRaises(ValueError):normalize_identifier(bad)

    def test_doi_search_is_exact_and_not_filtered_by_aging_keywords(self):
        from chem_pdf_extractor.catalog import search_pubmed
        with tempfile.TemporaryDirectory() as tmp, patch('chem_pdf_extractor.catalog.ScienceSkills') as skills:
            skills.return_value.call.side_effect=[['123'],[{'pmid':'123','title':'Research','doi':'10.1234/test'}]]
            papers=search_pubmed('DOI:10.1234/test',Path(tmp))
            query=skills.return_value.call.call_args_list[0].args[2]
            self.assertEqual(query,'"10.1234/test"[AID]')
            self.assertNotIn('aging',query)
            self.assertEqual(papers[0]['pmid'],'123')


class RelocatedTlsTest(unittest.TestCase):
    def test_context_keeps_peer_and_hostname_verification(self):
        ctx=tls_context()
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreater(ctx.cert_store_stats()['x509_ca'],0)

    def test_explicit_subprocess_ca_is_not_overwritten(self):
        self.assertEqual(subprocess_tls_env({'SSL_CERT_FILE':'custom.pem'})['SSL_CERT_FILE'],'custom.pem')
        self.assertEqual(subprocess_tls_env({'SSL_CERT_DIR':'custom'})['SSL_CERT_DIR'],'custom')
        self.assertTrue(Path(subprocess_tls_env({})['SSL_CERT_FILE']).is_file())

    def test_transient_retry_is_visible_without_echoing_network_error_text(self):
        messages=[]
        error=urllib.error.URLError('private network detail')
        with patch('urllib.request.urlopen',side_effect=error), patch('time.sleep'):
            with self.assertRaises(TransientCloudAPIError):
                cloud_chat_completion('https://api.real-provider.test/v1','fake','model',[],10,retry_count=2,on_retry=messages.append)
        self.assertEqual(len(messages),1)
        self.assertIn('2/2',messages[0])
        self.assertNotIn('private network detail',messages[0])

    def test_certificate_failure_is_actionable_and_not_retried_as_network(self):
        error=urllib.error.URLError(ssl.SSLCertVerificationError('bad CA'))
        with patch('urllib.request.urlopen',side_effect=error) as request, patch('time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'证书校验失败') as exc:
                cloud_chat_completion('https://api.real-provider.test/v1','fake','model',[],10,retry_count=3)
        self.assertNotIsInstance(exc.exception,TransientCloudAPIError)
        request.assert_called_once();sleep.assert_not_called()
