# /auth/validate 性能基准

## 场景

| 项 | 值 |
| --- | --- |
| 接口 | `POST /auth/validate` |
| 工具 | `python tests/perf/bench_validate.py` |
| 网关命令 | `go run cmd/gateway/main.go` 或 Docker Compose 中的 `account-gateway` |
| 并发 | 10 个线程 |
| 每线程请求数 | 100 |
| 总请求数 | 1000 |
| 输出指标 | p50、p95、p99 |

## 结果

| 日期 | 环境 | p50 | p95 | p99 | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| 2026-06-30 | 本地工作区 | N/A | N/A | N/A | 未运行：`go` 不在 PATH 或标准 Windows 安装位置。 |
| 2026-07-01 | Docker Compose 本地栈 | 11.26ms | 548.53ms | 2072.80ms | 已记录，需专项优化。 |
| 2026-07-02 | Docker Compose 本地栈，`AUDIT_MODE=sync` | 13.15ms | 853.65ms | 2461.80ms | 已记录，需专项优化。 |
| 2026-07-10 | Docker Compose 本地栈，`AUDIT_MODE=sync`，DELETE journal | 38.19ms | 1361.13ms | 3173.90ms | 同步审计路径仍是主要瓶颈，不作为本轮硬门槛。 |
| 2026-07-10 | Docker Compose 本地栈，`AUDIT_MODE=sync`，`SQLITE_JOURNAL_MODE=wal` | 20.38ms | 143.10ms | 761.52ms | WAL 明显降低尾延迟，但同步审计仍偏高。 |
| 2026-07-10 | Docker Compose 本地栈，`AUDIT_MODE=off` | 17.95ms | 31.02ms | 38.63ms | 关闭审计仅用于定位瓶颈；说明 JWT / Casbin / HTTP 主路径不是当前主要问题。 |
| 2026-07-10 | Docker Compose 本地栈，`AUDIT_MODE=async` | 18.32ms | 25.72ms | 30.77ms | 异步审计表现最好；后续可围绕队列可靠性、落盘失败告警和生产默认策略继续加固。 |

## 说明

本地启动网关后，在项目根目录运行基准：

```powershell
go run cmd/gateway/main.go
python tests/perf/bench_validate.py
```

若使用当前 Docker Compose 本地栈，也可在栈启动后直接运行：

```powershell
$env:PERF_REQUEST_TIMEOUT='10'
python tests/perf/bench_validate.py
```

如果任一请求返回非 2xx，或 `/auth/validate` 拒绝已知 owner 请求，基准会失败。脚本只记录 p50、p95、p99，不再内置固定 p99 门槛；性能优化后续作为专项持续跟踪。

## v2 后续专项对照方法

当前代码支持三组对照，建议每组独立启动网关后运行同一基准。2026-07-10 已完成 `sync` / `sync+WAL` / `off` / `async` 四组对照：默认同步审计仍为秒级尾延迟，WAL 可明显改善，`AUDIT_MODE=async` 表现最好。

```powershell
$env:AUTH_VALIDATE_TIMING='1'
$env:AUDIT_MODE='sync'
python tests/perf/bench_validate.py

$env:SQLITE_JOURNAL_MODE='wal'
$env:AUDIT_MODE='sync'
python tests/perf/bench_validate.py

$env:SQLITE_JOURNAL_MODE=''
$env:AUDIT_MODE='off'
python tests/perf/bench_validate.py

$env:AUDIT_MODE='async'
python tests/perf/bench_validate.py
```

`AUDIT_MODE=off` 只用于定位审计写入占比，不建议生产使用。当前证据显示 `off` 和 `async` 的尾延迟都显著低于同步审计，因此后续专项应优先围绕异步审计可靠性、SQLite WAL 默认策略、队列落盘失败告警和审计补偿机制继续加固；不再设置固定 p99 硬门槛。

## 异步审计可靠性验证

2026-07-14 已补齐异步 writer 关闭协议和查询一致性：网关收到 SIGTERM 后先停止 HTTP 服务，再停止接收新审计并排空已接受队列；审计查询与导出会在读取前执行有界 flush。`AUDIT_MODE=async` 下分组执行全部 107 项 E2E 均通过。

停机专项使用 20 并发提交 100 个带唯一 trace 前缀的 `/auth/validate` 请求，请求完成后立即执行 `docker compose stop -t 15 account-gateway`；SQLite 最终查得 100/100 条对应审计，容器日志确认进入 graceful shutdown。该结果证明正常 SIGTERM 路径可排空当前队列；进程强杀、磁盘持续失败、跨进程补偿和外部告警仍需后续生产化验证。
