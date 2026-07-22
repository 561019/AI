# 最小平台框架骨架

包含三个层接口、能力登记、SQLite 任务状态中心，以及意图、流程、权限和规则计算的最小适配服务。

本版本用于接口和调用链验收，不是生产实现。权限和规则服务使用明确标识的测试实现；后续将适配真实交付模块。

```powershell
$env:CODEX_PYTHON='完整 Python 路径'
.\framework\start_all.ps1
python acceptance\run_acceptance.py --mode live --config acceptance\config.local.json
.\framework\stop_all.ps1
```

CI 或一次性验收可使用 `python -m framework.run_cluster` 在一个父进程中统一管理全部子服务。
