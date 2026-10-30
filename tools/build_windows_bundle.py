"""Build a source/data transfer ZIP without machine environments or credentials."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import zipfile

ROOT_FILES = ('README.md', 'LICENSE', 'AGENTS.md', 'pyproject.toml', 'environment.yml',
              'requirements.lock', 'requirements-windows.txt', '.env.example',
              'run_senolytics.py', '启动项目.bat', '启动项目.command')
ROOT_DIRECTORIES = ('chem_pdf_extractor', 'vendor', 'tools', 'docs', 'tests', 'input_pdfs', 'output')
SKIP_NAMES = {'.env', 'config.local.json', '.DS_Store', '__pycache__', '.conda', '.git', '.runtime'}


def source_files(root: Path):
    for name in ROOT_FILES:
        p = root / name
        if p.is_file() and not p.is_symlink():
            yield p
    for name in ROOT_DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            continue
        for p in sorted(directory.rglob('*')):
            rel = p.relative_to(root)
            if (not p.is_file() or p.is_symlink() or any(part in SKIP_NAMES for part in rel.parts)
                    or p.suffix in {'.pyc', '.log', '.key', '.pem', '.token'}
                    or p.name.endswith(('-journal', '-wal', '-shm'))):
                continue
            yield p


def build_bundle(root: Path, target: Path) -> Path:
    root, target = root.resolve(), target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # backup() takes a consistent SQLite snapshot while the local web app remains open.
    with tempfile.TemporaryDirectory(prefix='senominer-transfer-') as tmp:
        db_copy = Path(tmp) / 'results.sqlite3'
        source_db = root / 'output' / 'results.sqlite3'
        if source_db.exists():
            with closing(sqlite3.connect(source_db.as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(db_copy)) as destination:
                    source.backup(destination)
                    if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('SQLite backup verification failed')
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for p in source_files(root):
                relative = p.relative_to(root)
                actual = db_copy if relative.as_posix() == 'output/results.sqlite3' else p
                archive.write(actual, 'SenoMiner-AI/' + relative.as_posix())
    return target


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    print(build_bundle(root, root / 'dist' / 'SenoMiner-AI-Windows.zip'))
