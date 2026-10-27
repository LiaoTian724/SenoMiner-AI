import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chem_pdf_extractor import catalog as catalog_module
from chem_pdf_extractor.catalog import build_catalog, local_pdf_output, pubchem_structure
from chem_pdf_extractor.experiment_groups import dose_details, group_paper_records, outcome_kind, study_type
from chem_pdf_extractor.evidence_story import attach_evidence_stories
from chem_pdf_extractor.claim_review import POLICY_VERSION, fingerprint, source_digest, validate_decisions
from chem_pdf_extractor.evidence_cards import CARD_VERSION, _key


def approve_fixture(folder, rows, source):
    source += '\n# Methods\nThe model was treated mice. Detection used microscopy.'
    (folder/'source.md').write_text(source)
    decisions = []
    for row in rows:
        quote = row.get('observed_result') or source
        if not source_span_fixture(source, quote):
            quote = source
        name = row['compound_name']
        decisions.append({'input_name': name, 'verdict': 'accepted', 'role': 'active_intervention',
                          'scope': 'senomorphic', 'effect_direction': 'beneficial_against_aging',
                          'requires_engineered_suicide_gene': False, 'active_components': [name],
                          'evidence_quote': quote, 'evidence_location': 'Results',
                          'supported_records': [{'experiment_id': row['experiment_id'], 'result_quote': quote}]})
    review = {'policy_version': POLICY_VERSION, 'source_sha256': source_digest(source),
              'records_sha256': fingerprint(rows), 'status': 'complete',
              'decisions': validate_decisions({'decisions': decisions}, rows, source)}
    (folder/'claim_review.json').write_text(json.dumps(review))
    cards=[]
    for d in review['decisions']:
        if d['verdict']!='accepted':continue
        quote=d['evidence_quote']
        cards.append({'name':d['canonical_name'],'claim_quote':quote,'location':'Results; Figure 1',
                      'title':'已核对实验','study_type':'in_vivo','primary':True,
                      'protocol':{'model':{'value':'treated mice','quote':'The model was treated mice.'},
                                  'assay':{'value':'microscopy','quote':'Detection used microscopy.'}},
                      'outcomes':[{'quote':quote}]})
    (folder/'evidence_cards.json').write_text(json.dumps({'version':CARD_VERSION,'source_sha256':source_digest(source),
        'records_sha256':fingerprint(rows),'review_key':_key(review),'status':'complete','raw':{'cards':cards}}))


def source_span_fixture(source, quote):
    from chem_pdf_extractor.validation import source_span
    return source_span(source, quote)


class CatalogTest(unittest.TestCase):
    def test_drug_class_is_not_a_compound_but_specific_names_without_cid_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'output'/'paper';folder.mkdir(parents=True)
            source='17-DMAG selectively killed senescent cells. HSP90 inhibitors selectively killed senescent cells.'
            rows=[{'compound_name':name,'experiment_id':name,'observed_result':quote}
                  for name,quote in [('17-DMAG','17-DMAG selectively killed senescent cells.'),
                                     ('HSP90 inhibitors','HSP90 inhibitors selectively killed senescent cells.')]]
            (folder/'report.json').write_text(json.dumps({'source':{'source':'paper.pdf'},'records':rows}))
            approve_fixture(folder,rows,source)
            names=[c['name'] for c in build_catalog(root)['compounds']]
            self.assertEqual(names,['17-DMAG'])
            self.assertEqual(len(json.loads((folder/'report.json').read_text())['records']),2)

    def test_pct_reading_steps_require_same_paper_cohort_and_source_facts(self):
        quote = 'PCT selectively targets the senescent population for elimination'
        source = '\n'.join([
            quote,
            'Cells were exposed to 1 µM 5FU for 5 consecutive days. After 24 h of recovery in drug-free medium, cells were treated with 20 µM PCT for an additional 48 h.',
            'Annexin V staining revealed a significant increase in early apoptosis in CCD and HCT116 cells that had been rendered senescent by 5FU',
            'CCK8 viability assay shows that PCT significantly reduces viability in 5FU-primed CCD18Co and HCT116 cells',
            'In contrast, non-senescent populations and HT29 cells, which do not strongly undergo senescence, were minimally affected',
            'Immunocytochemical co-staining with SA-β -galactosidase confirmed that apoptotic cells were predominantly senescent',
        ])
        for doi, kind, text, expected in [
            ('10.3390/ijms26189134', 'in_vitro', source, True),
            ('10.3390/ijms26189134', 'in_vitro', source.replace('24 h', '48 h'), False),
            ('10.3390/other', 'in_vitro', source, False),
            ('10.3390/ijms26189134', 'in_vivo', source, False),
        ]:
            with self.subTest(doi=doi, kind=kind, source=text):
                paper = {'doi': doi, 'groups': [{'id': 'pct-cell', 'study_type': kind,
                    'outcomes': [{'quote': quote, 'result': quote}], 'steps': []}]}
                attach_evidence_stories(paper, 'Piceatannol', text)
                self.assertEqual(bool(paper['lead_claim'].get('reading_steps')), expected)
                if expected:
                    self.assertIn('24 小时', paper['lead_claim']['reading_steps'][2])
                    self.assertIn('诱导细胞衰老', paper['lead_claim']['reading_steps'][1])
                    self.assertIn('Piceatannol', paper['lead_claim']['reading_steps'][3])

    def test_story_leads_with_verified_claim_and_one_cohort(self):
        quote = "D + Q significantly reduced (p = 0·001) adipose tissue p16 [INK4A+] cells. Raw values were reduced by 35%"
        source = "# Results\n" + quote + " (Fig. 1a)."
        outcome = {"quote": quote, "result": "p16 decreased by 35%", "endpoint": "p16", "assay": "immunohistochemistry",
                   "sample_size": "n=9", "outcome_kind": "衰老相关标志物；不等同于细胞清除"}
        paper = {"pmid": "31542391", "groups": [{"id": "cohort", "title": "人体临床给药", "study_type": "clinical",
                  "outcomes": [outcome, {**outcome, "endpoint": "p21"}], "steps": [{"action": str(i)} for i in range(10)]}]}
        attach_evidence_stories(paper, "Dasatinib + Quercetin", source)
        self.assertIn("35%", paper["lead_claim"]["quote"])
        self.assertEqual(paper["lead_claim"]["group_id"], "cohort")
        self.assertEqual(paper["groups"][0]["story"]["other_outcomes"], 1)
        self.assertLessEqual(len(paper["groups"][0]["story"]["steps"]), 3)

    def test_paper_specific_claim_is_not_assigned_to_another_compound(self):
        abt_quote = 'ABT263 treatment cleared SCs in normally aged mice.'
        combo_quote = 'The combination of ABT199 and WEHI539 selectively killed SCs.'
        paper = {'pmid': '26657143', 'groups': [{'id': 'combo', 'cohort_key': 'fig2-apoptosis',
                 'title': 'Figure 2', 'study_type': 'in_vitro', 'outcomes': [{'quote': combo_quote,
                 'result': combo_quote, 'outcome_kind': '细胞死亡／凋亡'}], 'steps': []}]}
        attach_evidence_stories(paper, 'ABT199 + WEHI539', abt_quote + '\n' + combo_quote)
        self.assertEqual(paper['lead_claim']['quote'], combo_quote)

    def test_paper_specific_claim_is_not_assigned_to_a_different_cohort(self):
        aged='Similarly to its effects in TBI-treated mice, ABT263 treatment cleared SCs in normally aged mice (Fig. 4a).'
        cell='ABT263 selectively killed senescent WI-38 cells in culture.'
        paper={'pmid':'26657143','groups':[{'id':'cells','figure':'1','study_type':'in_vitro',
               'outcomes':[{'quote':cell,'result':cell,'outcome_kind':'细胞死亡／凋亡'}],'steps':[]}]}
        attach_evidence_stories(paper,'ABT263',aged+'\n'+cell)
        self.assertEqual(paper['lead_claim']['quote'],cell)

    def test_only_own_positive_findings_enter_compound_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "output" / "paper-one"
            folder.mkdir(parents=True)
            text = "# Results\nFisetin improved senescent cell clearance in treated mice.\n"
            (folder / "source.md").write_text(text)
            quote = "Fisetin improved senescent cell clearance in treated mice."
            def row(name, origin, location, effect="positive", basis="direct_experiment"):
                return {"compound_name": name, "record_type": "chemical_candidate",
                        "experiment_id": 'test-' + name,
                        "compound_role": "tested", "evidence_origin": origin,
                        "source_location": location, "reported_effect": effect,
                        "claim_basis": basis, "experiment_model": "treated mice",
                        "observed_result": quote,
                        "field_evidence": json.dumps({"observed_result": quote}),
                        "evidence_checks": "{}", "needs_review": True}
            rows = [row("Fisetin", "original_experiment", "Results, Fig. 1"),
                    row("Navitoclax", "cited_experiment", "Results, Fig. 1"),
                    row("Dasatinib", "original_experiment", "Discussion"),
                    row("Quercetin", "original_experiment", "Results", effect="no_effect")]
            (folder / "report.json").write_text(json.dumps({"source": {"source": "paper-one.pdf"},
                                                            "source_sha256": "paper-one", "records": rows}))
            approve_fixture(folder, rows, text)
            catalog = build_catalog(root)
            self.assertEqual(catalog["summary"], {"compounds": 1, "papers": 1,
                                                   "direct": 1, "experiment_groups": 1, "outcomes": 1})
            self.assertEqual(catalog["compounds"][0]["name"], "Fisetin")
            self.assertTrue(catalog["compounds"][0]["papers"][0]["groups"][0]["outcomes"][0]["quote_matched"])

    def test_invalid_cid_is_rejected_before_network(self):
        with self.assertRaises(ValueError):
            pubchem_structure("../secret")

    def test_pubchem_3d_uses_local_sdf_cache_when_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "output" / ".structure_cache"
            folder.mkdir(parents=True)
            from rdkit import Chem
            from rdkit.Chem import AllChem
            mol=Chem.AddHs(Chem.MolFromSmiles('CO'))
            AllChem.EmbedMolecule(mol,randomSeed=42)
            sdf=Chem.MolToMolBlock(mol).replace('RDKit','PubChem')
            (folder / "5281614.sdf").write_text(sdf)
            with patch.object(catalog_module, "PROJECT_ROOT", Path(tmp)), patch.object(
                catalog_module.urllib.request, "urlopen", side_effect=AssertionError("network used")
            ):
                pubchem_structure.cache_clear()
                self.assertEqual(pubchem_structure("5281614"), sdf)
                pubchem_structure.cache_clear()

    def test_weak_screening_activity_is_not_promoted_to_effective(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "output" / "weak-screen"
            folder.mkdir(parents=True)
            quote = "Luteolin and curcumin also showed weak activity."
            (folder / "source.md").write_text("# Results\n" + quote)
            (folder / "report.json").write_text(json.dumps({
                "source": {"source": "screen.pdf"}, "records": [
                    {"compound_name": "luteolin", "record_type": "chemical_candidate",
                     "compound_role": "tested", "evidence_origin": "original_experiment",
                     "source_location": "Results; Fig. 1", "reported_effect": "positive",
                     "observed_result": "Luteolin showed weak activity.",
                     "field_evidence": {"observed_result": quote}}]}))
            self.assertEqual(build_catalog(root)["summary"]["compounds"], 0)

    def test_abstract_summary_and_unmatched_result_are_not_direct_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "output" / "paper"
            folder.mkdir(parents=True)
            quote = "Fisetin reduced senescent cells in treated mice."
            (folder / "source.md").write_text("# Results\n" + quote)
            def row(location, result_quote):
                return {"compound_name": "Fisetin", "record_type": "chemical_candidate",
                        "compound_role": "tested", "evidence_origin": "original_experiment",
                        "reported_effect": "positive", "source_location": location,
                        "field_evidence": {"observed_result": result_quote}}
            (folder / "report.json").write_text(json.dumps({
                "source": {"source": "paper.pdf"}, "records": [
                    row("Methods; Findings", quote),
                    row("Results; Fig. 1", "Unsupported positive claim")]}))
            self.assertEqual(build_catalog(root)["summary"]["compounds"], 0)

    def test_reviewed_report_can_be_used_without_overwriting_raw_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'output' / 'paper'
            folder.mkdir(parents=True)
            quote = 'ABT263 treatment significantly improved aged stem cell function.'
            (folder / 'source.md').write_text('# Results\n' + quote)
            source = {'source': 'PMID:26657143', 'pmid': '26657143'}
            raw = {'source': source, 'source_sha256': 'same-paper', 'records': []}
            (folder / 'report.json').write_text(json.dumps(raw))
            positive = {'compound_name': 'ABT263', 'record_type': 'chemical_candidate',
                        'experiment_id': 'test-abt',
                        'compound_role': 'tested', 'evidence_origin': 'original_experiment',
                        'claim_basis': 'direct_experiment', 'reported_effect': 'positive',
                        'source_location': 'Results; Figure 4', 'observed_result': quote,
                        'field_evidence': {'observed_result': quote}}
            reviewed = {**raw, 'derived_from': 'report.json', 'records': [positive]}
            (folder / 'report.revalidated.json').write_text(json.dumps(reviewed))
            approve_fixture(folder, [positive], '# Results\n' + quote)
            self.assertEqual(build_catalog(root)['summary']['compounds'], 1)
            self.assertEqual(json.loads((folder / 'report.json').read_text())['records'], [])

    def test_gcv_transgene_ablation_control_is_not_senolytic_catalog_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'output' / 'paper'
            folder.mkdir(parents=True)
            quote = 'GCV reduced senescent cells in p16-3MR mice.'
            (folder / 'source.md').write_text('HSV-TK p16-3MR Results\n' + quote)
            (folder / 'report.json').write_text(json.dumps({'source': {'source': 'PMID:26657143'},
                'records': [{'compound_name': 'GCV', 'record_type': 'chemical_candidate',
                             'compound_role': 'tested', 'evidence_origin': 'original_experiment',
                             'claim_basis': 'direct_experiment', 'reported_effect': 'positive',
                             'source_location': 'Results; Figure 3', 'observed_result': quote,
                             'field_evidence': {'observed_result': quote}}]}))
            self.assertEqual(build_catalog(root)['summary']['compounds'], 0)

    def test_explicit_paper_conclusion_without_experiment_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "output" / "paper-two"
            folder.mkdir(parents=True)
            quote = "Compound Z may reduce senescent cells."
            (folder / "source.md").write_text("# Conclusions\n" + quote)
            (folder / "report.json").write_text(json.dumps({
                "source": {"source": "paper-two.pdf"}, "source_sha256": "paper-two",
                "records": [{"compound_name": "Compound Z", "record_type": "background_mention",
                             "compound_role": "mentioned", "evidence_origin": "background",
                             "claim_basis": "conclusion_only", "reported_effect": "positive",
                             "source_location": "Conclusions", "observed_result": quote,
                             "field_evidence": json.dumps({"observed_result": quote})}]}))
            catalog = build_catalog(root)
            self.assertEqual(catalog["summary"]["compounds"], 0)

    def test_ellipsis_quote_recovers_only_literal_source_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'output'/'fisetin';folder.mkdir(parents=True)
            source='Dietary fisetin suppressed the luciferase signal of reporter mice significantly (Fig. 2A-B).'
            (folder/'source.md').write_text(source)
            (folder/'report.json').write_text(json.dumps({'source':{'source':'PMID:30279143','pmid':'30279143'},'records':[
                {'compound_name':'fisetin','experiment_id':'test-fisetin','record_type':'chemical_candidate','compound_role':'tested',
                 'evidence_origin':'original_experiment','claim_basis':'direct_experiment','reported_effect':'positive',
                 'source_location':'Results; Fig. 2','field_evidence':{'observed_result':'Dietary fisetin suppressed the luciferase signal ... significantly'},
                 'observed_result':'Dietary fisetin suppressed the luciferase signal significantly.'}]}))
            rows=json.loads((folder/'report.json').read_text())['records']
            approve_fixture(folder, rows, source)
            c=build_catalog(root)
            self.assertEqual(c['summary']['compounds'],1)
            self.assertIn('Dietary fisetin suppressed the luciferase signal',c['compounds'][0]['papers'][0]['groups'][0]['outcomes'][0]['quote'])

    def test_grouping_keeps_distinct_cohorts_and_merges_duplicate_outcome(self):
        base={'model':'human adipose explants','model_type':'ex_vivo','dose':'20 μM','location':'Fig. 4E-F',
              'quote':'Fisetin reduced SA-beta-gal and IL-6.','steps':[]}
        rows=[dict(base,id='one',sample_size='n=3',control='vehicle'),
              dict(base,id='two',sample_size='',control=''),
              dict(base,id='mouse',model='aged WT mice',model_type='in_vivo',dose='100 mg/kg',location='Fig. 4A',quote='Fisetin reduced mouse markers.')]
        groups=group_paper_records(rows,'30279143')
        self.assertEqual(len(groups),2)
        human=next(g for g in groups if g['study_type']=='ex_vivo')
        self.assertEqual(len(human['outcomes']),1)
        self.assertEqual(set(human['outcomes'][0]['source_record_ids']),{'one','two'})
        self.assertEqual(human['outcomes'][0]['sample_size'],'n=3')

    def test_feed_concentration_is_not_body_weight_dose(self):
        feed=dose_details({'dose':'500 ppm (500 mg/kg) fisetin','model_type':'in_vivo'})
        gavage=dose_details({'dose':'100 mg/kg','route':'oral gavage','model_type':'in_vivo'})
        self.assertIn('每千克饲料',feed['dose'])
        self.assertIn('不是每千克体重',feed['basis'])
        self.assertEqual(gavage['basis'],'每千克体重')

    def test_marker_change_without_cell_killing_is_not_senolytic_proof(self):
        self.assertEqual(outcome_kind({'result': 'Fisetin reduced SA-β-gal without evidence of cell killing.'}),
                         '衰老相关标志物；不等同于细胞清除')

    def test_clinical_biopsy_is_distinct_from_ex_vivo_explant(self):
        self.assertEqual(study_type({'model_type': 'clinical', 'model': 'adipose explant biopsy after oral treatment'}),
                         'clinical')
        self.assertEqual(study_type({'model': 'adipose explant resected before in-dish treatment'}), 'ex_vivo')

    def test_local_pdf_output_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            local_pdf_output("../paper.pdf")
        self.assertEqual(local_pdf_output("study.pdf", Path("/tmp")).parent,
                         Path("/tmp/output/papers"))


if __name__ == "__main__":
    unittest.main()
