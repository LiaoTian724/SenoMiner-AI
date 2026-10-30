import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    obj = importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

launch = module('windows_launcher')
package = module('build_windows_bundle')


class WindowsLauncherTest(unittest.TestCase):
    def root(self, tmp):
        root = Path(tmp) / '中文项目 with spaces & signs';root.mkdir()
        (root / 'requirements-windows.txt').write_text('rdkit==2026.9.1\n')
        (root / 'requirements.lock').write_text('rdkit==2026.9.1\n')
        return root.resolve()

    def runner(self, calls, fail=None):
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[1] == 'create':
                prefix = Path(argv[argv.index('--prefix') + 1]);prefix.mkdir(parents=True)
                (prefix / 'python.exe').touch()
            if fail and fail(argv):raise subprocess.CalledProcessError(1, argv)
        return run

    def test_first_setup_pins_versions_uses_windows_prefix_and_preserves_mac_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.root(tmp);mac = root / '.conda' / 'SenoMiner_AI';mac.mkdir(parents=True)
            (mac / 'marker').write_text('keep')
            calls=[];prefix=launch.prepare_environment(root,Path('conda.exe'),run=self.runner(calls))
            self.assertEqual(prefix, root / '.conda' / 'win-64' / 'SenoMiner_AI')
            self.assertIn('python=3.11.15',calls[0][0]);self.assertIn('sqlite=3.51.2',calls[0][0])
            self.assertEqual(calls[0][0][calls[0][0].index('--platform')+1],'win-64')
            self.assertIn('--only-binary=:all:',calls[1][0])
            self.assertEqual((mac / 'marker').read_text(),'keep')
            self.assertTrue((prefix / '.senominer-windows-ready.json').is_file())
            self.assertTrue(all(k['check'] and k['cwd']==str(root) for _,k in calls))

    def test_next_launch_checks_existing_environment_without_reinstalling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp);calls=[];run=self.runner(calls)
            launch.prepare_environment(root,Path('conda.exe'),run=run);calls.clear()
            launch.prepare_environment(root,Path('conda.exe'),run=run)
            self.assertEqual(len(calls),1);self.assertIn('-c',calls[0][0])
            (root/'requirements-windows.txt').write_text('changed')
            calls.clear();launch.prepare_environment(root,Path('conda.exe'),run=run)
            self.assertEqual(len(calls),2);self.assertIn('pip',calls[0][0])

    def test_failed_check_does_not_mark_environment_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp);calls=[]
            with self.assertRaises(subprocess.CalledProcessError):
                launch.prepare_environment(root,Path('conda.exe'),run=self.runner(calls,lambda a:a[-2]=='-c'))
            self.assertEqual(len(calls),3)
            self.assertFalse((launch.environment_path(root)/'.senominer-windows-ready.json').exists())

    def test_command_arguments_preserve_paths_and_conda_activation(self):
        command=launch.conda_run(Path('Conda Folder/conda.exe'),Path('项目 & data/SenoMiner_AI'),'python.exe','script with spaces.py')
        self.assertEqual(command[-1],'script with spaces.py')
        self.assertIn('--no-capture-output',command)
        self.assertEqual(command[command.index('--prefix')+1],'项目 & data/SenoMiner_AI')

    def test_env_template_is_created_only_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.env.example').write_text('ARK_API_KEY=template')
            self.assertTrue(launch.ensure_local_config(root))
            (root/'.env').write_text('ARK_API_KEY=existing')
            self.assertFalse(launch.ensure_local_config(root));self.assertIn('existing',(root/'.env').read_text())

    def test_bundle_excludes_keys_environments_and_logs_but_keeps_database_and_reports(self):
        import sqlite3,zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source';root.mkdir()
            for rel,content in [('README.md','read me'),('.env','secret'),('.env.example','template'),
                ('output/papers/p/source.md','source'),('output/papers/p/report.json','{}'),
                ('output/papers/p/model.key','secret'),('chem_pdf_extractor/__pycache__/x.pyc','cache'),
                ('chem_pdf_extractor/test.py','code'),('.conda/env/marker','env'),('logs/task.log','log')]:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
            with sqlite3.connect(root/'output/results.sqlite3') as db:
                db.execute('CREATE TABLE test (value TEXT)');db.execute("INSERT INTO test VALUES ('preserved')")
            target=Path(tmp)/'bundle.zip';package.build_bundle(root,target)
            with zipfile.ZipFile(target) as z:
                names=z.namelist();self.assertIn('SenoMiner-AI/output/results.sqlite3',names)
                self.assertIn('SenoMiner-AI/output/papers/p/report.json',names)
                self.assertIn('SenoMiner-AI/.env.example',names)
                self.assertFalse(any(x.endswith('/.env') or '.conda/' in x or '__pycache__' in x or x.endswith('.key') or 'logs/' in x for x in names))
                copied=Path(tmp)/'saved.sqlite3';copied.write_bytes(z.read('SenoMiner-AI/output/results.sqlite3'))
            with sqlite3.connect(copied) as db:self.assertEqual(db.execute('SELECT value FROM test').fetchone()[0],'preserved')


if __name__ == '__main__':unittest.main()
