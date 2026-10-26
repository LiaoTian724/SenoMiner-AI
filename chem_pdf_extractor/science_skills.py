"""Run the unmodified Science Skills CLIs in the active project environment."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "vendor" / "science-skills"


class SkillError(RuntimeError):
    pass


class ScienceSkills:
    def __init__(self, cache_dir: Path, timeout: int = 90, ttl: int = 604800):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.ttl = ttl

    def call(self, database: str, *args: str) -> Any:
        if database not in {"pubchem", "chembl", "pubmed"}:
            raise ValueError("Unsupported database")
        script = SKILLS_ROOT / f"{database}_database" / "scripts" / f"{database}_api.py"
        if not script.is_file():
            raise SkillError(f"Missing vendored {database} wrapper")
        digest = hashlib.sha256(json.dumps([database, args]).encode()).hexdigest()
        cache = self.cache_dir / f"{digest}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < self.ttl:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        env = os.environ.copy()
        env.setdefault("NCBI_TOOL", "SenoMiner_AI")
        if env.get("NCBI_EMAIL") and not env.get("USER_EMAIL"):
            env["USER_EMAIL"] = env["NCBI_EMAIL"]
        # argv arrays, never a shell; each query has an independent output file.
        with tempfile.TemporaryDirectory(prefix="query-", dir=self.cache_dir) as tmp:
            output = Path(tmp) / "result.json"
            argv = ([str(output), *args] if database == "pubmed"
                    else [*args, "--output", str(output)])
            try:
                proc = subprocess.run([sys.executable, str(script), *argv],
                                      env=env, capture_output=True, text=True,
                                      timeout=self.timeout, check=False)
            except subprocess.TimeoutExpired:
                raise SkillError(f"{database} query timed out") from None
            if proc.returncode or not output.exists():
                # Avoid reflecting upstream diagnostics containing URLs/credentials.
                raise SkillError(f"{database} wrapper failed (exit {proc.returncode})")
            try:
                result = json.loads(output.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise SkillError(f"{database} returned invalid JSON") from None
        if isinstance(result, dict) and (result.get("error") or result.get("status") == "error"):
            # Only genuine not-found responses can be interpreted as no match.
            if database == "pubchem" and "404" in str(result.get("error", "")):
                return result
            raise SkillError(f"{database} reported a query error")
        fd, temp_name = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)
        Path(temp_name).replace(cache)
        return result
