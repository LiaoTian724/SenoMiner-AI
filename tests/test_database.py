import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from chem_pdf_extractor import catalog
from chem_pdf_extractor.database import database_path, read_catalog, save_catalog, sync_project_output


def example():
    source = {'id': 'paper-a', 'title': '原文论文', 'pmid': '123', 'doi': '10.1234/paper',
              'source_name': 'paper.pdf', 'read_at': '2026-10-28T12:00:00+00:00'}
    record = {'id': 'record-a', 'study_type': 'in_vitro', 'effect_type': 'senolytic',
              'model': 'CCD18Co', 'dose': '20 µM', 'duration': '48 h', 'result': '本篇结果',
              'evidence_quote': 'A literal source quote.', 'evidence_location': 'Results 2; Fig. 2',
              'source': source, 'steps': [{'action': '原文步骤', 'quote': 'Source method.'}],
              'outcomes': [{'quote': 'Source outcome.'}], 'field_evidence': {'dose': {'quote': '20 µM'}}}
    compounds = [{'id': 'combination:1+2', 'name': "A + B's combination", 'identity': {
        'components': [{'name': 'A', 'cid': '1'}, {'name': 'B', 'cid': '2'}]},
        'papers': [{**source, 'groups': [{'id': 'cohort-a'}], 'experiment_records': [record]}]}]
    return {'compounds': compounds, 'papers': [source], 'local_pdfs': [{'name': 'paper.pdf', 'processed': True}],
            'summary': {'compounds': 1, 'papers': 1, 'experiment_groups': 1}}


class DatabaseTests(unittest.TestCase):
    def test_complete_roundtrip_and_sql_columns_keep_combination_source_and_evidence(self):
        data = example()
        before = copy.deepcopy(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_catalog(root, data)
            self.assertEqual(read_catalog(root), before)
            self.assertEqual(data, before)
            with sqlite3.connect(database_path(root)) as db:
                self.assertEqual(db.execute('SELECT name FROM compounds').fetchone()[0], "A + B's combination")
                self.assertEqual(db.execute('SELECT doi FROM papers').fetchone()[0], '10.1234/paper')
                self.assertEqual(db.execute('SELECT model,dose,evidence_quote FROM experiments').fetchone(),
                                 ('CCD18Co', '20 µM', 'A literal source quote.'))
                stored = json.loads(db.execute('SELECT data_json FROM experiments').fetchone()[0])
                self.assertEqual(stored['steps'], data['compounds'][0]['papers'][0]['experiment_records'][0]['steps'])
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_same_record_id_for_different_compounds_and_duplicate_paper_ids_do_not_merge(self):
        data = example()
        other = copy.deepcopy(data['compounds'][0]);other['id'] = 'cid:3';other['name'] = 'Other'
        data['compounds'].insert(0, other)
        data['papers'].append(copy.deepcopy(data['papers'][0]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);save_catalog(root, data)
            self.assertEqual(read_catalog(root), data)
            with sqlite3.connect(database_path(root)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0], 2)

    def test_unchanged_refresh_does_not_rewrite_saved_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);save_catalog(root, example())
            with sqlite3.connect(database_path(root)) as db:
                db.execute("CREATE TRIGGER no_rewrite BEFORE DELETE ON compounds BEGIN SELECT RAISE(ABORT,'rewritten'); END")
            save_catalog(root, example())
            self.assertEqual(read_catalog(root), example())

    def test_failed_update_rolls_back_all_tables_and_the_previous_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);data = example();save_catalog(root, data)
            invalid = copy.deepcopy(data);invalid['papers'][0]['title'] = 'Changed'
            invalid['compounds'].append(copy.deepcopy(invalid['compounds'][0]))
            with self.assertRaises(sqlite3.IntegrityError):save_catalog(root, invalid)
            self.assertEqual(read_catalog(root), data)
            save_catalog(root, data)
            self.assertEqual(read_catalog(root), data)

    def test_changed_snapshot_replaces_stale_results_without_touching_other_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);save_catalog(root, example())
            with sqlite3.connect(database_path(root)) as db:
                db.execute('CREATE TABLE unrelated_notes (note TEXT)');db.execute("INSERT INTO unrelated_notes VALUES ('keep')")
            empty = {'compounds': [], 'papers': [], 'local_pdfs': [], 'summary': {'compounds': 0}}
            save_catalog(root, empty)
            self.assertEqual(read_catalog(root), empty)
            with sqlite3.connect(database_path(root)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT note FROM unrelated_notes').fetchone()[0], 'keep')

    def test_parallel_saves_are_atomic_and_do_not_duplicate_records(self):
        a = example();b = copy.deepcopy(a);b['compounds'][0]['name'] = 'Updated'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda data: save_catalog(root, data), [a, b] * 4))
            saved = read_catalog(root)
            self.assertIn(saved, [a, b])
            with sqlite3.connect(database_path(root)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM compounds').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0], 1)

    def test_existing_catalog_entry_point_saves_without_changing_its_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = catalog.build_catalog(root)
            self.assertTrue(database_path(root).is_file())
            self.assertEqual(read_catalog(root), data)

    def test_extraction_hook_syncs_only_the_current_projects_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('chem_pdf_extractor.config.PROJECT_ROOT', root), patch.object(catalog, 'build_catalog') as build:
                sync_project_output(root / 'output' / 'papers' / 'new-paper')
                build.assert_called_once_with(root)
                sync_project_output(root / 'unrelated-output')
                build.assert_called_once()


if __name__ == '__main__':
    unittest.main()
