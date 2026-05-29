#!/usr/bin/env python3
"""One-shot OMPA vault refresh for WhaleTrax."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(script: str) -> None:
    subprocess.run([sys.executable, str(ROOT / script)], check=True)


def main() -> None:
    run('ingest_whaletrax.py')
    run('ingest_reports.py')
    run('export_locus.py')
    print('OMPA vault refreshed')


if __name__ == '__main__':
    main()
