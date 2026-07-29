# Intent Analysis Engine Release Runbook

This package runs the intent analysis API as Docker services. It returns a
standard TaskList only and does not execute business tasks.

## 1. Prerequisites

- Docker Desktop 4.x or a Docker Engine with Docker Compose v2
- Network access to pull Docker base images on the first startup
- An available local port `8000` for the API

The default release uses L1 rules and mock L3 mode. It starts without
downloading an embedding model or requiring an external model API key.

## 2. Start The API

Open PowerShell in the package root:

```powershell
.\scripts\start-release.ps1
```

The script creates `.env.release` from `.env.release.example` on the first
run. The file is local configuration and must not be added to source control
or sent to other people if it contains an API key.

After startup:

```text
Health: http://127.0.0.1:8000/health
Docs:   http://127.0.0.1:8000/docs
API:    http://127.0.0.1:8000/api/v1/intent/analyze
```

Start the optional frontend:

```powershell
.\scripts\start-release.ps1 -WithFrontend
```

## 3. Configure A Real L3 Model

Edit `.env.release` before starting the service:

```env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your-own-api-key
LLM_MODEL=deepseek-chat
```

Do not package, commit, print, or log a real API key. Restart the release
services after modifying the file:

```powershell
.\scripts\stop-release.ps1
.\scripts\start-release.ps1
```

`ENABLE_SEMANTIC_MATCHING=false` is intentional for the portable release:
unknown Chinese tasks can use the configured L3 model without requiring BGE,
Milvus, or a vector-model download.

## 4. API Smoke Test

```powershell
$body = @{
  text = "请计算本月销售提成"
  user_id = "release-user"
  conversation_id = "release-conversation"
  debug = $false
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/intent/analyze" `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

The response is a standard TaskList. When required information is missing,
the response requests clarification instead of guessing.

## 5. Stop Or Reset

Stop containers while preserving PostgreSQL data:

```powershell
.\scripts\stop-release.ps1
```

Remove containers and the release PostgreSQL volume:

```powershell
.\scripts\stop-release.ps1 -RemoveData
```

## 6. Call From Another Computer

Deploy the package on a server that can run Docker. Replace `127.0.0.1` in
the API URL with the server IP address or domain name, and allow inbound TCP
port `8000` in the server firewall and network security group.

For an Internet-facing deployment, put an authenticated HTTPS reverse proxy
in front of the API. Do not expose the API or PostgreSQL port publicly
without network access controls.

## 7. Create The Delivery Zip

Run this on the development computer:

```powershell
.\scripts\create-release-package.ps1
```

The zip is written to `dist/`. It excludes local environments, runtime data,
logs, Git metadata, frontend dependencies, and `.env.release`.
