from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.templates import run_template


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: template_cli.py SCENARIO_ID INPUT_JSON RESULT_DIR TIMEOUT_SECONDS")
    scenario_id = sys.argv[1]
    input_path = Path(sys.argv[2])
    result_dir = Path(sys.argv[3])
    timeout_seconds = int(sys.argv[4])
    task_input = json.loads(input_path.read_text(encoding="utf-8"))
    result = run_template(scenario_id, task_input, result_dir, timeout_seconds)
    (result_dir / "docker_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
