# Package Verification

This handoff package was prepared for external integration and local startup.

## Verified Before Packaging

```text
Backend tests: 432 passed, 4 skipped
Docker Compose config: valid with .env.example
Package dry-run: passed
```

## Recommended Startup For Receiver

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Then check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

API docs:

```text
http://127.0.0.1:8000/docs
```

Main API:

```text
POST /api/v1/intent/analyze
POST /api/v1/intent/clarification/answer
```

## Package Exclusions

The package intentionally excludes local-only and sensitive files:

```text
.git/
.codex/
.agents/
.venv/
frontend/node_modules/
.runtime/
.pytest_cache/
.env
.env.local
*.log
```

Use `.env.example` and `.env.local.example` as templates. Do not send real API keys inside the package.
