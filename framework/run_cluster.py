from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from framework.core import initialize
from framework.run_services import SERVICES


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    initialize()
    environment = {**os.environ, "PLATFORM_DB_INITIALIZED": "1"}
    processes: list[subprocess.Popen] = []
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        for service in SERVICES:
            processes.append(subprocess.Popen([sys.executable, "-m", "framework.run_services", service], cwd=root, env=environment))
        print(f"CLUSTER_READY services={len(processes)}", flush=True)
        while not stopping:
            failed = [process.returncode for process in processes if process.poll() is not None]
            if failed:
                print(f"CLUSTER_PROCESS_EXIT codes={failed}", flush=True)
                return 1
            time.sleep(0.25)
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
