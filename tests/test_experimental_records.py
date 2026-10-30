import copy
import csv
import io
import unittest

from chem_pdf_extractor.experimental_records import paper_records, filter_records, records_csv
from chem_pdf_extractor.evidence_cards import validate_cards, card_groups
from test_evidence_cards import card, SOURCE, REVIEW


class ExperimentalRecordsTest(unittest.TestCase):
    def paper(self):
        groups=[{'id':'g1','study_type':'in_vitro','model':'HCT116','dose':'20 µM','duration':'48 h',
                 'induction':'5FU 1 µM for 5 days','outcomes':[{'quote':'one'},{'quote':'two'}],
                 'story':{'model':'HCT116','dose':'20 µM','duration':'48 h','result':'cell result'},'protocol_evidence':{}},
                {'id':'g2','study_type':'in_vivo','model':'mouse liver','dose':'100 mg/kg',
                 'story':{'model':'mouse liver','dose':'100 mg/kg','result':'animal result'},'protocol_evidence':{}}]
        return {'id':'paper1','title':'Original paper','pmid':'123','groups':groups,
                'claim_review':{'scope':'senolytic'},'lead_claim':{'group_id':'g1','model':'HCT116',
                'dose':'20 µM','duration':'48 h','induction_agent':'5FU','induction_conditions':'1 µM, 5 days',
                'recovery':'24 h','result':'cell result','quote':'Direct efficacy claim','location':'Results 2'}}

    def test_same_cohort_multiple_outcomes_is_one_record_and_summary_stays_with_its_cohort(self):
        p=self.paper();before=copy.deepcopy(p)
        records=paper_records(p,'Piceatannol',{'cid':'667639'})
        self.assertEqual(len(records),2)
        self.assertEqual(len(records[0]['outcomes']),2)
        self.assertEqual(records[0]['recovery'],'24 h')
        self.assertEqual(records[0]['dose'],'20 µM')
        self.assertEqual(records[0]['induction_agent'],'5FU')
        self.assertEqual(records[1]['recovery'],'')
        self.assertEqual(records[1]['result'],'animal result')
        self.assertEqual(records[1]['source']['title'],'Original paper')
        self.assertEqual(p,before)
        again=paper_records(p,'Alternate chemical alias',{'cid':'667639'})
        self.assertEqual(records[0]['id'],again[0]['id'])

    def test_query_conditions_must_belong_to_one_experiment(self):
        records=paper_records(self.paper(),'Piceatannol',{'cid':'667639'})
        self.assertEqual(len(filter_records(records,'HCT116 20','in_vitro','senolytic')),1)
        self.assertEqual(filter_records(records,'liver 20'),[])
        self.assertEqual(len(filter_records(records,'HCT116 20 μM')),1)
        self.assertEqual(filter_records(records,'HCT116','clinical'),[])
        with self.assertRaises(ValueError):filter_records(records,study_type='unrecognised')

    def test_csv_is_source_linked_formula_safe_and_keeps_missing_fields_empty(self):
        records=paper_records(self.paper(),'=dangerous()',{'cid':'667639'})
        data=records_csv(records)
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['化合物'],"'=dangerous()")
        self.assertEqual(rows[1]['恢复培养'],'')
        self.assertEqual(rows[0]['来源文献'],'Original paper')
        self.assertEqual(rows[0]['PMID'],'123')
        self.assertEqual(rows[0]['PubChem CID'],'667639')
        self.assertEqual(rows[0]['效果原文'],'Direct efficacy claim')

    def test_recovery_and_induction_fields_need_exact_source_evidence(self):
        c=card();quote='5FU was used at 1 µM for 5 days. Cells recovered for 24 h in drug-free medium.'
        source=SOURCE+'\n'+quote
        c['protocol'].update({'induction_agent':{'value':'5FU','quote':quote},
                              'induction_conditions':{'value':'1 µM for 5 days','quote':quote},
                              'recovery':{'value':'24 h','quote':quote}})
        g=card_groups(validate_cards({'cards':[c]},REVIEW,source))[0]
        self.assertEqual(g['recovery'],'24 h')
        self.assertEqual(g['induction_agent'],'5FU')
        self.assertEqual(g['dose'],'10 µM Piceatannol')
        c['protocol']['recovery']['value']='48 h'
        g=card_groups(validate_cards({'cards':[c]},REVIEW,source))[0]
        self.assertEqual(g['recovery'],'')


    def test_different_recovery_conditions_do_not_merge_independent_designs(self):
        first=card();second=copy.deepcopy(first)
        first['protocol']['recovery']={'value':'24 h','quote':'Cells recovered for 24 h.'}
        second['protocol']['recovery']={'value':'48 h','quote':'Cells recovered for 48 h.'}
        source=SOURCE+'\nCells recovered for 24 h.\nCells recovered for 48 h.'
        self.assertEqual(len(validate_cards({'cards':[first,second]},REVIEW,source)),2)
