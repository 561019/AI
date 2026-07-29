from __future__ import annotations

import asyncio

from .runtime import build_runtime


async def run() -> None:
    runtime = build_runtime()
    await runtime.initialize()
    try:
        await runtime.worker.run_forever(runtime.settings.worker_poll_seconds)
    finally:
        await runtime.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
