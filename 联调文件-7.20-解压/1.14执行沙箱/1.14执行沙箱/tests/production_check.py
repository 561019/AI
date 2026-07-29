from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.executors import DockerTemplateExecutor, LocalTemplateExecutor
from backend.service import SandboxService


def main() -> None:
    service = SandboxService(ROOT)
    readiness = service.readiness()
    assert readiness["ok"], readiness
    assert len(service.list_scenarios()) == 20

    task = service.create_task({"scenario_id": "s19_over_stock_warning", "actor": "sales-user", "input": {}})
    assert task["status"] == "success"
    assert task["result"]["payload"]["status"] == "warning"
    assert task["logs"]

    local = LocalTemplateExecutor().health()
    docker_image = str(service.config.get("runtime", {}).get("docker_image", "python:3.12-slim"))
    docker = DockerTemplateExecutor(ROOT, docker_image).health()
    report = {
        "ok": True,
        "readiness": readiness,
        "local_executor": local,
        "docker_executor": docker,
        "note": "Docker availability depends on local Docker Desktop/service. Local executor remains available as fallback.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "production_check.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
