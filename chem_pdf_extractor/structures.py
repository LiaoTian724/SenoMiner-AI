"""PubChem conformers with an explicitly labelled local RDKit fallback."""
from __future__ import annotations

from .network import tls_context

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

_LOCK = threading.Lock()


def _valid_3d(sdf: str) -> bool:
    from rdkit import Chem
    mol = Chem.MolFromMolBlock(sdf, removeHs=False)
    return bool(mol and 0 < mol.GetNumAtoms() <= 500 and mol.GetNumConformers()
                and mol.GetConformer().Is3D()
                and all(math.isfinite(v) for point in mol.GetConformer().GetPositions() for v in point))


def _fetch(cid: str, dimension: str) -> str:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type={dimension}"
    request = urllib.request.Request(url, headers={"User-Agent": "SenolyticsKnowledge/0.4.0 (research; PUG REST)"})
    with urllib.request.urlopen(request, timeout=15, context=tls_context()) as response:
        data = response.read(1_000_001)
    if len(data) > 1_000_000 or b"V2000" not in data and b"V3000" not in data:
        raise ValueError("PubChem 返回的结构文件无效")
    return data.decode("utf-8", errors="replace")


def generate_conformer(sdf: str, cid: str) -> str:
    """Generate one visual conformer; preserve the source molecular graph/stereo."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise ValueError("本环境缺少 RDKit，无法生成备用 3D 构象") from exc
    mol = Chem.MolFromMolBlock(sdf, removeHs=False)
    if mol is None or not 1 <= mol.GetNumHeavyAtoms() <= 200:
        raise ValueError("PubChem 化学结构无效或超出本地构象生成范围")
    identity = Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True)
    mol.RemoveAllConformers()
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 61453
    params.numThreads = 1
    params.maxIterations = 500
    params.timeout = 15
    status = AllChem.EmbedMolecule(mol, params)
    if status != 0:
        params.useRandomCoords = True
        status = AllChem.EmbedMolecule(mol, params)
    if status != 0:
        raise ValueError("RDKit 未能生成有效 3D 构象")
    try:
        if AllChem.MMFFHasAllMoleculeParams(mol):
            AllChem.MMFFOptimizeMolecule(mol, maxIters=300)
        elif AllChem.UFFHasAllMoleculeParams(mol):
            AllChem.UFFOptimizeMolecule(mol, maxIters=300)
    except (ValueError, RuntimeError):
        pass  # Valid ETKDG coordinates remain usable for visual identification.
    if Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True) != identity:
        raise ValueError("构象生成改变了分子身份，拒绝展示")
    mol.SetProp("_Name", f"PubChem CID {cid}; RDKit ETKDGv3 generated conformer")
    return Chem.MolToMolBlock(mol) + f"\n> <PUBCHEM_COMPOUND_CID>\n{cid}\n\n$$$$\n"


def _save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(pending).replace(path)
    finally:
        Path(pending).unlink(missing_ok=True)


def molecular_structure(cid: str, root: Path) -> dict:
    if not re.fullmatch(r"\d{1,10}", str(cid)):
        raise ValueError("无效 PubChem CID")
    cache = root / "output" / ".structure_cache"
    sdf_path, meta_path = cache / f"{cid}.sdf", cache / f"{cid}.json"
    # Serialise embedding and cache writes; this local app has few structures.
    with _LOCK:
        if sdf_path.is_file() and sdf_path.stat().st_size <= 1_000_000:
            sdf = sdf_path.read_text()
            if _valid_3d(sdf):
                meta = {"origin": "pubchem_3d", "label": "PubChem 提供的 3D 构象"}
                valid_meta = not meta_path.is_file()
                if meta_path.is_file():
                    try:
                        saved = json.loads(meta_path.read_text())
                        if saved.get("sha256") == hashlib.sha256(sdf.encode()).hexdigest():
                            meta = saved
                            valid_meta = True
                    except (ValueError, OSError):
                        pass
                elif "RDKit" in sdf[:200] or "generated conformer" in sdf[:200]:
                    valid_meta = False
                if valid_meta:
                    return {"sdf": sdf, **meta}
        try:
            sdf = _fetch(cid, "3d")
            if not _valid_3d(sdf):
                raise ValueError("PubChem 没有返回有效 3D 坐标")
            meta = {"origin": "pubchem_3d", "label": "PubChem 提供的 3D 构象"}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            try:
                source_path = cache / f"{cid}.source2d.sdf"
                source = source_path.read_text() if source_path.is_file() else _fetch(cid, "2d")
                _save(source_path, source)
                sdf = generate_conformer(source, cid)
                meta = {"origin": "rdkit_etkdg", "label": "RDKit 根据 PubChem 化学结构生成的 3D 构象",
                        "method": "ETKDGv3; MMFF/UFF when available", "rdkit_version": __import__("rdkit").__version__}
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                raise ValueError("PubChem 结构暂不可用，且本地备用构象未生成；可稍后重试") from exc
        meta.update({"cid": cid, "sha256": hashlib.sha256(sdf.encode()).hexdigest(),
                     "structure_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"})
        _save(sdf_path, sdf)
        _save(meta_path, json.dumps(meta, ensure_ascii=False))
        return {"sdf": sdf, **meta}
