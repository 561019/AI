# Test Results - 2026-07-17

Workspace:

```text
D:\AIProjects\intent-analysis-engine
```

## Summary

| Scope | Command | Result |
| --- | --- | --- |
| Backend regression | `.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider` | `419 passed, 4 skipped, 2 warnings` |
| Context Provider integration | `.\.venv\Scripts\python.exe -m pytest tests\backend\test_context_provider_integration.py -q -p no:cacheprovider` | `10 passed` |

Screenshot:

```text
docs/reports/screenshots/test-results-20260717.png
```

Raw outputs:

```text
docs/reports/pytest-backend-20260717.txt
docs/reports/pytest-context-provider-20260717.txt
```

## Notes

- The Context Provider integration test verifies the mocked external context call and omitted-expression resolution.
- The current mock case resolves `帮我再算一遍` to `重新计算2025年销售提成`.
- The two warnings are existing dependency deprecation warnings and do not fail the suite.

