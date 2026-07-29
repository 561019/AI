#!/usr/bin/env bash
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8013
