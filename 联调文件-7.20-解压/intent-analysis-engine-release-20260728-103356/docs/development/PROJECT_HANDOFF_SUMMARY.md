# 意图分析引擎项目交接总结

更新时间：2026-07-09

本文用于下一次新会话快速加载项目上下文。新会话建议优先阅读本文，再按需查看 `docs/` 下的原始研发方案、真实需求关联说明和平台四层架构图。

## 1. 当前结论

项目已经完成一个可运行的意图分析引擎 MVP，包含后端 FastAPI 服务、PostgreSQL 数据基础、Milvus 向量库接入、三层意图分析编排、统一 TaskList 输出、HTTP API、研发测试控制台、e2e 测试集和 Docker Compose 部署。

当前 Docker Compose 部署已验证通过，以下服务均已启动并处于 healthy：

- `backend`
- `frontend`
- `postgres`
- `milvus`
- `etcd`
- `minio`

已验证：

- `GET /health` 返回 `ok`
- `GET /health/ready` 返回 database 和 Milvus 均 `ok`
- `frontend` 在 `http://localhost:5173` 返回 `200 OK`
- PostgreSQL `pg_isready` 通过
- Milvus `/healthz` 返回 `OK`
- `/api/v1/intent/analyze` 对规则命中文本可返回 Level1 TaskList

## 2. 必须遵守的关键决策

1. 严格遵守原始 `docs` 中的架构和业务边界：
   - `意图分析引擎研发方案 v0.3`
   - `意图分析引擎和真实需求关联说明 v0.1`
   - `平台四层架构图`
2. 意图分析引擎只负责判断意图、抽取/组织任务清单，不执行业务任务。
3. 所有判断最终统一输出 `TaskList`，禁止直接返回业务执行结果。
4. 所有 AI 模型调用必须经过 `ModelGateway`，禁止在业务模块中直接硬编码模型调用。
5. Level1 只做明确规则匹配，不调用 Embedding、LLM 或其他业务引擎。
6. Level2 只做语义理解、候选匹配和置信度计算，不调用 Level3，也不执行业务。
7. Level3 只做复杂意图识别、多任务拆分、参数抽取和缺失参数发现，输出必须符合 `TaskList` Schema。
8. `intent_record` 记录最终意图判断过程，作为分析链路审计基础。
9. HTTP 接口统一响应格式为：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

## 3. 整体架构思路

系统遵循平台四层架构中的职责划分：

- L4 调用入口：通过 HTTP API 接收外部请求。
- L2 接口控制模块：当前由 FastAPI route + service dependency 组合完成入口控制。
- 意图分析引擎：内部统一调度 Level1、Level2、Level3。
- L1 流程管控：当前阶段只输出 TaskList，暂不接任务执行编排。
- 其他业务引擎：只作为 `target_engine` 被识别和写入任务清单，不被调用。

核心分析流程：

```text
用户输入
  -> IntentAnalyzer
  -> Level1 RuleMatcher
      confidence >= RULE_THRESHOLD -> TaskList
  -> Level2 SemanticMatcher
      confidence >= SEMANTIC_THRESHOLD -> TaskList
  -> Level3 LLMIntentAnalyzer
      -> TaskList 或 need_confirmation
  -> IntentRecordService 写入最终判断记录
  -> HTTP API 返回统一响应
```

## 4. 已完成模块

### 4.1 项目基础结构

已创建并使用以下目录：

- `backend/`：FastAPI 后端
- `frontend/`：React + TypeScript 研发测试控制台
- `database/`：初始化 SQL、迁移说明、Milvus 说明
- `tests/`：后端单元测试和 e2e 测试
- `docs/`：原始文档和研发交接文档

### 4.2 数据库层

PostgreSQL 已实现核心表：

- `function_registry`：功能登记库
- `rule_mapping`：一级规则映射库
- `intent_record`：意图判断记录表

相关文件：

- `backend/app/models/function_registry.py`
- `backend/app/models/rule.py`
- `backend/app/models/judgment_record.py`
- `backend/app/db/session.py`
- `database/init/001_schema.sql`
- `database/init/002_seed_data.sql`

### 4.3 功能登记库 Repository / Service

已实现：

- `create()`
- `get_by_code()`
- `list_functions()`
- `search_by_category()`
- 注册功能
- 查询功能
- 校验功能状态

相关文件：

- `backend/app/repositories/function_registry_repository.py`
- `backend/app/services/function_registry_service.py`

### 4.4 Level1 规则匹配引擎

已实现：

- 关键词匹配
- 正则匹配
- 优先级排序
- 置信度计算
- 查询功能登记库
- 输出统一结果

相关文件：

- `backend/app/services/rule_engine/matcher.py`
- `backend/app/services/rule_engine/repository.py`
- `backend/app/schemas/rule_engine.py`

### 4.5 意图判断记录层

已实现：

- 创建判断记录
- 按 ID 查询
- 列表查询
- 按用户查询
- 按分析等级查询
- Level1/总入口最终记录写入

相关文件：

- `backend/app/repositories/intent_record_repository.py`
- `backend/app/services/intent_record_service.py`

### 4.6 Level1 编排服务

已实现 `Level1IntentAnalyzer`，串联：

- `RuleMatcher`
- `FunctionRegistryService`
- `IntentRecordService`
- `TaskListBuilder`

相关文件：

- `backend/app/services/intent_analyzer/level1_analyzer.py`

### 4.7 TaskList 统一任务清单

已定义统一输出 Schema：

- `TaskItem`
- `TaskList`

已实现 `TaskListBuilder`，用于将意图判断结果转换为统一任务清单。

相关文件：

- `backend/app/schemas/task.py`
- `backend/app/services/task_builder/builder.py`

### 4.8 Level2 语义分析引擎

已实现：

- `SemanticMatcher.analyze(text)`
- `embed_text()`
- `search_candidates()`
- `rank_candidates()`
- TopK 候选输出
- Milvus Repository 抽象

相关文件：

- `backend/app/services/semantic_engine/matcher.py`
- `backend/app/repositories/vector_repository.py`
- `backend/app/schemas/semantic.py`
- `backend/app/scripts/init_semantic_vectors.py`

### 4.9 Model Gateway

已实现统一模型调用层，支持：

- `embedding(texts)`
- `rerank(query, candidates)`
- `chat(messages)`

支持 OpenAI 兼容接口和本地模型 HTTP 接口，通过 `.env` 配置。

相关文件：

- `backend/app/integrations/models/base.py`
- `backend/app/integrations/models/model_gateway.py`
- `.env.example`

关键配置：

```env
MODEL_API_URL=http://localhost:8001/v1
MODEL_API_KEY=
EMBEDDING_MODEL=bge-m3
RERANK_MODEL=bge-reranker-v2-m3
LLM_MODEL=qwen-32b
RULE_THRESHOLD=0.9
SEMANTIC_THRESHOLD=0.75
```

### 4.10 Level3 LLM 意图理解模块

已实现：

- 复杂意图识别
- 多任务拆分
- 参数抽取
- 缺失参数发现
- Prompt 模板
- LLM JSON 解析
- JSON 解析失败自动修复一次
- 修复失败返回 `NeedConfirmationResult`

相关文件：

- `backend/app/services/llm_engine/analyzer.py`
- `backend/app/prompts/intent_analysis_prompt.txt`
- `backend/app/schemas/llm.py`

### 4.11 完整 IntentAnalyzer 总入口

已实现三层调度：

```text
Level1 -> Level2 -> Level3
```

行为：

- Level1 达到 `RULE_THRESHOLD`，直接输出 TaskList。
- Level1 不达标，进入 Level2。
- Level2 达到 `SEMANTIC_THRESHOLD`，输出 TaskList。
- Level2 不达标，进入 Level3。
- 最终判断写入 `intent_record`。

相关文件：

- `backend/app/services/intent_analyzer/analyzer.py`
- `backend/app/services/intent_analyzer/__init__.py`

### 4.12 HTTP API

已实现：

- `POST /api/v1/intent/analyze`
- `GET /api/v1/intent/history`
- `GET /health`
- `GET /health/ready`
- 兼容保留旧占位接口：`POST /api/intent-analysis`

相关文件：

- `backend/app/api/routes/intent.py`
- `backend/app/api/routes/health.py`
- `backend/app/api/router.py`
- `backend/app/main.py`
- `backend/app/schemas/intent_http.py`

### 4.13 研发测试控制台

已实现 React + TypeScript 测试工具，只用于验证意图分析能力。

功能：

- 输入文本
- 输入用户 ID
- 输入会话 ID
- 调用 `/api/v1/intent/analyze`
- 显示用户输入、判断等级、匹配功能、TaskList、置信度、耗时、记录 ID

相关文件：

- `frontend/src/pages/IntentConsole.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/styles/global.css`
- `frontend/src/vite-env.d.ts`

访问地址：

```text
http://localhost:5173
```

### 4.14 测试集和报告

已实现 100 条 e2e 测试集：

- 规则命中：30
- 语义命中：30
- 复杂 LLM：20
- 缺参数：10
- 无意义文本：10

测试统计：

- Level1 比例：30%
- Level2 比例：30%
- Level3 比例：40%
- 准确率：100%
- 平均耗时：约 4 ms 级别，具体以报告为准

相关文件：

- `tests/e2e/intent_analysis_cases.py`
- `tests/e2e/test_intent_analysis_e2e.py`
- `tests/e2e/reports/intent_analysis_e2e_report.md`
- `tests/e2e/reports/intent_analysis_e2e_report.json`

最近全量测试结果：

```text
375 passed, 3 warnings
```

### 4.15 Docker Compose 部署

已实现并验证：

- backend
- frontend
- postgres
- milvus
- etcd
- minio

相关文件：

- `docker-compose.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`

部署验证中处理过的环境问题：

- Docker Desktop 初始卡在 `starting`。
- 执行 `wsl --update` 后，重启 Docker Desktop，Docker Engine 恢复为 `running`。
- 首次拉取 `python:3.12-slim`、`node:22-alpine` 时 Docker Hub token 请求超时。
- 单独执行 `docker pull python:3.12-slim` 和 `docker pull node:22-alpine` 后，Compose 构建启动成功。

## 5. 当前可用命令

### 5.1 本地后端测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/backend
```

### 5.2 e2e 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e
```

### 5.3 全量测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

### 5.4 前端构建

```powershell
cd frontend
npm.cmd run build
```

### 5.5 Docker 部署

```powershell
cd D:\AIProjects\intent-analysis-engine
docker compose config
docker compose up -d --build
docker compose ps
```

### 5.6 部署健康验证

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/health/ready
Invoke-WebRequest http://localhost:5173 -UseBasicParsing
docker compose exec -T postgres pg_isready -U intent -d intent_analysis
docker compose exec -T milvus curl -f http://127.0.0.1:9091/healthz
```

### 5.7 停止部署

```powershell
docker compose down
```

## 6. 重要文件修改记录

### 后端核心

- `backend/app/core/config.py`
  - 增加数据库、Milvus、模型网关、阈值配置。
- `backend/app/db/session.py`
  - 实现 SQLAlchemy engine、SessionLocal、`get_db()`。
- `backend/app/models/`
  - 增加 FunctionRegistry、RuleMapping、IntentRecord ORM。
- `backend/app/repositories/`
  - 增加功能登记库、意图记录、向量库访问层。
- `backend/app/services/rule_engine/`
  - 实现 Level1 规则匹配。
- `backend/app/services/semantic_engine/`
  - 实现 Level2 语义匹配。
- `backend/app/services/llm_engine/`
  - 实现 Level3 LLM 分析。
- `backend/app/services/intent_analyzer/`
  - 实现 Level1 编排和完整三层总入口。
- `backend/app/services/task_builder/`
  - 实现统一 TaskList 构建。
- `backend/app/integrations/models/`
  - 实现 Model Gateway。
- `backend/app/api/routes/intent.py`
  - 新增正式 HTTP API。
- `backend/app/api/routes/health.py`
  - 新增 `/health` 和 `/health/ready`。
- `backend/app/main.py`
  - 挂载顶层 health 路由和 `/api` 路由。

### 前端核心

- `frontend/src/api/client.ts`
  - 切换到正式 `/api/v1/intent/analyze`。
- `frontend/src/pages/IntentConsole.tsx`
  - 实现研发测试控制台。
- `frontend/src/styles/global.css`
  - 增加控制台布局和结果展示样式。
- `frontend/package.json`
  - 构建脚本调整为 `tsc --noEmit && vite build`。
- `frontend/package-lock.json`
  - 锁定前端依赖。
- `frontend/tsconfig*.json`
  - 修复 Vite/Node 类型配置。

### 部署

- `docker-compose.yml`
  - 增加 6 个服务。
  - 增加所有服务 healthcheck。
  - 增加服务依赖健康条件。
- `backend/Dockerfile`
  - Python 3.12 FastAPI 镜像构建。
- `frontend/Dockerfile`
  - 使用 `npm ci`，启动 Vite 开发服务供研发测试。

### 测试

- `tests/backend/test_intent_analyzer.py`
  - 覆盖完整三层总入口。
- `tests/backend/test_intent_http_api.py`
  - 覆盖 HTTP API 契约。
- `tests/backend/test_health.py`
  - 覆盖 `/health` 和 readiness。
- `tests/e2e/`
  - 100 条意图分析 e2e 测试集和自动报告。

## 7. 当前已知限制和注意事项

1. Docker Compose 当前不包含真实模型服务。
   - Level1 规则命中请求可直接成功。
   - Level1 未命中时会进入 Level2，需要 `MODEL_API_URL` 对应的 Embedding 服务。
   - 如果未启动模型服务，API 会返回 `Model gateway request failed: /embedding`。
2. Milvus 服务已健康，但生产可用的向量数据需要执行语义向量初始化脚本。
   - 相关脚本：`backend/app/scripts/init_semantic_vectors.py`
3. e2e 测试为了稳定性，通过依赖覆盖使用确定性测试 Analyzer，不依赖真实模型或 Milvus 搜索结果。
4. Docker 数据卷持久化后，`database/init/*.sql` 只在首次创建 Postgres 数据目录时执行。
   - 如果修改初始化 SQL，需要重建卷或手动迁移。
5. 当前数据库种子功能代码使用 `FUNC_*` 风格，例如 `FUNC_REPORT_GENERATION`。
   - 单元测试中部分 mock 使用 `REPORT_CREATE` 等语义化代码。
   - 后续若要和真实 L1/L2/L3 业务引擎打通，应统一 function_code 命名规范。
6. Windows PowerShell 直接写中文 JSON 请求时可能出现编码问题。
   - 部署验证中使用 Unicode 转义请求可正常命中规则。

## 8. 推荐下一步待办

### P0：真实模型服务接入

- 确认 `MODEL_API_URL` 指向真实 OpenAI 兼容或本地模型服务。
- 验证 `/embeddings` 或 `/embedding`。
- 验证 `/chat/completions` 或 `/chat`。
- 将模型服务加入 Compose，或在部署文档中明确外部依赖。

### P0：Milvus 向量数据初始化

- 使用 `function_registry` 中的 `function_name`、`description`、`example_sentences` 生成 embedding。
- 写入 Milvus collection。
- 验证 Level2 对规则未命中文本可返回候选功能。

### P1：function_code 规范统一

- 确认最终标准代码是 `FUNC_REPORT_GENERATION` 还是 `REPORT_CREATE`。
- 统一数据库种子、测试数据、Prompt 示例、TaskList 示例和后续 L1 编排接口。

### P1：生产数据库迁移机制

- 当前已有 Alembic 基础结构和数据库初始化 SQL。
- 后续应明确生产环境以 Alembic 为准，还是以 `database/init` 为准。
- 推荐生产环境使用 Alembic 管理 schema 变更，`database/init` 仅用于本地/测试首启。

### P1：前端控制台增强

- 增加历史记录查询页签，调用 `/api/v1/intent/history`。
- 增加错误结果展示，如模型服务未启动、need_confirmation。
- 增加示例输入按钮，避免编码问题影响人工验证。

### P2：可观测性

- 增加结构化日志。
- 增加 request_id / conversation_id 链路追踪。
- 增加模型调用耗时、Milvus 查询耗时、各 Level 命中情况统计。

### P2：CI/CD

- 增加测试命令流水线。
- 增加 Docker build 检查。
- 增加 Compose health 验证脚本。

## 9. 新会话建议加载顺序

1. 读取本文：`docs/development/PROJECT_HANDOFF_SUMMARY.md`
2. 读取原始设计文档：
   - `docs/意图分析引擎研发方案_v0_3_20260702.docx`
   - `docs/意图分析引擎和真实需求关联说明_v0_1_20260704.docx`
   - `docs/架构图.jpg`
3. 查看核心入口：
   - `backend/app/services/intent_analyzer/analyzer.py`
   - `backend/app/api/routes/intent.py`
   - `backend/app/schemas/task.py`
4. 查看部署状态：
   - `docker-compose.yml`
   - `backend/app/api/routes/health.py`
5. 查看测试能力：
   - `tests/e2e/test_intent_analysis_e2e.py`
   - `tests/e2e/reports/intent_analysis_e2e_report.md`

## 10. 一句话项目状态

当前项目已经从架构设计推进到可部署、可测试、可通过 Level1 完成真实 HTTP 意图分析的 MVP；下一阶段的关键是接入真实模型服务、初始化 Milvus 向量数据，并统一生产 function_code 标准。
