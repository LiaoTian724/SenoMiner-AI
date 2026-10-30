"""Windows first-run setup and normal launch; never reuse a macOS Conda prefix."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PYTHON_VERSION = '3.11.15'
ENVIRONMENT_NAME = 'SenoMiner_AI'
CONDA_PACKAGES = ('python=3.11.15', 'sqlite=3.51.2', 'pip=26.0.1', 'psutil=7.0.0', 'tornado=6.5.5')
IMPORTS = ('pypdf', 'pymupdf', 'pymupdf4llm', 'langchain', 'langchain_core', 'langchain_ollama',
           'pydantic', 'pandas', 'openpyxl', 'polite_http', 'dotenv', 'certifi', 'rdkit')
CHECK_CODE = (
    "import sys,importlib;from pathlib import Path;"
    f"assert sys.version_info[:3]==(3,11,15),sys.version;"
    f"assert Path(sys.prefix).name=={ENVIRONMENT_NAME!r},sys.prefix;"
    "assert sys.platform=='win32',sys.platform;assert sys.maxsize>2**32;"
    f"[importlib.import_module(name) for name in {IMPORTS!r}];"
    "from rdkit import Chem;assert Chem.MolFromSmiles('CCO') is not None;"
    "import sqlite3;sqlite3.connect(':memory:').close();"
    "print('Windows environment ready: Python '+sys.version.split()[0])"
)


def environment_path(root: Path) -> Path:
    return root / '.conda' / 'win-64' / ENVIRONMENT_NAME


def conda_run(conda: Path, prefix: Path, *args: str) -> list[str]:
    return [str(conda), 'run', '--no-capture-output', '--prefix', str(prefix), *map(str, args)]


def requirements_digest(root: Path) -> str:
    return hashlib.sha256((PYTHON_VERSION + '\n').encode() +
                          (root / 'requirements-windows.txt').read_bytes() +
                          (root / 'requirements.lock').read_bytes()).hexdigest()


def prepare_environment(root: Path, conda: Path, *, run=subprocess.run) -> Path:
    root = root.resolve()
    prefix = environment_path(root)
    executable = prefix / 'python.exe'
    stamp_path = prefix / '.senominer-windows-ready.json'
    digest = requirements_digest(root)
    try:
        stamp = json.loads(stamp_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        stamp = {}
    if stamp.get('prefix') and stamp['prefix'] != str(prefix):
        raise RuntimeError('这个 Windows 环境来自其他路径。请重新解压不含 .conda 的启动包，在固定位置重新初始化。')
    if not executable.is_file():
        if prefix.exists():
            raise RuntimeError(f'发现未完成的 Windows 环境：{prefix}。请移除这个 Windows 专用目录后重试；原 Mac 环境不用处理。')
        print('[1/3] 首次创建 Windows 专用环境，请保持窗口打开。', flush=True)
        run([str(conda), 'create', '--platform', 'win-64', '--prefix', str(prefix), '--override-channels', '-c', 'conda-forge',
             *CONDA_PACKAGES, '--yes'], check=True, cwd=str(root))
    if stamp.get('requirements') != digest:
        print('[2/3] 安装项目固定版本依赖，首次需要联网。', flush=True)
        run(conda_run(conda, prefix, str(executable), '-m', 'pip', 'install', '--only-binary=:all:',
                      '--requirement', str(root / 'requirements-windows.txt')),
            check=True, cwd=str(root))
    print('[3/3] 检查 Python、PDF、数据库和分子依赖。', flush=True)
    run(conda_run(conda, prefix, str(executable), '-c', CHECK_CODE), check=True, cwd=str(root))
    # Save success only after all components have actually imported in this environment.
    stamp_path.write_text(json.dumps({'prefix': str(prefix), 'requirements': digest,
                                     'python': PYTHON_VERSION}, ensure_ascii=False), encoding='utf-8')
    return prefix


def ensure_local_config(root: Path) -> bool:
    target = root / '.env'
    if target.exists():
        return False
    shutil.copyfile(root / '.env.example', target)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conda', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.error('此入口用于 Windows；Mac 请使用 启动项目.command。')
    root = Path(__file__).resolve().parents[1]
    try:
        prefix = prepare_environment(root, args.conda)
        created = ensure_local_config(root)
        if created:
            print('已生成 .env 模板。可先浏览已有结果；提取新论文前请填写自己的 ARK_API_KEY。', flush=True)
        print('正在打开本地网页。请保持这个窗口打开，结束时按 Ctrl+C。', flush=True)
        return subprocess.call(conda_run(args.conda, prefix, str(prefix / 'python.exe'),
                                        str(root / 'run_senolytics.py'), '--open-browser', '--no-auto-install'),
                               cwd=str(root))
    except subprocess.CalledProcessError as exc:
        print(f'初始化失败（退出码 {exc.returncode}）。请检查网络和上方错误，修复后再次双击启动。', file=sys.stderr)
        return exc.returncode or 1
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
