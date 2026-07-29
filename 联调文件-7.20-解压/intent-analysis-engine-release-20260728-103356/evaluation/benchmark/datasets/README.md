# Benchmark Datasets

This directory stores benchmark data separate from development tests.

Rules:

- `train` may be used for dataset analysis and threshold exploration.
- `validation` may be used for regular development regression.
- `blind_test` is final acceptance data. Do not inspect or tune against it.
- Do not import benchmark data into `tests/backend`.
- Add new data as JSON or JSONL files using the required sample schema.

