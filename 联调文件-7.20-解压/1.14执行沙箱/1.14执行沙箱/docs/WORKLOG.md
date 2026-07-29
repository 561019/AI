# Worklog

## Long-Term Project Memory

Last updated: 2026-07-01

This file is the persistent memory for the Agent Execution Sandbox project. Read this first if conversation context has been compressed or lost.

## User Profile And Intent

- User is a beginner and needs plain-language explanations.
- User wants to validate whether the L1 1.14 Agent Execution Sandbox module is feasible.
- User initially asked for a project at `D:\agent-sandbox-module`.
- User does not need real enterprise production integration immediately; feasibility validation is the real goal.
- User prefers visible UI evidence rather than raw JSON only.
- User asked to preserve project context before conversation compaction.
- Project memory rule: whenever the project moves forward, update this `WORKLOG.md` immediately after each meaningful step. Do not wait until the end of a long work session.
- Context management rule: this is separate from `WORKLOG.md`. When the current conversation context window approaches about 70%, proactively create a concise context summary in chat and preserve important project state in `WORKLOG.md` before continuing. The assistant cannot directly trigger the platform's internal compaction mechanism, but should behave as if doing manual context compression at that threshold.

## Project Location

Main deliverable:

```text
D:\agent-sandbox-module
```

Workspace source copy:

```text
C:\Users\刘卓\Documents\Codex\2026-06-30\zhe\agent-sandbox-module
```

The D drive project is the user-facing deliverable. When editing from the workspace copy, sync changes to D drive.

## Original Inputs

The project is based on:

1. 执行沙箱研发方案 v0.1
   - L1 · 1.14 执行沙箱
   - Core principle: give digital employees an isolated, disposable execution environment.
   - Sandbox handles "where to run safely", not "whether it should run".
   - Adjacent modules:
     - 1.4 驾驭机制: whether to run, max steps, dead loop, human approval.
     - 1.9 安全合规: egress allowlist, credential injection, audit, sensitive data policy.
     - 1.10 设备与系统接口: ERP/OA/database adapters.
     - 1.5 大模型调度: model calls.
     - 1.12 成本管控: CPU/memory/duration accounting.
   - Preferred future base: Cube Sandbox.
   - Docker/Firecracker/Kata can be stepping stones or fallback.

2. 沙箱的场景和需求.docx
   - Contains 20 scenes:
     1. 坏账准备、所得税、递延所得税计算
     2. 多维度毛利贡献自动计算
     3. 产品成本测算与配方变更测算
     4. 发票核销（真伪+入库单匹配）
     5. 委外材料核销及配比变动预警
     6. 杂乱数据表一键分类+透视分析
     7. 产品混配性判断+混配试验表生成
     8. 批量素材处理+字幕/配音/剪辑
     9. 短视频端到端自动剪辑+配字幕配音+背景音乐
     10. 市场分析+客户来年产品量增长预测
     11. 多平台推流/限流规则自动适配
     12. 上游原料价格每日趋势分析
     13. 拍照识别原料属性+进口原料翻译
     14. 原料价格波动分析+未来趋势预测
     15. 合同条款变动识别+合同归档
     16. 成品质量自动检测+质量追溯
     17. 库存+销售历史+市场预测的备货参考
     18. 销售订单+新客户条件+合同非工作时间 AI 审查
     19. 跨部门同时下单超库存预警
     20. 采购计划分析+历史数据对比+未来需求预测

## Current Goal Summary

Build and validate the L1 1.14 Agent Execution Sandbox module feasibility.

The user is a beginner and wants a runnable local project at:

```text
D:\agent-sandbox-module
```

## Current Status

Completed:

- Local MVP project created at `D:\agent-sandbox-module`.
- Web UI works at `http://127.0.0.1:8765`.
- 20 scenario templates from the user's sandbox requirements document are registered in `scenario_templates/scenarios.json`.
- Tasks can be submitted and executed from the web page.
- Task logs, status, result files, and result JSON are recorded under `data/`.
- `smoke_test.py` passes all 20 templates.
- Pluggable executor architecture added in `backend/executors.py`.
- `DockerTemplateExecutor` code path added.
- Docker is not available on this machine right now: `docker command not found`.
- Current running executor falls back to `LocalTemplateExecutor`.
- `/api/policy` and `/api/readiness` are available.
- `production_check.py` passes using local fallback executor.
- Mock platform services added in `backend/mock_platform.py`.
- Mock integration test added in `tests/integration_mock_test.py`.
- Task lifecycle now includes `platform_checks`.
- UI was updated to show a beginner-friendly chain summary above raw JSON:
  - 收到任务
  - 账号网关
  - 安全合规
  - ERP/OA 模拟取数
  - 沙箱执行
  - 成本记录
  - 审计留痕
- User clarified two standing rules:
  - Update `WORKLOG.md` immediately after every meaningful project step.
  - Separately, when a conversation context window reaches about 70%, proactively create a concise manual context summary and keep essential project state in `WORKLOG.md`.
- User asked for a manual context compression in the current conversation; this WORKLOG update records that checkpoint.

Important note:

- Docker/Cube Sandbox is not installed yet.
- Real ERP/OA/account/security/cost modules are not available.
- For feasibility validation, mock platform services are now implemented.

## Implemented Architecture

### Backend

- `backend/app.py`
  - HTTP server.
  - Serves frontend.
  - API endpoints:
    - `GET /api/health`
    - `GET /api/scenarios`
    - `GET /api/tasks`
    - `GET /api/tasks/{task_id}`
    - `POST /api/tasks`
    - `GET /api/policy`
    - `GET /api/readiness`
    - `GET /api/files/{relative_result_path}`

- `backend/service.py`
  - Main orchestration.
  - Creates tasks.
  - Runs account/security/mock data/executor/cost/audit lifecycle.
  - Stores task JSON in `data/tasks.json`.

- `backend/templates.py`
  - Contains 20 scenario template handlers.
  - These are deterministic local handlers used for feasibility validation.
  - They do not call paid APIs.

- `backend/executors.py`
  - `LocalTemplateExecutor`
  - `DockerTemplateExecutor`
  - `build_executor(config, project_root)`
  - `runtime.executor` in `config.example.json` supports:
    - `auto`
    - `docker`
    - `local`

- `backend/template_cli.py`
  - CLI entry used by Docker executor inside a container.

- `backend/mock_platform.py`
  - `MockAccountGateway`
  - `MockSecurityCompliance`
  - `MockERP`
  - `MockOA`
  - `MockCostControl`
  - `MockPlatform`

### Frontend

- `frontend/index.html`
- `frontend/styles.css`
- `frontend/app.js`

Current UI sections:

- 运行任务
- 执行记录
- 安全边界

Important UI behavior:

- User chooses a scenario and submits JSON.
- Execution record list shows task name, timestamp, and status.
- Clicking a task shows:
  - beginner-friendly summary cards
  - platform chain steps
  - business result summary
  - raw JSON for developers

### Docs

- `README.md`
- `docs/DELIVERY_NOTES.md`
- `docs/ROADMAP.md`
- `docs/WORKLOG.md`

## Mock Platform Chain

Implemented chain:

```text
submit task
→ mock account gateway resolves actor/role/department/permissions
→ mock security compliance checks permissions
→ mock ERP/OA injects test data for selected scenarios
→ sandbox executor runs template
→ mock cost control records duration/memory/cpu cost units
→ mock audit events are saved
→ UI displays platform_checks and business result
```

Mock-enhanced scenarios:

- `s04_invoice_matching`
  - gets invoices and receipts from mock ERP.
- `s15_contract_diff`
  - gets old/new contract text from mock OA.
- `s19_over_stock_warning`
  - gets inventory and cross-department orders from mock ERP.
- `s20_purchase_plan`
  - gets purchase history and current stock from mock ERP.

Permission denial path:

- `sales-user` can run inventory/order scenarios.
- `sales-user` cannot run invoice matching because missing `receipt:read`.
- `integration_mock_test.py` verifies this failure path.

## Validation Commands

Run these from:

```powershell
cd D:\agent-sandbox-module
```

Commands:

```powershell
python tests\smoke_test.py
python tests\production_check.py
python tests\integration_mock_test.py
```

Expected:

- All print JSON with `"ok": true`.

Known status:

- `production_check.py` reports Docker unavailable unless Docker is installed.
- That is OK for feasibility validation.

## How User Opens The App

Start service:

```powershell
cd D:\agent-sandbox-module
python backend\app.py
```

Open:

```text
http://127.0.0.1:8765/
```

If page seems old:

- Press `Ctrl + F5`.
- Then click `执行记录`.
- Click a task.
- Look above the black JSON area for summary cards.

## Current Limitations

This is not a final enterprise production deployment.

Still missing for real production:

- Docker Desktop installed and running, or server-side Docker.
- Cube Sandbox deployed on a suitable Linux/KVM server.
- Real ERP/OA/database test interfaces.
- Real account gateway.
- Real security compliance service.
- Real cost control service.
- Real credential vault.
- Real egress gateway.
- Immutable audit storage.
- Server deployment and operational monitoring.

For the user's actual goal, which is feasibility validation, the current mock-integrated prototype is enough to prove the chain can work.

## Latest Conversation Compression Summary

As of the latest checkpoint:

- The runnable app is at `D:\agent-sandbox-module`.
- The long-term memory file is only kept at:

```text
C:\Users\刘卓\Documents\Codex\2026-06-30\zhe\agent-sandbox-module\docs\WORKLOG.md
```

- The copy at `D:\agent-sandbox-module\docs\WORKLOG.md` was deleted by user request.
- The app opens at `http://127.0.0.1:8765/`.
- If old UI appears, use `Ctrl + F5`.
- The UI now has beginner-friendly task detail cards above the raw JSON.
- The project currently validates feasibility with mock services, not real production services.
- Docker is not installed/available; Docker executor code exists but falls back to local executor.
- Do not install Docker unless the user explicitly asks to install it.

## Re-Review On 2026-07-02: Important Correction

The user challenged whether the implementation truly follows the original execution sandbox R&D plan.

After re-reading both source documents:

- `执行沙箱研发方案_v0_1_20260628(1).html`
- `沙箱的场景和需求.docx`

Important correction:

The current project is **not** a strict full implementation of the R&D plan. It is a feasibility MVP / local prototype.

The R&D plan requires the execution sandbox module to provide:

1. Independent isolated execution environment for each digital employee.
2. Disposable lifecycle: create on demand, inject code/task, isolate execution, collect result, destroy.
3. Code sandbox for Python/data analysis/modeling/batch processing.
4. Browser sandbox for webpage automation and price/competitor/market collection.
5. Optional combined code + browser sandbox.
6. CPU, memory, and runtime quotas that are enforced by the sandbox runtime.
7. Privilege escape prevention: code must not access host files/data/systems.
8. Egress allowlist: outbound access only through allowed domains.
9. Egress audit trail: record where the sandbox connected and what happened.
10. Credential injection controlled by security compliance, not visible to AI code.
11. Cost metering for CPU, memory, duration, reported to 1.12 cost control.
12. Security compliance integration for whitelist, credential injection, execution audit, permission filtering.
13. Device/system interface integration: ERP/CRM/database access must go through 1.10 adapters.
14. Model calls from sandbox must go through 1.5 model dispatch.
15. Primary open-source choice: Tencent Cloud Cube Sandbox, compatible with E2B API.
16. CubeEgress for outbound gateway.
17. Firecracker/Kata as fallback isolation options.
18. Target full local/private deployment and future Kunpeng/Ascend compatibility validation.
19. Manager-facing sandbox monitoring page showing sandbox instances, resource usage, outbound accesses, execution traces.
20. Objective acceptance tests:
    - sandbox code cannot access host files/data;
    - resource overrun is stopped;
    - outbound access only reaches allowlist;
    - all outbound activity and execution are auditable;
    - real scenarios like webpage collection and data analysis can run.

Current project only partially satisfies these:

- It has task lifecycle records, 20 scenario templates, result files, logs, a web UI, mock account/security/ERP/OA/cost services, and executor abstraction.
- It does **not** yet implement real Cube Sandbox.
- It does **not** yet implement actual browser sandbox.
- It does **not** yet enforce OS-level isolation.
- It does **not** yet enforce true resource quotas at runtime.
- It does **not** yet enforce true network egress allowlist.
- It does **not** yet do real credential injection.
- It does **not** yet prove host-file escape prevention.
- It does **not** yet integrate real 1.10/1.9/1.12/1.5 modules.
- Docker executor code exists but Docker is not installed/available, so real container isolation is not active.

New implementation direction:

Do not describe the current version as final production or full plan implementation. Describe it as:

```text
feasibility prototype with mock platform integration
```

Next work should align strictly to the R&D plan:

1. Add an explicit plan-compliance checklist page/document.
2. Implement real isolated runtime path, preferably Docker first for local validation.
3. Add browser sandbox capability, likely Playwright-in-container for local validation.
4. Add real allowlist egress enforcement for sandbox tasks.
5. Add host-file access escape tests.
6. Add timeout/resource overrun tests.
7. Add outbound blocked/allowed tests.
8. Add execution trace and egress trace UI.
9. Add Cube Sandbox/E2B adapter skeleton matching the plan.
10. Only after Docker/Cube runtime is active should the implementation be called close to production-grade.

## Module Delivery Standard From User

The user clarified the expected deliverable style for this project and related L1 modules.

Important rule:

We are **not** each building a complete platform. Each person should build their own responsible L1 small module as a capability package that is:

- demonstrable;
- testable;
- verifiable;
- later callable by the full platform.

Each module must clearly explain:

1. What problem this module solves.
2. Which job/role scenario it serves.
3. What the input is.
4. What the output is.
5. What the boundaries with other modules are.
6. How to prove the module is useful.

Recommended final deliverables for each module:

1. Module description.
2. Boundary description.
3. Input/output description.
4. API/interface description.
5. Small UI demo.
6. Scenario test data.
7. Test cases.
8. Test result document.
9. Screenshots.
10. Current limitations.
11. Follow-up modules to integrate.
12. Joint debugging / integration preparation table.

Testing standard:

- Do not only use arbitrary fake data.
- Prefer Hanhe's real job scenarios.
- Use at least one complete end-to-end role scenario to prove module capability.
- Final documentation must explain:
  - test process;
  - screenshots;
  - result;
  - current shortcomings;
  - what modules need to be connected next.

Impact on current execution sandbox project:

The final output should not be described as a complete platform. It should be reshaped into an L1 1.14 execution sandbox **capability package** with:

- a clear module explanation;
- strict module boundary;
- input/output contract;
- API list;
- demo UI;
- Hanhe scenario test data;
- objective test cases;
- test result report with screenshots;
- deficiency list;
- integration preparation table for 1.4, 1.5, 1.8, 1.9, 1.10, 1.12, and L2 engines.

## 2026-07-02 New Direction

User requested:

> 按照这个交付形态和验收口径，和方案的要求，现在改，继续推进，直到真正实现方案所提到的所有要求。

Immediate interpretation:

- Stop treating the current project as enough just because it can demo feasibility.
- Reshape it into a strict L1 module capability package.
- Add plan-compliance checklist.
- Add deliverable documents required by the user.
- Add UI/API evidence for requirements.
- Keep current limitations explicit.
- Do not claim final production until real isolation runtime is active.

Important remaining hard requirement:

- True production alignment requires Docker/Cube Sandbox/Firecracker/Kata or equivalent real isolation runtime.
- Current machine previously reported Docker unavailable.
- Do not silently install Docker/Cube. If installation becomes necessary, ask user clearly before system-level installation.

## 2026-07-02 Capability Package Documents Added

To align with the user's delivery standard, these documents were added:

- `docs/MODULE_SPEC.md`
- `docs/BOUNDARY_SPEC.md`
- `docs/API_SPEC.md`
- `docs/INTEGRATION_PREP_TABLE.md`
- `docs/PLAN_COMPLIANCE.md`
- `docs/TEST_REPORT.md`

Purpose:

- Reshape project into an L1 1.14 execution sandbox capability package.
- Clearly state module problem, role scenario, input/output, API, boundary, test status, and integration preparation.
- Explicitly record that current implementation is not full plan compliance yet.
- Identify missing requirements: Cube Sandbox, real isolation, browser sandbox, real egress enforcement, credential injection, objective security tests.

## 2026-07-02 Compliance API And UI Added

Added:

- `backend/compliance.py`
- `GET /api/compliance`
- "研发方案合规清单" section on the 安全边界 page.

Purpose:

- Make plan compliance visible in the UI, not only in documents.
- Clearly show each R&D plan requirement as 已完成 / 部分完成 / 未完成.
- Prevent overclaiming current prototype as final production implementation.

## 2026-07-02 Test Repair

Issue found during validation:

- `scenario_templates/scenarios.json` had become empty in both workspace and D drive copy.
- This broke `production_check.py` and `integration_mock_test.py`.

Fix:

- Restored all 20 scenario definitions.
- Synced `scenario_templates/scenarios.json` to `D:\agent-sandbox-module`.
- `production_check.py` was also updated to run `s19_over_stock_warning` as `sales-user`, because after adding mock permission checks the default `demo-user` does not have `order:read`.

Reason:

- The permission failure was correct behavior from the new mock account/security chain; the test needed to use an actor with the right permissions.

## 2026-07-02 Continue Toward Full Plan Requirements

User requested:

> 继续补，直到满足方案里面的所有要求。

Working interpretation:

- Continue implementing plan requirements beyond the current capability-package prototype.
- Keep stating the truth: full compliance requires a real isolation runtime.
- Prioritize implementable local steps first:
  1. Add concrete acceptance test framework for host-file access, resource overrun, egress allowlist, lifecycle, and audit.
  2. Add generated-code sandbox task type carefully, using policy controls for local validation and Docker path for real isolation when Docker is available.
  3. Add browser sandbox interface and local placeholder; real browser isolation should run in Docker/Cube.
4. Add UI and report evidence for plan requirements.
5. Check whether Docker is installed/available; do not claim Docker isolation unless it really runs.

## 2026-07-02 Platform Link Validation Added

Added:

- `backend/demo_cases.py`
- `GET /api/demo-cases`
- `POST /api/demo-cases/{case_id}`
- `frontend` navigation item and page for `平台链路验证`
- one-click demo cards for:
  - `invoice_matching`
  - `over_stock_warning`
  - `permission_denied`
- `tests/demo_cases_test.py`

Purpose:

- Give the user and future验收人 a direct, visible way to prove the module chain.
- Show three concrete evidence patterns:
  1. successful finance chain;
  2. successful inventory warning chain;
  3. permission-denial chain before sandbox execution.
- Keep the module honest: it is still a feasibility-capability package, not real Docker/Cube isolation.

Validation note:

- Existing smoke / production / mock integration / acceptance tests still pass.
- New demo cases test should be run with the regular Python test workflow.
- Tests that write to `data/tasks.json` should be run serially; parallel execution can cause temporary race failures during validation.

Reminder:

- Cube Sandbox requires suitable server/Linux/KVM environment. Local Windows prototype cannot honestly prove Cube microVM isolation unless that environment is provided.

## 2026-07-02 Hardware Candidate Note

User showed a laptop configuration screenshot:

- Model shown: 机械革命无界 15X Pro
- CPU shown: 锐龙 AI 9H 365 / 20 threads
- Memory info shown: 2 slots, 5600MHz; total RAM capacity not visible in screenshot
- GPU shown: integrated graphics

Assessment:

- CPU class should be enough for local sandbox feasibility validation, Docker Desktop, WSL2, and a Linux VM.
- Integrated GPU is acceptable because execution sandbox mainly needs CPU/RAM, not a discrete GPU.
- Need to confirm actual RAM capacity:
  - 16GB: enough for basic MVP/Docker validation;
  - 32GB: recommended;
  - 64GB: better for Linux VM + nested virtualization experiments.
- Need to confirm virtualization is enabled in Windows Task Manager / BIOS:
  - AMD calls this SVM / AMD-V.
- For Cube Sandbox inside a Linux VM, nested virtualization must work. This is possible in principle on modern AMD CPUs, but not guaranteed until tested.
- For final production-level Cube Sandbox, a real Linux/KVM server remains more reliable than a Windows laptop VM.

## 2026-07-02 Handoff Summary For New Conversation

User is about to open a new conversation and continue this topic.

Must remember:

- Read this `WORKLOG.md` first in the new conversation.
- The user wants strict alignment with the original R&D plan, not just a demo.
- The current project must be treated as an L1 module capability package, not a complete platform.
- Current implementation is still a prototype with mock platform integration.
- Do not call it final production.
- Major missing hard requirements remain:
  - real Docker/Cube isolation runtime;
  - browser sandbox;
  - host-file isolation proof;
  - resource overrun proof;
  - real egress allowlist enforcement;
  - credential injection;
  - Cube/E2B adapter;
  - real integration with 1.4, 1.5, 1.8, 1.9, 1.10, 1.12.
- The latest added capability is the acceptance framework:
  - `backend/acceptance.py`
  - `GET /api/acceptance`
  - "客观验收检查" section in UI
  - `tests/acceptance_check.py`
- Latest acceptance result:
  - passed: sandbox lifecycle, result collection
  - partial: app-layer timeout, allowlist config
  - blocked: Docker/container isolation, host-file isolation, browser sandbox, Cube Sandbox
- D drive deliverable directory:

```text
D:\agent-sandbox-module
```

- Long-term memory file is only this workspace file:

```text
C:\Users\刘卓\Documents\Codex\2026-06-30\zhe\agent-sandbox-module\docs\WORKLOG.md
```

- `D:\agent-sandbox-module\docs\WORKLOG.md` should remain deleted unless user changes instruction.
- If editing docs/source in workspace, sync needed files to `D:\agent-sandbox-module`, but do not leave WORKLOG in D drive.
- User asked that every meaningful project step update this file immediately.

Suggested first action in new conversation:

1. Read this `WORKLOG.md`.
2. Summarize current status to user.
3. Ask/confirm whether to proceed with local Docker Desktop installation/check, or continue with Linux VM / Cube Sandbox feasibility planning.

## 2026-07-02 Acceptance Check Framework Added

Added:

- `backend/acceptance.py`
- `GET /api/acceptance`
- "客观验收检查" section on the 安全边界 page
- `tests/acceptance_check.py`

Purpose:

- Turn the R&D plan's objective acceptance requirements into visible checks:
  - lifecycle logs;
  - result file collection;
  - real container isolation availability;
  - host-file isolation proof;
  - resource timeout;
  - egress allowlist;
  - browser sandbox;
  - Cube Sandbox readiness.

Important truth:

- Several checks currently report `blocked` or `partial` because Docker/Cube is not available.
- This is intentional and prevents falsely claiming full plan compliance.

Follow-up fix:

- Lifecycle acceptance originally checked the latest task, which could be a failed permission-denial task.
- It now checks the latest successful task first, because `sandbox.result_collected` only appears when execution succeeds.

## Next Step

Recommended next steps:

1. Improve UI further for beginner validation:
   - Add a dedicated "平台链路验证" page.
   - Add one-click demo buttons:
     - 发票核销 demo
     - 超库存预警 demo
     - 权限不足 demo
   - Add plain-language status messages.

2. Add Docker installation/check helper:
   - Only after user confirms installing Docker.
   - Do not silently install system software.

3. If Docker becomes available:
   - Set `runtime.executor` to `docker`.
   - Run `production_check.py`.
   - Verify Docker path.

4. If Cube Sandbox server becomes available:
   - Add `CubeSandboxExecutor`.
   - Keep current executor interface.

Implemented files:

- `backend/mock_platform.py`
- `tests/integration_mock_test.py`

Service now writes `platform_checks` into each task.

## Validation Commands

```powershell
cd D:\agent-sandbox-module
python tests\smoke_test.py
python tests\production_check.py
```

After mock services:

```powershell
python tests\integration_mock_test.py
```

## 2026-07-02 Sandbox Monitoring Page Added

Added:

- `backend/monitor.py`
- `GET /api/monitor`
- `frontend` navigation item and page for `沙箱监控`
- `tests/monitor_test.py`
- refreshed `docs/PLAN_COMPLIANCE.md`
- refreshed `docs/TEST_REPORT.md`

Purpose:

- Give Windows users a visible sandbox-instance view even without Linux/Docker.
- Show per-task instance information:
  - status;
  - actor / role;
  - timeout / memory / CPU limits;
  - cost units;
  - audit count;
  - artifact paths.
- Help the user verify that the module is not just a task submitter, but also a traceable sandbox capability package.

Validation note:

- `tests/monitor_test.py` passes.
- `tests/demo_cases_test.py`, `tests/smoke_test.py`, `tests/integration_mock_test.py`, and `tests/acceptance_check.py` still pass after the new page/API.
- `tests` that write `data/tasks.json` should continue to run serially.
- The D-drive deliverable and the running `127.0.0.1:8765` service were both restarted to the new version, so the browser now sees `平台链路验证` and `沙箱监控`.

## 2026-07-03 Linux Server Real-Isolation Direction

User provided a lab Linux server for continuing beyond the Windows capability-package prototype.

Server details supplied by user:

- Host/IP: `10.60.66.97`
- Hostname: `nlp-Precision-5820-Tower-X-Series`
- SSH port: `22`
- SSH user: `nlp`
- Login: password-based
- OS: Ubuntu 20.04.6 LTS, x86_64
- Sudo: user belongs to sudo group; password required
- Network: external network works; `archive.ubuntu.com` reachable
- Proxy process: `clash-linux` on port `7890`

Current implementation direction:

1. Use the Linux server to validate real Docker-based isolation first.
2. Do not jump directly to Cube/Firecracker/Kata until Docker isolation passes.
3. Deploy the current project to the server.
4. Install or verify Docker.
5. Switch runtime executor from local fallback to Docker.
6. Add real acceptance tests for:
   - container runtime availability;
   - host-file access isolation;
   - CPU/memory/timeout limits;
   - network disabled or allowlist behavior;
   - result collection from container;
   - audit/monitor evidence in UI/API.

Security reminder:

- The user gave a password in chat for convenience. Do not write it into repo files or docs. Recommend changing it after validation.

Project path chosen by user:

```text
/home/nlp/刘卓/执行沙箱/
```

Initial server check result:

- SSH reachable from Windows.
- Sudo works for `nlp`.
- CPU: 20 logical cores.
- Memory: about 62GiB total, about 52GiB available at check time.
- Disk: `/home` has about 208GB available.
- Docker command is not installed yet.
- `/dev/kvm` exists, so later Cube/Firecracker/Kata feasibility is worth checking, but first target remains Docker.

2026-07-03 Docker setup progress:

- Installed Ubuntu package `docker.io`.
- Docker service is enabled and running.
- Docker version: `26.1.3`.
- Added `nlp` to the `docker` group; a new SSH session can run Docker without sudo.
- First Docker execution attempt selected `DockerTemplateExecutor`, proving the app detects Docker.
- First execution failed because Docker Hub image pull for `python:3.12-slim` timed out.
- Direct Docker Hub access times out from the server; local clash proxy on `7890` also reset Docker Hub TLS attempts.
- New plan: build/import a local Python Docker image from Ubuntu mirror reachable by the server, then set `runtime.docker_image` to that local image.
- Built local image `agent-sandbox-python:3.10-local` through `debootstrap` + `docker import`, avoiding Docker Hub dependency.
- Server `config.example.json` was changed to `"executor": "docker"` and `"docker_image": "agent-sandbox-python:3.10-local"`.
- First real container task started but failed because `backend/template_cli.py` did not add `/app` to `sys.path`; fixed by inserting project root before importing `backend.templates`.
- Docker executor was hardened with generated container names and timeout cleanup via `docker rm -f`.
- Acceptance checks were upgraded to run real Docker probes:
  - host file outside mounted paths must not be readable;
  - `/app` read-only mount must not be writable;
  - runaway container must be stopped after timeout;
  - `--network none` must block outbound network attempts.
- `backend/app.py` now supports `SANDBOX_MVP_HOST`; this allows the Linux server demo to bind to `0.0.0.0` while Windows can still default to `127.0.0.1`.
- Cube readiness wording was updated for the Linux server: `/dev/kvm` exists, but Cube Sandbox itself is not installed yet.

Linux server validation result:

- `production_check.py`: passed with `DockerTemplateExecutor`.
- `integration_mock_test.py`: passed.
- `demo_cases_test.py`: passed.
- `monitor_test.py`: passed.
- `acceptance_check.py`: passed with:
  - passed: sandbox lifecycle;
  - passed: result collection;
  - passed: real container isolation;
  - passed: host file isolation;
  - passed: resource timeout;
  - partial: egress allowlist, because Docker `--network none` proves default-deny but domain-level allowlist still needs CubeEgress or an egress proxy;
  - blocked: browser sandbox;
  - blocked: Cube Sandbox, although `/dev/kvm` exists.

Important current truth:

- The project now has real Docker-based isolated execution on the Linux server.
- It still does not have browser sandbox or Cube Sandbox integration.

Linux server web demo:

- Service started from `/home/nlp/刘卓/执行沙箱/`.
- Bound with `SANDBOX_MVP_HOST=0.0.0.0` and `SANDBOX_MVP_PORT=8765`.
- Browser URL from the user's network:

```text
http://10.60.66.97:8765/
```

- `/api/readiness` confirms `DockerTemplateExecutor` with image `agent-sandbox-python:3.10-local`.
- `/api/acceptance` currently reports: 5 passed, 1 partial, 0 failed, 2 blocked.

## 2026-07-03 Leadership Demo Evidence Gap

User pointed out that the current `安全边界 / 客观验收检查` page is too text/report-like:

- It prints status and explanations.
- It does not visibly prove how the function was tested.
- It is not convincing enough for leadership acceptance.

New implementation target:

- Add a dedicated `验收演示` page.
- Each key sandbox capability should be a clickable live proof:
  - Docker runtime proof;
  - Docker isolated task proof;
  - host-file isolation proof;
  - resource timeout proof;
  - network default-deny proof;
  - permission denial proof.
- For each proof, show:
  - what is being verified;
  - expected result;
  - actual command/task executed;
  - actual stdout/stderr or task id/result;
  - pass/fail status.

Purpose:

- Make the module demonstrable to leadership as an evidence-driven capability package, not just a page of claims.

Implemented after this note:

- Added `backend/verification.py`.
- Added `GET /api/verification`.
- Added `POST /api/verification/run`.
- Added frontend page `验收演示`.
- The new page can run each proof live and show:
  - claim;
  - expected result;
  - command/API call;
  - stdout/stderr or task result;
  - pass/fail.
- First full `/api/verification/run` returned 6 passed, 0 failed.
- Fixed a confusing result detail: template payload still said `LocalTemplateExecutor`; executor layer now overwrites `sandbox_runtime` so Docker tasks visibly report `DockerTemplateExecutor`, `docker_container`, image, network, memory, and CPU.

## 2026-07-03 Leadership Demo UI Feedback

User correctly pointed out that the new verification page still looked like printed text/JSON:

- It showed commands and raw evidence.
- This proves things to engineers, but it is not persuasive enough for leadership.
- Need to turn it into a visual acceptance board.

New UI target:

- Keep live verification API as the evidence source.
- Change frontend presentation to show each requirement as:
  - requirement;
  - live attack/probe;
  - sandbox defense;
  - visible result;
  - raw command/evidence hidden under a collapsible details area.
- Make the leadership-facing first view answer: "what was attacked, what blocked it, what passed."

Implemented visual improvement:

- `验收演示` result area was changed from text/JSON-first to a visual proof board.
- Each proof card now shows:
  - requirement being proven;
  - live probe/attack;
  - sandbox defense mechanism;
  - visible pass result;
  - key facts such as Docker version, executor, isolation mode, network mode, stopped container name, missing permissions.
- Raw command and JSON evidence are now hidden under `展开技术证据`, so leadership sees the proof flow first and engineers can still inspect details.

## 2026-07-03 Continue Toward Remaining Requirements

User requested continuing until all original requirements are implemented.

Current remaining requirements after Docker isolation:

1. Domain-level egress allowlist:
   - current status: Docker `--network none` proves default-deny;
   - missing: allow whitelisted domains while rejecting non-whitelisted domains, with visible access evidence.
2. Browser sandbox:
   - missing: browser automation inside an isolated container.
3. Cube Sandbox / E2B adapter:
   - missing: real Cube runtime; server has `/dev/kvm`, so feasibility is promising.
4. Credential injection:
   - missing: real secret injection and non-exposure to task code.
5. Real platform integration:
   - missing: real 1.5/1.9/1.10/1.12 services.

Next implementation order:

1. Implement Docker-level egress gateway first.
2. Show egress gateway in `验收演示`.
3. Then implement browser sandbox.
4. Then add Cube/E2B adapter skeleton and readiness checks.

## 2026-07-03 Docker Egress Gateway Implemented

Added:

- `backend/egress_gateway.py`
- `egress_allowlist_gateway` verification case in `backend/verification.py`
- acceptance integration so `egress allowlist` can become `passed` when the live probe succeeds
- frontend visual proof card for `域名级出站白名单`

Validation design:

1. Create a Docker internal network.
2. Start an `egress-proxy` container on the internal network.
3. Connect the proxy container to the default bridge network so only the proxy has outbound access.
4. Run task/probe containers only on the internal network.
5. Probe results:
   - `http://example.com` through proxy should pass;
   - `http://openai.com` through proxy should be blocked;
   - direct access without proxy should fail because the task container is on an internal network.

This is the first real domain-level egress allowlist validation, beyond simple Docker `--network none`.

Server validation result:

- `egress_allowlist_gateway` live verification passed.
- `http://example.com` through proxy returned `200`.
- `http://openai.com` through proxy returned `403`.
- Direct bypass attempt from the task container failed because the task container only joined an internal Docker network.
- `/api/acceptance` now reports:
  - passed: 6;
  - partial: 0;
  - failed: 0;
  - blocked: 2 (`browser sandbox`, `Cube Sandbox`).

## 2026-07-03 Browser Sandbox Build Diagnosis

User thought the browser image build was stuck; continue normally and do not stop the existing server/demo service.

Checked the Linux server at `10.60.66.97`:

- demo service is still listening on `0.0.0.0:8765`;
- Docker image currently available: `agent-sandbox-python:3.10-local`;
- Debian Chromium rootfs build failed during package configuration, not because the app server was stuck.

Failure details from `/tmp/agent-browser-debian-rootfs/debootstrap/debootstrap.log`:

- `chromium` depends on GTK/dconf pieces;
- `dconf-service` could not configure because a DBus session bus package was missing;
- as a result `dconf-gsettings-backend`, `libgtk-3-common`, `libgtk-3-0`, and `chromium` remained unconfigured.

Next action:

1. Repair or rebuild the Debian browser rootfs with missing DBus/GTK runtime dependencies included.
2. Import it as `agent-sandbox-browser:chromium-local`.
3. Add a live browser verification case that visibly proves:
   - browser runs inside a Docker container;
   - allowed URL can load through the egress gateway;
   - blocked URL is rejected;
   - direct bypass is unavailable from the browser container.

## 2026-07-03 Browser Sandbox Image Ready

Repaired the Debian browser rootfs on the Linux server:

- installed/fixed missing DBus, GTK, and font dependencies;
- verified `chromium --version` inside the repaired rootfs;
- imported the image as `agent-sandbox-browser:chromium-local`.

Smoke test result:

- Docker image list now includes:
  - `agent-sandbox-browser:chromium-local` (~1.31GB);
  - `agent-sandbox-python:3.10-local`;
- Chromium successfully loaded `http://example.com` inside a Docker container with:
  - `--memory 768m`;
  - `--cpus 1`;
  - `--read-only`;
  - writable tmpfs only for `/tmp`, `/run`, `/root`, and `/var/tmp`;
  - dedicated browser user data dir under `/tmp/chrome`;
- proof text `Example Domain` appeared in the real DOM output.

Next action:

1. Add browser verification API case using this image.
2. Route browser outbound access through the existing egress gateway.
3. Show browser sandbox as a visual proof card in the leadership demo UI.
4. Update acceptance from `blocked` to `passed` once live verification succeeds.

## 2026-07-03 Browser Sandbox Verification Wired In

Code changes prepared in the latest server project copy:

- added `browser_sandbox` to the live verification case list;
- implemented a real browser probe that:
  - creates a Docker internal network;
  - starts the existing egress proxy with `example.com` allowlisted;
  - runs `agent-sandbox-browser:chromium-local` with Headless Chromium;
  - keeps browser container constrained with CPU/memory, read-only rootfs, and tmpfs writable paths only;
  - proves `http://example.com` loads through the proxy;
  - proves `openai.com` creates a deny record in proxy logs;
  - proves direct browser bypass without proxy fails;
- connected `/api/acceptance` browser sandbox check to the live browser probe;
- added `runtime.browser_image = agent-sandbox-browser:chromium-local` to config;
- added frontend visual facts for browser sandbox:
  - browser image;
  - allowlisted page loaded;
  - non-allowlisted domain rejected;
  - direct bypass failed;
  - browser network name.

Local syntax checks passed:

- `python -m py_compile backend/verification.py backend/acceptance.py`;
- `node --check frontend/app.js`.

Next action:

1. Sync the changed files to `/home/nlp/刘卓/执行沙箱/`.
2. Restart the server on port `8765`.
3. Run `/api/verification/run` for `browser_sandbox`.
4. Re-run `/api/acceptance`; expected remaining blocked item should be only `Cube Sandbox`.

## 2026-07-03 Browser Sandbox Passed on Server

Synced the browser sandbox verification changes to the Linux server and restarted the demo service on `0.0.0.0:8765`.

Live API validation:

- `POST /api/verification/run {"case_id":"browser_sandbox"}` returned `status: passed`;
- browser image: `agent-sandbox-browser:chromium-local`;
- browser container network: generated internal Docker network such as `agent-browser-8c30cc2c`;
- allowlisted page proof:
  - Chromium DOM output contained `Example Domain`;
- non-allowlisted proof:
  - proxy logs contained deny records for `openai.com`;
- direct-bypass proof:
  - Chromium did not load `Example Domain` without proxy and produced an offline/error page.

Current `/api/acceptance` summary:

- passed: 7;
- partial: 0;
- failed: 0;
- blocked: 1.

Passed requirements now include:

- sandbox lifecycle;
- result collection;
- real Docker container isolation;
- host file isolation;
- resource timeout with CPU/memory limits;
- egress allowlist gateway;
- browser sandbox.

Only remaining blocked item:

- `Cube Sandbox` because `/dev/kvm` exists, but Cube runtime is not installed or connected yet.

## 2026-07-03 Cube Sandbox Preflight

Checked official Cube Sandbox docs:

- Cube Sandbox bare-metal deployment requires x86_64/aarch64 Linux with `/dev/kvm`, root, Docker, internet, RAM >= 8GB, and free disk >= 50GB.
- Ubuntu is supported when glibc >= 2.31.
- `/data/cubelet` must be mounted as XFS because Cube relies on XFS reflink/CoW snapshots.
- Installation starts an E2B-compatible API on port `3000`, WebUI on `12088`, host processes, and MySQL/Redis via Docker Compose.

Server preflight result:

- OS/kernel: Ubuntu 20.04, kernel `5.14.0-1059-oem`, x86_64.
- glibc: `2.31`.
- `/dev/kvm`: present.
- user `nlp`: in `sudo` and `docker` groups.
- Docker: server version `26.1.3`.
- free disk: `/home` has about `208G` free.
- ports `3000` and `12088`: not occupied.
- missing requirement: `/data/cubelet` XFS mount.

Next action:

1. Create a reversible XFS loopback filesystem under `/home` and mount it at `/data/cubelet`.
2. Run Cube official one-click installer in bare-metal/KVM mode.
3. Create or import a Cube code template.
4. Add Cube/E2B live verification into this module once Cube API is responding.

## 2026-07-03 Cube XFS Workspace Prepared

Prepared Cube's required `/data/cubelet` filesystem on the Linux server:

- installed `xfsprogs`;
- created sparse image file:
  - `/home/nlp/cube-sandbox-state/cubelet-xfs.img`;
  - size: `80G`;
- formatted it as XFS with reflink enabled:
  - `mkfs.xfs -m reflink=1`;
- mounted it at:
  - `/data/cubelet`;
- verified:
  - filesystem type: `xfs`;
  - source: `/dev/loop0`;
  - available space: about `80G`.

This avoids repartitioning the lab server and remains reversible by unmounting `/data/cubelet` and deleting the sparse image.

Next action:

- run Cube Sandbox official bare-metal installer with `MIRROR=cn`.

## 2026-07-03 Cube Installer Partially Completed, Network Agent Failed

Ran Cube official bare-metal installer:

```bash
curl -sL https://cnb.cool/CubeSandbox/CubeSandbox/-/git/raw/master/deploy/one-click/online-install.sh | MIRROR=cn bash
```

Result:

- downloaded `cube-sandbox-one-click-v0.4.0.tar.gz` (~228MB);
- installed `docker-compose`;
- extracted Cube package into `/usr/local/services/cubetoolbox`;
- installed systemd units:
  - `cube-sandbox-cube-api.service`;
  - `cube-sandbox-cubemaster.service`;
  - `cube-sandbox-cubelet.service`;
  - `cube-sandbox-network-agent.service`;
  - `cube-sandbox-cube-egress.service`;
  - `cube-sandbox-webui.service`;
  - MySQL/Redis/CoreDNS/CubeProxy services and targets.

Installer quickcheck failed:

- expected unit not active:
  - `cube-sandbox-network-agent.service`.

Current state:

- Cube is partially installed;
- do not claim Cube runtime is passed yet;
- next step is to inspect `systemctl status` and `journalctl` for `cube-sandbox-network-agent.service`.

## 2026-07-03 Cube Root Cause Identified: Kernel Lacks BTF

Inspected Cube network-agent failure.

Important findings:

- `cube-sandbox-network-agent.service` panics immediately.
- `/data/log/network-agent/network-agent-req.log` shows the real cause:
  - `ebpf.NewCollectionWithOptions`;
  - `apply CO-RE relocations`;
  - `load kernel spec`;
  - `no BTF found for kernel version 5.14.0-1059-oem`;
  - `not supported`.
- Current kernel config confirms:
  - `CONFIG_BPF=y`;
  - `CONFIG_BPF_SYSCALL=y`;
  - `CONFIG_DEBUG_INFO_BTF is not set`.

Current Cube service state:

- active:
  - `cube-sandbox-cube-api.service` on port `3000`;
  - `cube-sandbox-webui.service` on port `12088`;
  - `cube-sandbox-cubelet.service`;
  - `cube-sandbox-cubemaster.service`;
  - MySQL, Redis, CoreDNS, CubeProxy;
- inactive/dead:
  - `cube-sandbox-network-agent.service`;
  - `cube-sandbox-cube-egress.service`;
  - `cube-sandbox-cube-egress-net.service`;
  - `cube-sandbox-compute.target`.

Conclusion:

- Cube Sandbox is partially installed, but not usable as a real runtime yet.
- To make Cube pass, the server needs a kernel with BTF support (`/sys/kernel/btf/vmlinux`) or Cube's supported/PVM kernel path, which likely requires installing a different kernel and rebooting.
- Do not claim Cube Sandbox passed until network-agent and compute target are active and a real Cube/E2B sandbox can run code.

## 2026-07-03 Final Verification State After Browser + Cube Attempt

Re-ran live verification on the Linux server:

```bash
POST /api/verification/run {"case_id":"all"}
```

Result:

- passed: 8;
- failed: 0.

Passed visual/live verification cases:

1. `docker_runtime` - Docker real isolation runtime.
2. `docker_task` - task runs through `DockerTemplateExecutor`.
3. `host_file_isolation` - container cannot read unmounted host file and cannot write read-only app mount.
4. `resource_timeout` - runaway container is stopped and cleaned.
5. `network_default_deny` - `--network none` blocks outbound access.
6. `egress_allowlist_gateway` - internal Docker network plus proxy allows `example.com`, blocks non-allowlisted domain, and blocks direct bypass.
7. `browser_sandbox` - real Headless Chromium loads allowlisted page through proxy, non-allowlisted domain is denied, and direct bypass fails.
8. `permission_denial` - missing permission blocks sensitive task.

Current `/api/acceptance`:

- passed: 7;
- partial: 0;
- failed: 0;
- blocked: 1.

The only blocked item is Cube Sandbox:

- Cube is partially installed;
- Cube WebUI responds on `12088`;
- Cube API responds on `3000`;
- network-agent/compute target remain inactive because current kernel lacks BTF:
  - `CONFIG_DEBUG_INFO_BTF is not set`;
  - no `/sys/kernel/btf/vmlinux`;
  - log cause: `no BTF found for kernel version 5.14.0-1059-oem`.

Important caution:

- Finishing Cube likely requires installing/switching to a BTF-capable kernel or Cube-supported/PVM kernel and rebooting the lab server.
- Do not reboot automatically without explicit user approval because this is a shared Linux server and may affect other users.

Current demo URLs:

- L1 sandbox module UI: `http://10.60.66.97:8765/`
- Cube WebUI from installer: `http://10.60.66.97:12088/`
- Cube E2B-compatible API port: `http://10.60.66.97:3000/`

Synced latest long-term memory to:

- local long-term memory file;
- server project `docs/WORKLOG.md`;
- local deliverable `D:\agent-sandbox-module\docs\WORKLOG.md`.

## 2026-07-15 Platform Layer Interface v1

- Analyzed `层间交互逻辑图_v2_1_20260712.html`: the execution sandbox is a basic-layer capability and must only accept routed calls from the business-engine layer.
- Added registered service `execution_sandbox.run_task` and formal endpoints for service discovery, request submission, request/result lookup, and event lookup under `/api/v1/layer-interface`.
- Added Bearer service authentication, caller-layer enforcement, 13-engine allowlist, caller/header consistency checks, real-user resolution, trace-id idempotency, conflict detection, and persisted request records.
- Added immediate result, HTTP 202 acceptance receipt, progress events, and standard rejection responses.
- Kept `/api/tasks` as a standalone demo/compatibility API; platform integration should use the v1 layer interface.
- Server verification passed: missing token -> 401; application-layer call -> 403; s19 receipt -> 202 then Docker success; duplicate trace -> same request; sales-user s04 -> permission rejection before Docker with zero resource cost.
- Automated verification passed on the server: platform interface 8 cases, smoke scenarios s06/s03/s19/all 20 templates, and backend Python compilation.
- Current integration boundary: service identity, account/permission providers, ERP/OA, cost control, and proactive callbacks remain adapters or mocks until the owning modules are connected.

## 2026-07-17 Capability Gap Closure In Progress

- Added Docker-backed formal service paths for generated Python code and allowlisted browser retrieval.
- Added immutable evidence snapshots on request (`retain_snapshot=true`) and company-scope checks (`X-Company-Id`).
- Security parameters remain fixed by the sandbox: no caller-supplied Docker command, default no network for code, allowlist proxy for browser, read-only root filesystem, capability drop, no-new-privileges, PID/CPU/memory/time limits.
- Local compilation and existing platform-interface regression passed; server Docker verification is next.
- Server verification: generated Python code executed successfully in Docker with network disabled and an immutable evidence snapshot. The new formal browser service is implemented but its Chromium parameters were adjusted after an initial startup timeout; final server regression remains required before claiming it as verified.
- Final server browser regression passed. `execution_sandbox.run_browser` dynamically created an internal Docker network, egress proxy, Chromium container, result directory, audit data and immutable snapshot for a submitted allowlisted URL. It returned the controlled page in 3058ms; audit records show the requested page allowed (200) and non-allowlisted Chromium background connections denied (403).
