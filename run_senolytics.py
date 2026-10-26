"""Launch the adapted workbench using the project's exact virtual environment."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main():
    if sys.version_info[:3] != (3, 11, 15) or Path(sys.prefix).name != "SenoMiner_AI":
        raise SystemExit("请使用 SenoMiner_AI 虚拟环境（Python 3.11.15），操作见 README.md。")
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    for dest, source in (("CHEM_PDF_EXTRACTOR_API_KEY", "ARK_API_KEY"),
                         ("CHEM_PDF_EXTRACTOR_BASE_URL", "ARK_BASE_URL"),
                         ("CHEM_PDF_EXTRACTOR_MODEL", "ARK_MODEL_ID"),
                         ("USER_EMAIL", "NCBI_EMAIL")):
        if os.getenv(source):
            os.environ.setdefault(dest, os.environ[source])
    os.chdir(root)
    from chem_pdf_extractor.entrypoint import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
