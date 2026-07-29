"""需要安装 ``.[api]``；用于真实 HTTP 生命周期冒烟测试。"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def main() -> None:
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("OBJECT_STORE_ACCESS_KEY", None)
    os.environ.pop("OBJECT_STORE_SECRET_KEY", None)
    os.environ["ALLOW_DEMO_ACTOR"] = "true"
    os.environ["ENABLE_EMBEDDED_WORKER"] = "true"
    with tempfile.TemporaryDirectory() as directory:
        os.environ["LOCAL_DATA_DIR"] = directory
        from fastapi.testclient import TestClient
        from doc_table_engine.api import create_app

        with TestClient(create_app()) as client:
            response = client.post(
                "/v1/jobs",
                headers={"X-Actor-ID": "demo-user"},
                files={"file": ("sales.csv", "区域,销售额\n华东,125000.00\n", "text/csv")},
                data={"business_tags": '["project:demo"]', "confidence_threshold": "0.85"},
            )
            response.raise_for_status()
            job_id = response.json()["job_id"]
            status = "queued"
            for _ in range(50):
                status_response = client.get(f"/v1/jobs/{job_id}")
                status_response.raise_for_status()
                status = status_response.json()["status"]
                if status in {"completed", "failed", "review_required"}:
                    break
                time.sleep(0.05)
            if status != "completed":
                raise AssertionError(f"HTTP 任务未完成: {status}")
            result = client.get(f"/v1/jobs/{job_id}/result", headers={"X-Actor-ID": "demo-user"})
            result.raise_for_status()
            payload = result.json()["result"]
            assert payload["registration"]["job_id"] == job_id
            assert payload["semantic"]["tables"][0]["values"][3]["raw_value"] == "125000.00"
            print({"job_id": job_id, "status": status, "route": payload["registration"]["route"]})


if __name__ == "__main__":
    main()
