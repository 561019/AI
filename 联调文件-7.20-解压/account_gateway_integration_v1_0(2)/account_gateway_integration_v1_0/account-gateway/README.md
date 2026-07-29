# account-gateway

`account-gateway` 是账号身份事实服务：统一登录、账号生命周期、租户及组织关系、数字员工身份和共享工具凭证托管。它不再是业务权限的最终决策者；所有 allow/deny 由权限管理模块实时生成，基础模块层业务调用由 `l1-layer-interface` 统一转交。

已迁出的网关接口会返回 HTTP `410 permission_capability_moved`：`/api/ui-permissions`、审批模板与审批运行时策略、岗位标准资源、转授、资源及资源发布。岗位、任职和汇报线仍是网关登记的身份事实；权限管理命令经 `/api/org/*`、`/api/permissions/*` 的兼容代理进入权限模块控制面。

仓库包含端到端测试，pytest fixture 会拉起所需的 Docker 服务。修改网关行为前，建议使用 `make test` 作为一键检查。

## 技术栈

- Go 1.22+
- Casdoor：身份与 OIDC
- Casbin：策略执行
- Docker Compose：本地依赖
- Python 3.11+ 与 pytest：端到端测试

## 目录结构

```text
account-gateway/
  cmd/gateway/             Go 启动入口
  internal/account/        账号生命周期行为
  internal/audit/          审计记录模型、写入器与迁移
  internal/auth/           JWT 与 OIDC 集成
  internal/gateway/        旧 `/auth/validate` 认证兼容适配
  internal/layerapi/       仅接受层接口调用的登记身份事实服务
  internal/policy/         迁移期历史策略兼容代码（不作为正式判权来源）
  infra/casdoor/           Casdoor 本地配置与数据库初始化
  scripts/                 本地辅助脚本
  tests/e2e/               pytest 端到端测试
  tests/mocks/             上游模拟数据与服务
  docs/                    架构、契约与快速启动文档
```

## 运行测试

运行完整端到端测试流程：

```sh
make test
```

`make test` 会调用 `scripts/up.sh`、`pytest tests/e2e` 和 `scripts/down.sh`。`pytest.ini` 设置了 `testpaths = tests/e2e` 与 60 秒超时，`tests/e2e/conftest.py` 会为需要本地服务的测试管理 Docker Compose 生命周期。

只检查 make 目标而不实际执行：

```sh
make -n test
```

输出中应包含 `pytest tests/e2e`。

## 构建与运行

构建全部 Go 包：

```sh
make build
```

本地运行网关：

```sh
make run
```

如果希望在 pytest 之外直接拉起本地依赖：

```sh
docker-compose up
```

清理本地构建产物：

```sh
make clean
```

## 可视化控制台

项目新增 `web/` 前端控制台，用于可视化和操作当前账号网关能力：

- 运行期授权校验
- 账号生命周期
- 凭证托管
- Breakglass 应急账号
- 数字员工
- 审计查询与导出
- 租户与审批 MVP
- 钉钉 / 企微 / HR mock sync

启动前端：

```sh
cd web
npm install
npm run dev
```

默认访问 `http://127.0.0.1:5173`。Vite 会把 `/api`、`/auth`、`/health` 等请求代理到 `http://127.0.0.1:8080`。

## 契约文档

- [架构定位](docs/architecture.md)
- [运行期校验契约](docs/runtime-validation-contract.md)
- [铁律实现映射](docs/iron-rules.md)
- [快速启动](docs/quickstart.md)
- [当前进度与已做工作](docs/current-progress.md)
- [四次阶段工作进度汇报](docs/four-stage-progress-report.md)
- [v2 完成度与至今工作总结](docs/v2-completion-summary.md)
- [v2 后续完善计划与完成记录](docs/v2-next-plan.md)
- [原需求对照审查：需求、架构与接口](docs/requirement-architecture-interface-review.md)
- [岗位架构与权限授权机制对照说明](docs/post-permission-mechanism-alignment.md)
- [聚合联调接口说明](docs/aggregated-integration-api.md)
- [系统架构图 HTML](docs/account-gateway-system-architecture.html)
- [与安全合规模块联调接口说明](docs/security-compliance-integration.md)

## 当前范围

已实现：

- 账号生命周期接口与行为
- 审计记录写入与审计端到端覆盖
- 基于 JWT 的 `/auth/validate` 运行期校验
- 基于 Casbin 的策略执行与种子策略加载
- Casdoor OIDC 登录回调与本地 mock 模式
- 凭证托管、breakglass、数字员工、租户、审批、岗位权限、资源目录、数据登记和聚合联调接口 MVP
- 钉钉 / 企微 / HR mock sync 入口和租户详情查询路由
- 独立权限模块兼容接入：`PERMISSION_MODE=local|shadow|remote`。`shadow` 返回旧结果并记录差异，`remote` 只使用独立权限服务且故障时默认拒绝。

## 独立权限模块切换

独立权限服务默认地址为 `http://127.0.0.1:8001`，可通过 `PERMISSION_URL` 修改。迁移顺序为：

1. `PERMISSION_MODE=local`：保持当前网关决策。
2. `PERMISSION_MODE=shadow`：网关返回本地决策，同时调用权限服务并记录差异；组织和权限聚合管理接口写入权限服务。
3. `PERMISSION_MODE=remote`：网关保留 JWT、数字员工和 breakglass 前置检查，业务权限统一调用权限服务。超时、异常或服务不可达返回 503 和 `allow=false`，不会回退到本地放行。

兼容 `/auth/validate` 会把旧请求头映射为权限服务 JSON；旧请求没有新字段时使用 `source_service=account_gateway`、`target_service=legacy_runtime`、`data_label=normal`、`data_state=active`。

后续生产化：

- 真实 HR / 钉钉 / 企微 connector
- 四类审批正式拆分与制度模板
- 真实资产池、版本锁定和交接治理界面
- 运行期性能专项、安全运营和生产部署加固
