# L1.6 Context & Prompt MVP

This is the week-1 MVP for L1.6 context and prompt management.

Current implementation direction:

- Langfuse is the primary LLMOps / prompt-management platform.
- harness9 is used only as a Context Engineering reference: token budget, 80% warning, summarization compaction, session persistence, and resume-style recovery.
- Sync package / inheritance package, work report, handoff file, Project command center, and account command center remain self-built business modules.

It uses only Python standard library modules:

- `http.server` for HTTP APIs
- `sqlite3` for local persistence
- simple mock permission adapter
- local audit event table

## Start

```powershell
python .\l1_6_context_prompt\server.py
```

If the system `python` command is unavailable, use:

```powershell
.\l1_6_context_prompt\run_server.ps1
```

Default URL:

```text
http://127.0.0.1:8765
```

Demo console:

```text
http://127.0.0.1:8765/
```

## Local storage

All MVP data is stored locally by default.

```text
l1_6_context_prompt/data/l1_6.sqlite3
```

The database is created automatically on first start from:

```text
l1_6_context_prompt/schema.sql
```

No cloud database or external service is required for the week-1 MVP. The mock permission adapter and audit log also write to the same local SQLite database.

## Health

```text
GET /health
```

## Main APIs

Context:

- `POST /api/context/estimate`
- `POST /api/context/memories`
- `GET /api/context/memories`
- `GET /api/context/memories/{id}`
- `PATCH /api/context/memories/{id}`
- `POST /api/context/memories/{id}/archive`

Conversation session:

- `POST /api/sessions`
- `GET /api/sessions`
- `GET /api/sessions/{id}`
- `PATCH /api/sessions/{id}/capacity`
- `POST /api/sessions/{id}/context-usage`
- `POST /api/sessions/{id}/compactions`
- `GET /api/sessions/{id}/compactions`
- `PATCH /api/sessions/{id}/notes`
- `GET /api/sessions/{id}/capacity-events`
- `POST /api/sessions/{id}/work-report`
- `POST /api/sessions/{id}/handoff-file`
- `POST /api/sessions/{id}/handoff-package`
- `POST /api/sessions/{id}/close`

Prompt:

- `POST /api/prompts/templates`
- `GET /api/prompts/templates`
- `POST /api/prompts/templates/{template_id}/versions`
- `GET /api/prompts/templates/{template_id}/versions`
- `POST /api/prompts/versions/{version_id}/publish`

Artifacts:

- `POST /api/artifacts/files`
- `GET /api/artifacts/files`
- `GET /api/artifacts/files/{id}`

Generated outputs:

- `GET /api/work-reports`
- `GET /api/handoff-files`
- `GET /api/handoff-packages`

Sync package / inheritance package:

- `POST /api/projects/{project_id}/sync-packages/upgrade`
- `GET /api/projects/{project_id}/sync-packages/latest`
- `GET /api/projects/{project_id}/sync-packages`

Langfuse-style local trace facade:

- `GET /api/langfuse/traces`
- `GET /api/langfuse/traces/{trace_id}`
- `POST /api/langfuse/traces/{trace_id}/score`

Audit:

- `GET /api/audit-events`

## Phase-1 scope now covered

- Records per-session capacity usage.
- Emits 80% warning and 85% forced-handoff capacity events.
- Manages project-level prompt templates and active prompt versions.
- Stores Langfuse platform binding metadata for prompt versions.
- Records Langfuse-style prompt run traces and scores for generated files.
- Can generate work reports, handoff files, and sync packages with Kimi/Moonshot when `LLM_PROVIDER=kimi`.
- Upgrades project-level sync packages / inheritance packages from work reports.
- Records harness9-style context estimates and summarization compaction events.

## Remote model integration

Langfuse remains the prompt-management and version-control layer. The remote LLM is the model execution layer.

### DeepSeek official API

Use this for the fast DeepSeek model:

```text
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

The generic OpenAI-compatible variable names are also supported:

```text
LLM_PROVIDER=deepseek
OPENAI_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

### Kimi / Moonshot API

Add these values to `.env`:

```text
LLM_PROVIDER=kimi
MOONSHOT_API_KEY=sk-your-key
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=kimi-k2.6
```

After enabling a remote model, work report, handoff file, and sync package generation call the configured model instead of the deterministic MVP renderer. If `LLM_PROVIDER` is not `kimi` or `deepseek`, the local deterministic renderer is still used so smoke tests can run without network access.

Check local LLM config without exposing the secret:

```text
GET http://127.0.0.1:8765/api/llm/config
GET http://127.0.0.1:8765/api/deepseek/config
```
- Registers generated outputs in `artifact_file` for later retrieval.

