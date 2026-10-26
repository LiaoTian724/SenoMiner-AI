import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chem_pdf_extractor.evidence_cards import card_groups, extract_cards, load_cards, result_location, validate_cards

CLAIM='Piceatannol selectively induced apoptosis in senescent cells versus non-senescent cells.'
SOURCE=('# Abstract\nPiceatannol may be useful against aging.\n# Results\n'+CLAIM+
        '\n# Discussion\nPiceatannol could improve health in humans.\n# Methods\n'
        'HCT116 cells were treated with 10 µM Piceatannol for 24 h. Apoptosis was assessed by Annexin V staining.')
REVIEW={'decisions':[{'canonical_name':'Piceatannol','verdict':'accepted'}]}


def card():
    protocol_quote='HCT116 cells were treated with 10 µM Piceatannol for 24 h.'
    return {'name':'Piceatannol','title':'已诱导衰老细胞的选择性凋亡','study_type':'in_vitro','primary':True,
            'claim_quote':CLAIM,'location':'Results; Figure 2','figure':'Figure 2',
            'protocol':{'model':{'value':'HCT116 cells','quote':protocol_quote},
                        'dose':{'value':'10 µM Piceatannol','quote':protocol_quote},
                        'duration':{'value':'24 h','quote':protocol_quote},
                        'assay':{'value':'Annexin V staining','quote':'Apoptosis was assessed by Annexin V staining.'}},
            'outcomes':[{'quote':CLAIM}]}


class EvidenceCardTests(unittest.TestCase):
    def test_parameters_and_primary_result_are_bound_to_source(self):
        cards=validate_cards({'cards':[card()]},REVIEW,SOURCE)
        self.assertEqual(len(cards),1)
        group=card_groups(cards)[0]
        self.assertEqual(group['model'],'HCT116 cells')
        self.assertIn('10 µM',group['dose'])
        self.assertEqual(group['outcomes'][0]['quote'],CLAIM)
        self.assertEqual(group['outcomes'][0]['assay'],'Annexin V staining')

    def test_invented_protocol_values_are_removed_not_rendered(self):
        c=card();c['protocol']['dose']['value']='1000 µM Piceatannol'
        checked=validate_cards({'cards':[c]},REVIEW,SOURCE)[0]
        self.assertEqual(checked['protocol']['dose']['value'],'')

    def test_paraphrased_model_is_replaced_with_actual_source_description(self):
        c=card();c['protocol']['model']['value']='A summary of colon cancer cells'
        checked=validate_cards({'cards':[c]},REVIEW,SOURCE)[0]
        self.assertEqual(checked['protocol']['model']['value'],c['protocol']['model']['quote'])
        self.assertNotIn('A summary',checked['protocol']['model']['value'])

    def test_a_caption_without_an_experimental_object_is_not_a_model(self):
        c=card();c['protocol']['model']={'value':'HCT116 senescent cells',
                                       'quote':'Specific results for substance X are shown in Fig. 1.'}
        source=SOURCE+'\nSpecific results for substance X are shown in Fig. 1.'
        self.assertEqual(validate_cards({'cards':[c]},REVIEW,source),[])

    def test_identical_short_model_names_do_not_merge_different_cohorts(self):
        first=card();second=copy.deepcopy(first)
        second['figure']='Figure 3'
        second['protocol']['model']['quote']='HCT116 cells were treated with 10 µM Piceatannol for 24 h. '
        self.assertEqual(len(validate_cards({'cards':[first,second]},REVIEW,SOURCE)),2)

    def test_claim_only_without_a_model_or_assay_does_not_become_an_experiment(self):
        for key in ('model','assay'):
            c=card();c['protocol'][key]={'value':'unreported','quote':''}
            self.assertEqual(validate_cards({'cards':[c]},REVIEW,SOURCE),[])

    def test_actual_section_wins_over_model_location(self):
        for quote in ('Piceatannol may be useful against aging.','Piceatannol could improve health in humans.'):
            self.assertEqual(result_location(SOURCE,quote,'Results; Figure 2'),'')
        self.assertEqual(result_location(SOURCE,CLAIM,'Discussion'),'Results')

    def test_cannot_add_a_new_compound_or_a_fabricated_result(self):
        c=card();c['name']='5FU'
        self.assertEqual(validate_cards({'cards':[c]},REVIEW,SOURCE),[])
        c=card();c['outcomes']=[{'quote':'An invented efficacy outcome involving Piceatannol.'}]
        self.assertEqual(validate_cards({'cards':[c]},REVIEW,SOURCE),[])

    def test_same_cohort_multiple_outcomes_stays_one_card(self):
        c=card();c['outcomes']*=3
        cards=validate_cards({'cards':[c,copy.deepcopy(c)]},REVIEW,SOURCE)
        self.assertEqual(len(cards),1)
        self.assertEqual(len(cards[0]['outcomes']),1)

    def test_cached_cards_invalidate_on_source_change_and_errors_are_retryable(self):
        config={'cloud_base_url':'https://example.com/v1','cloud_api_key':'test','cloud_model':'test'}
        with tempfile.TemporaryDirectory() as tmp, patch('chem_pdf_extractor.evidence_cards.cloud_chat_completion',
              side_effect=[RuntimeError('offline'),json.dumps({'cards':[card()]})]) as api:
            folder=Path(tmp)
            self.assertEqual(extract_cards([],SOURCE,REVIEW,config,folder),[])
            self.assertIsNone(load_cards(folder,[],SOURCE,REVIEW))
            self.assertEqual(len(extract_cards([],SOURCE,REVIEW,config,folder)),1)
            self.assertEqual(api.call_count,2)
            self.assertIsNone(load_cards(folder,[],SOURCE+'extra',REVIEW))


if __name__=='__main__':
    unittest.main()
