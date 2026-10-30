"""SQLite persistence for the existing catalog; extraction and presentation stay intact."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from .text_safety import json_dumps_utf8

_SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS papers (
    position INTEGER PRIMARY KEY,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    pmid TEXT NOT NULL,
    doi TEXT NOT NULL,
    read_at TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS papers_id ON papers(id);
CREATE TABLE IF NOT EXISTS compounds (
    id TEXT PRIMARY KEY,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    pubchem_cid TEXT NOT NULL,
    chembl_id TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    position INTEGER PRIMARY KEY,
    id TEXT NOT NULL,
    compound_id TEXT NOT NULL REFERENCES compounds(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL,
    study_type TEXT NOT NULL,
    effect_type TEXT NOT NULL,
    model TEXT NOT NULL,
    dose TEXT NOT NULL,
    duration TEXT NOT NULL,
    result TEXT NOT NULL,
    evidence_quote TEXT NOT NULL,
    evidence_location TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experiments_source ON experiments(compound_id, paper_id);
CREATE INDEX IF NOT EXISTS experiments_type ON experiments(study_type, effect_type);
"""


def database_path(root: Path) -> Path:
    return Path(root) / "output" / "results.sqlite3"


def save_catalog(root: Path, data: dict) -> None:
    """Atomically mirror current, already-validated results without changing their order.

    Queryable columns cover the common fields; JSON retains every original field,
    including combination identities, outcomes, steps and literal source evidence.
    Identical refreshes do not rewrite result rows. Unknown database tables are untouched.
    """
    serialized = json_dumps_utf8(data, sort_keys=True)
    digest = hashlib.sha256(f"{_SCHEMA_VERSION}\n{serialized}".encode("utf-8")).hexdigest()
    # Work on the serialization to keep SQL strings safe and leave caller data intact.
    saved = json.loads(serialized)
    target = database_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target, timeout=30)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(_SCHEMA)
        # Check and update under the same write lock, including simultaneous refreshes.
        db.execute("BEGIN IMMEDIATE")
        try:
            current = db.execute("SELECT value FROM catalog_state WHERE key = 'digest'").fetchone()
            if current is not None and current[0] == digest:
                db.commit()
                return
            db.execute("DELETE FROM experiments")
            db.execute("DELETE FROM compounds")
            db.execute("DELETE FROM papers")
            db.executemany("INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (position, str(paper['id']), str(paper.get('title') or ''),
                 str(paper.get('source_name') or ''), str(paper.get('pmid') or ''),
                 str(paper.get('doi') or ''), str(paper.get('read_at') or ''), json_dumps_utf8(paper))
                for position, paper in enumerate(saved.get('papers', []))
            ])
            db.executemany("INSERT INTO compounds VALUES (?, ?, ?, ?, ?, ?)", [
                (str(compound['id']), position, str(compound['name']),
                 str(compound.get('identity', {}).get('cid') or ''),
                 str(compound.get('identity', {}).get('chembl_id') or ''), json_dumps_utf8(compound))
                for position, compound in enumerate(saved.get('compounds', []))
            ])
            records = [(compound['id'], paper['id'], record)
                       for compound in saved.get('compounds', [])
                       for paper in compound.get('papers', [])
                       for record in paper.get('experiment_records', [])]
            fields = ('id', 'study_type', 'effect_type', 'model', 'dose', 'duration',
                      'result', 'evidence_quote', 'evidence_location')
            db.executemany("INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (position, str(record.get('id') or ''), str(compound_id), str(paper_id),
                 *(str(record.get(key) or '') for key in fields[1:]), json_dumps_utf8(record))
                for position, (compound_id, paper_id, record) in enumerate(records)
            ])
            db.executemany("INSERT OR REPLACE INTO catalog_state VALUES (?, ?)", [
                ('digest', digest), ('schema_version', str(_SCHEMA_VERSION)),
                ('summary', json_dumps_utf8(saved.get('summary', {}))),
                ('local_pdfs', json_dumps_utf8(saved.get('local_pdfs', []))),
            ])
            db.commit()
        except BaseException:
            db.rollback()
            raise


def read_catalog(root: Path) -> dict | None:
    """Read the complete saved result independently of the original report files."""
    target = database_path(root)
    if not target.is_file():
        return None
    with closing(sqlite3.connect(target, timeout=30)) as db:
        # A single read transaction prevents mixing two concurrent saved snapshots.
        db.execute("BEGIN")
        state = dict(db.execute("SELECT key, value FROM catalog_state"))
        if 'digest' not in state:
            return None
        return {
            'compounds': [json.loads(row[0]) for row in db.execute(
                'SELECT data_json FROM compounds ORDER BY position')],
            'papers': [json.loads(row[0]) for row in db.execute(
                'SELECT data_json FROM papers ORDER BY position')],
            'local_pdfs': json.loads(state['local_pdfs']),
            'summary': json.loads(state['summary']),
        }


def sync_project_output(output_dir: Path) -> None:
    """Save completed project extractions even when no browser is polling the API."""
    from .config import PROJECT_ROOT
    if Path(output_dir).resolve().is_relative_to((PROJECT_ROOT / 'output').resolve()):
        from .catalog import build_catalog
        build_catalog(PROJECT_ROOT)
