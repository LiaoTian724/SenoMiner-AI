import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chem_pdf_extractor.claim_review import (
    POLICY_VERSION, approved_records, fingerprint, load_review, review_rows, source_digest, validate_decisions,
)
from chem_pdf_extractor.catalog import build_catalog
from chem_pdf_extractor.evidence_cards import CARD_VERSION, _key


SOURCE = ('# Results\n5FU treatment induced a strong senescent phenotype. '
          'Piceatannol selectively killed senescent cells relative to non-senescent controls. '
          'Abemaciclib followed by LLOMe reduced breast cancer cell viability. '
          'Ganciclovir cleared cells expressing the engineered HSV-TK suicide gene.')
QUOTE = 'Piceatannol selectively killed senescent cells relative to non-senescent controls.'


def row(name='Piceatannol', identity='exp-one', quote=QUOTE):
    return {'experiment_id': identity, 'compound_name': name, 'record_type': 'chemical_candidate',
            'evidence_origin': 'original_experiment', 'claim_basis': 'direct_experiment',
            'compound_role': 'tested', 'reported_effect': 'positive', 'source_location': 'Results; Fig. 1',
            'observed_result': quote, 'field_evidence': {'observed_result': quote}}


def decision(name='Piceatannol', identity='exp-one', quote=QUOTE, **overrides):
    return {'input_name': name, 'verdict': 'accepted', 'role': 'active_intervention',
            'scope': 'senolytic', 'effect_direction': 'beneficial_against_aging',
            'requires_engineered_suicide_gene': False, 'active_components': [name],
            'evidence_quote': quote, 'evidence_location': 'Results',
            'supported_records': [{'experiment_id': identity, 'result_quote': quote}], **overrides}


def save_review(folder, rows, source, decisions):
    review = {'policy_version': POLICY_VERSION, 'source_sha256': source_digest(source),
              'records_sha256': fingerprint(rows), 'status': 'complete',
              'decisions': validate_decisions({'decisions': decisions}, rows, source)}
    (folder/'claim_review.json').write_text(json.dumps(review))
    return review


class ClaimReviewTests(unittest.TestCase):
    def test_positive_change_is_not_benefit_against_senescence(self):
        quote = '5FU treatment induced a strong senescent phenotype.'
        result = validate_decisions({'decisions': [decision('5FU', quote=quote, effect_direction='promotes_senescence')]},
                                    [row('5FU', quote=quote)], SOURCE)
        self.assertNotEqual(result[0]['verdict'], 'accepted')

    def test_cancer_killing_and_sequence_are_not_antiaging_entities(self):
        quote = 'Abemaciclib followed by LLOMe reduced breast cancer cell viability.'
        for scope in ('cancer_only', 'senolytic'):
            with self.subTest(scope=scope):
                name = 'Abemaciclib followed by LLOMe'
                result = validate_decisions({'decisions': [decision(name, quote=quote, scope=scope,
                                                                   active_components=['Abemaciclib','LLOMe'])]},
                                            [row(name, quote=quote)], SOURCE)
                self.assertNotEqual(result[0]['verdict'], 'accepted')

    def test_suicide_transgene_ablation_control_is_rejected(self):
        quote = 'Ganciclovir cleared cells expressing the engineered HSV-TK suicide gene.'
        d = decision('Ganciclovir', quote=quote, requires_engineered_suicide_gene=True)
        self.assertNotEqual(validate_decisions({'decisions': [d]}, [row('Ganciclovir', quote=quote)], SOURCE)[0]['verdict'], 'accepted')

    def test_each_claim_and_accepted_record_must_have_literal_evidence(self):
        for change in ({'evidence_quote': 'An invented positive sentence describing Piceatannol efficacy.'},
                       {'active_components': ['A fabricated chemical']},
                       {'supported_records': [{'experiment_id': 'other', 'result_quote': QUOTE}]},
                       {'supported_records': [{'experiment_id': 'exp-one', 'result_quote': 'p<0.001'}]},
                       {'requires_engineered_suicide_gene': None}):
            with self.subTest(change=change):
                d = decision(**change)
                self.assertNotEqual(validate_decisions({'decisions': [d]}, [row()], SOURCE)[0]['verdict'], 'accepted')

    def test_conflicting_or_missing_decisions_fail_closed(self):
        for payload in ({}, {'decisions':[decision(),decision(active_components=['5FU'])]}):
            self.assertEqual(approved_records({'decisions':validate_decisions(payload,[row()],SOURCE)}), {})

    def test_multiple_effect_scopes_for_same_drug_merge_only_valid_records(self):
        rows=[row(),row(identity='exp-two'),row(identity='methods-only')]
        payload={'decisions':[decision(),decision(identity='exp-two',scope='lifespan'),
                              decision(identity='methods-only',verdict='rejected',role='mechanistic_probe')]}
        reviewed=validate_decisions(payload,rows,SOURCE)
        self.assertEqual(reviewed[0]['scope'],'lifespan')
        self.assertEqual(set(approved_records({'decisions':reviewed})),{'exp-one','exp-two'})

    def test_review_does_not_transfer_evidence_to_another_input_or_experiment(self):
        rows = [row(), row('5FU', 'exp-induction')]
        decisions = validate_decisions({'decisions':[decision(supported_records=[
            {'experiment_id':'exp-induction','result_quote':QUOTE}])]}, rows, SOURCE)
        self.assertEqual(approved_records({'decisions':decisions}), {})

    def test_review_invalidates_when_source_or_records_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            save_review(folder, [row()], SOURCE, [decision()])
            self.assertTrue(load_review(folder,[row()],SOURCE))
            self.assertFalse(load_review(folder,[row()],SOURCE+' added text'))
            self.assertFalse(load_review(folder,[row(quote='a changed result')],SOURCE))

    def test_review_error_does_not_accept_and_is_retryable(self):
        config = {'cloud_base_url':'https://example.com/v1','cloud_api_key':'test','cloud_model':'test'}
        with tempfile.TemporaryDirectory() as tmp, patch('chem_pdf_extractor.claim_review.cloud_chat_completion',
                                                       side_effect=[RuntimeError('offline'),json.dumps({'decisions':[decision()]})]) as api:
            first=review_rows([row()], SOURCE, config, Path(tmp))
            self.assertEqual(first['status'],'error')
            second=review_rows([row()], SOURCE, config, Path(tmp))
            self.assertEqual(second['status'],'complete')
            self.assertEqual(api.call_count,2)
            self.assertTrue(approved_records(second))

    def test_catalog_requires_review_and_uses_read_order_not_alphabet_or_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for directory,name,read_at,mtime in [('a-old','Piceatannol','2026-10-24T01:00:00+00:00',200),
                                                 ('z-new','Fisetin','2026-10-26T01:00:00+00:00',100)]:
                folder=root/'output'/directory;folder.mkdir(parents=True)
                quote=f'{name} selectively killed senescent cells relative to non-senescent controls.'
                r=row(name,identity='exp-'+name,quote=quote)
                (folder/'source.md').write_text(quote)
                path=folder/'report.json';path.write_text(json.dumps({'source':{'source':directory+'.pdf','title':directory},
                        'source_sha256':directory,'read_at':read_at,'records':[r]}))
                os.utime(path,(mtime,mtime))
            self.assertEqual(build_catalog(root)['compounds'],[])
            for folder in (root/'output').iterdir():
                report=json.loads((folder/'report.json').read_text());r=report['records'][0];quote=r['observed_result']
                source=quote+'\n# Methods\nThe assay was cell viability.'
                (folder/'source.md').write_text(source)
                review=save_review(folder,[r],source,[decision(r['compound_name'],r['experiment_id'],quote)])
                card={'name':review['decisions'][0]['canonical_name'],'claim_quote':quote,'location':'Results; Figure 1',
                      'title':'实验','study_type':'in_vitro','protocol':{
                          'model':{'value':'senescent cells','quote':quote},
                          'assay':{'value':'cell viability','quote':'The assay was cell viability.'}},'outcomes':[{'quote':quote}]}
                (folder/'evidence_cards.json').write_text(json.dumps({'version':CARD_VERSION,'source_sha256':source_digest(source),
                    'records_sha256':fingerprint([r]),'review_key':_key(review),'status':'complete','raw':{'cards':[card]}}))
            result=build_catalog(root)
            self.assertEqual([c['name'] for c in result['compounds']],['Fisetin','Piceatannol'])
            self.assertEqual(result['papers'][0]['title'],'z-new')

    def test_true_combination_is_retained_as_combination(self):
        quote='Dasatinib and Quercetin together reduced senescent cells in treated patients.'
        r=row('D+Q',quote=quote)
        d=decision('D+Q',quote=quote,active_components=['Dasatinib','Quercetin'])
        result=validate_decisions({'decisions':[d]},[r],quote)
        self.assertEqual(result[0]['canonical_name'],'Dasatinib + Quercetin')
        self.assertEqual(result[0]['verdict'],'accepted')


if __name__=='__main__':
    unittest.main()
