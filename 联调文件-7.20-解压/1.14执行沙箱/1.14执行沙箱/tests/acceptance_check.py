from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.acceptance import run_acceptance_checks


def main() -> None:
    report = run_acceptance_checks(ROOT)
    assert report["summary"]["failed"] == 0, report
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
