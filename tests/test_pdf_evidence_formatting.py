"""Regression cases for source evidence lost in PDF-to-Markdown formatting."""
import json
import tempfile
import unittest
from pathlib import Path

from chem_pdf_extractor.validation import source_span
from chem_pdf_extractor.claim_review import validate_decisions, fingerprint, source_digest, POLICY_VERSION
from chem_pdf_extractor.evidence_cards import CARD_VERSION, _key
from chem_pdf_extractor.server import _catalog_completion_message
from chem_pdf_extractor.catalog_progress import CatalogProgress


class PdfEvidenceFormattingTests(unittest.TestCase):
    def test_italics_keep_original_offsets_and_do_not_change_numbers(self):
        source = '# Results\nVoclosporin extended the lifespan of _C. elegans_ by 19.1%.'
        quote = 'Voclosporin extended the lifespan of C. elegans by 19.1%.'
        span = source_span(source, quote)
        self.assertIsNotNone(span)
        self.assertEqual(source[span['start']:span['end']], span['text'])
        self.assertIsNone(source_span(source, quote.replace('19.1%', '91.1%')))
        self.assertIsNone(source_span(source, quote.replace('extended', 'reduced')))

    def test_page_furniture_can_interrupt_one_continuous_result_sentence(self):
        source = ('_Molecules_ **2025**, _30_, 2653 12 of 27\n'
                  '# Results\nPanaxatriol cleared 45% of senescent cells and 12% of\n\n'
                  '_Molecules_ **2025**, _30_, 2653 13 of 27\n\nproliferating cells.')
        quote = 'Panaxatriol cleared 45% of senescent cells and 12% of proliferating cells.'
        span = source_span(source, quote)
        self.assertIsNotNone(span)
        self.assertEqual(source[span['start']:span['end']], span['text'])
        self.assertIn('13 of 27', span['text'])

    def test_never_skips_a_negative_sentence_or_unconfirmed_header(self):
        for middle in ('It did not selectively kill senescent cells.',
                       'Molecules 2025, 30, 2653 13 of 27'):
            source = 'Panaxatriol cleared cells.\n'+middle+'\nVoclosporin extended lifespan.'
            self.assertIsNone(source_span(source, 'Panaxatriol cleared cells. Voclosporin extended lifespan.'))

    def test_chemical_identifiers_and_unpaired_markers_are_preserved(self):
        self.assertIsNone(source_span('drug_A extended lifespan.', 'drugA extended lifespan.'))
        self.assertIsNone(source_span('A * B increased.', 'A B increased.'))

    def test_formatting_correction_accepts_only_the_active_drug(self):
        quote = 'Voclosporin extended the lifespan of C. elegans by 19.1%.'
        source = '# Results\nVoclosporin extended the lifespan of _C. elegans_ by 19.1%. Metformin was the control.'
        rows = [{'experiment_id': 'one', 'compound_name': 'Voclosporin'},
                {'experiment_id': 'two', 'compound_name': 'Metformin'}]
        d = {'input_name': 'Voclosporin', 'verdict': 'accepted', 'role': 'active_intervention',
             'scope': 'lifespan', 'effect_direction': 'beneficial_against_aging',
             'requires_engineered_suicide_gene': False, 'active_components': ['Voclosporin'],
             'evidence_quote': quote, 'supported_records': [{'experiment_id': 'one', 'result_quote': quote}]}
        checked = validate_decisions({'decisions': [d]}, rows, source)
        self.assertEqual(checked[0]['verdict'], 'accepted')
        self.assertNotEqual(checked[1]['verdict'], 'accepted')

    def test_zero_records_message_distinguishes_validation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = '# Results\nA paper without validated experimental evidence.'
            (folder/'source.md').write_text(source)
            (folder/'report.json').write_text(json.dumps({'records': []}))
            review = {'policy_version': POLICY_VERSION, 'source_sha256': source_digest(source),
                      'records_sha256': fingerprint([]), 'status': 'complete', 'raw_decisions': []}
            # With no eligible candidates this is a genuine zero result.
            (folder/'claim_review.json').write_text(json.dumps(review))
            (folder/'evidence_cards.json').write_text(json.dumps({'version': CARD_VERSION,
                'source_sha256': source_digest(source), 'records_sha256': fingerprint([]),
                'review_key': _key(review), 'status': 'complete', 'raw': {'cards': []}}))
            self.assertIn('未找到符合收录条件', _catalog_completion_message(folder))
            # An ungrounded accepted claim must instead be shown as needing review.
            rows = [{'compound_name': 'Drug', 'experiment_id': 'one'}]
            (folder/'report.json').write_text(json.dumps({'records': rows}))
            review['records_sha256'] = fingerprint(rows)
            (folder/'claim_review.json').write_text(json.dumps(review))
            saved = json.loads((folder/'evidence_cards.json').read_text())
            saved['records_sha256'] = fingerprint(rows)
            (folder/'evidence_cards.json').write_text(json.dumps(saved))
            self.assertIn('原文证据未通过核对', _catalog_completion_message(folder))

    def test_progress_retains_specific_completion_message(self):
        progress = CatalogProgress(); progress.start('paper.pdf', 'pdf')
        progress.finish(message='提取完成：收录 2 个化合物、2 组实验。')
        self.assertIn('2 个化合物', progress.snapshot()['message'])
        progress.start('paper.pdf', 'pdf'); progress.finish('failed', message='success')
        self.assertEqual(progress.snapshot()['message'], 'failed')
