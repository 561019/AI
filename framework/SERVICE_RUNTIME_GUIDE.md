# 项目启动与关闭说明

本文档适用于当前联调项目的前端 Workbench、后端服务集群、SQLite 数据库和本地文件对象。

## 重要规则

- 同一时间只能启动一组后端服务集群。
- 后端必须使用 `framework\start_all.ps1` 启动，不要同时启动 `framework.run_cluster` 或单独的 `framework.run_services`。
- 后端必须使用 `framework\stop_all.ps1` 关闭，不能只依赖旧的 PID 文件。
- 服务运行期间不要删除 `platform_data.db`、`-wal` 或 `-shm` 文件。
- 后端启动脚本会先停止旧的框架服务进程，再启动新的一组服务，用于避免端口冲突和 SQLite 写入竞争。

## 数据存储位置

```text
SQLite 数据库：
framework\data\foundation_data\platform_data.db

SQLite WAL 文件：
framework\data\foundation_data\platform_data.db-wal
framework\data\foundation_data\platform_data.db-shm

上传文件：
framework\data\foundation_data\objects\uploads\

AI 生成文件：
framework\data\foundation_data\objects\generated\

后端日志和 PID 文件：
framework\.run\
```

## 启动后端服务

打开 PowerShell，执行：

```powershell
cd C:\Users\21964\Documents\联调
.\framework\start_all.ps1
```

脚本会执行以下操作：

1. 查找并停止所有旧的 `framework.run_services` 服务进程。
2. 只初始化一次共享 SQLite 数据库结构和 WAL 配置。
3. 为每个后端服务启动一个进程。
4. 将进程 ID 写入 `framework\.run\*.pid`。
5. 将标准输出和错误输出写入 `framework\.run\*.out.log` 和 `framework\.run\*.err.log`。

命令完成后等待几秒，再检查关键服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
Invoke-RestMethod http://127.0.0.1:8200/health
Invoke-RestMethod http://127.0.0.1:8300/health
Invoke-RestMethod http://127.0.0.1:8031/health
Invoke-RestMethod http://127.0.0.1:8050/health
Invoke-RestMethod http://127.0.0.1:8060/health
```

每个接口都应返回 `status = ok`。

关键端口：

```text
8100  L4 应用网关
8200  L2 引擎网关
8031  L2 数据操作引擎
8300  L1 基础网关
8060  L1 基础数据模块
```

## 启动前端 Workbench

打开第二个 PowerShell 窗口，执行：

```powershell
cd C:\Users\21964\Documents\联调\Web\workbench
npm.cmd run dev
```

打开 Vite 输出的地址，通常是：

```text
http://127.0.0.1:5173
```

使用前端期间请保持该窗口运行。关闭该窗口只会停止 Vite 开发服务器，不会停止后端服务集群。

## 正常关闭

### 关闭前端

在运行 Vite 的 PowerShell 窗口中按：

```text
Ctrl+C
```

### 关闭后端

在任意 PowerShell 窗口执行：

```powershell
cd C:\Users\21964\Documents\联调
.\framework\stop_all.ps1
```

脚本会通过进程命令行、PID 文件和框架端口查找服务，能够处理没有成功绑定端口的残留服务。

验证后端是否已经关闭：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match '(^|\s)-m\s+framework\.run_services(\s|$)' } |
  Select-Object ProcessId, ParentProcessId, CommandLine
```

不应返回任何进程记录。

## 安全重启后端

后端代码发生变化，或者服务状态不确定时，执行以下顺序：

```powershell
cd C:\Users\21964\Documents\联调
.\framework\stop_all.ps1
.\framework\start_all.ps1
```

不要在多个终端中同时运行 `start_all.ps1`。

## 故障排查

### 查看服务日志

```powershell
Get-Content .\framework\.run\application.err.log -Tail 100
Get-Content .\framework\.run\engine.err.log -Tail 100
Get-Content .\framework\.run\data_operation.err.log -Tail 100
Get-Content .\framework\.run\foundation_data.err.log -Tail 100
```

### 查看端口占用进程

```powershell
netstat -ano | Select-String ':8100|:8200|:8031|:8300|:8060'
```

如果命令返回 PID，可以继续查看进程详情：

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId = <PID>" |
  Select-Object ProcessId, ParentProcessId, Name, CommandLine
```

### 处理重复服务或 SQLite 写入错误

常见现象包括端口已被占用、`database is locked`，或者写入时上游连接被关闭。

按以下顺序执行：

```powershell
cd C:\Users\21964\Documents\联调
.\framework\stop_all.ps1
Start-Sleep -Seconds 2
.\framework\start_all.ps1
```

然后重新执行五个健康检查。不要通过手动删除 SQLite WAL 文件来恢复服务。

## 验证数据链路

联调测试期间优先通过应用网关查询，不要在服务运行时直接操作 SQLite：

```text
http://127.0.0.1:8100/api/v1/data/records?dataset=projects
http://127.0.0.1:8100/api/v1/data/records?dataset=conversations
http://127.0.0.1:8100/api/v1/data/records?dataset=uploaded_files
http://127.0.0.1:8100/api/v1/data/records?dataset=generated_files
http://127.0.0.1:8100/api/v1/data/records?dataset=storage_objects
```

发送对话请求时，保留返回的 `trace_id`，然后查询：

```text
http://127.0.0.1:8100/api/v1/runtime/session/{trace_id}
http://127.0.0.1:8100/api/v1/traces/{trace_id}/calls
http://127.0.0.1:8100/api/v1/traces/{trace_id}/data-access
```

这些接口可以查看同一业务操作对应的任务、文件、服务间调用和数据访问决策。
