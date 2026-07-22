# 案例二接口级验收版本

来源：`架构/AI平台架构框架说明_v3_9_20260719.docx`

标题：案例二：多智能体协同代办——本月销售对账的并行核对与逐笔拍板

## 一、可直接输入的对话

在当前框架的对话框或接口测试里使用：

```text
办理本月销售对账：请并行核对我负责项目的回款流水与财务数据、我名下合同登记表、发票一致性；发现疑点逐笔让我拍板，其余自动通过。
```

## 二、结构化后的三项并行任务

1. 回款流水核对
   - 读取本人负责项目的本月回款流水与财务应收数据。
   - 取数能力：`data.search`
   - 计算能力：`rule.calculate`

2. 合同登记表核对
   - 读取本人名下合同登记表。
   - 取数能力：`data.search`
   - 计算能力：`rule.calculate`

3. 发票一致性核对
   - 从外部财务或税务系统取回发票数据。
   - 外部系统能力：`external.api.call`
   - 计算能力：`rule.calculate`

三项互不依赖，可由流程执行引擎判定为并行。

## 三、关键动作确认

本测试版本固定生成两处疑点，模拟文档案例二：

1. 一笔回款金额与合同尾款相差一笔运费。
2. 一张发票抬头不一致。

这两处都不是意图确认，而是关键动作确认：

- 由流程执行引擎汇总疑点。
- 由人机协同模块生成确认卡。
- 付盛贤逐笔拍板。
- 拍板后由数据操作引擎写回对账状态。

## 四、预期调用链

```text
业务应用层 application-gateway
  -> 业务引擎层 engine-gateway
  -> 意图分析引擎 intent-adapter
  -> 大模型调度 model-dispatcher / 原意图模块
  -> 流程执行引擎 workflow-execution
  -> 能力登记中心 capability-registry
  -> 权限模块 permission-adapter
  -> 数据操作引擎 data-operation
  -> 规则计算引擎 rule-adapter
  -> 外部系统对接引擎 external-system-integration
  -> 人机协同 human-collaboration
  -> 数据操作引擎 data-operation 写回
  -> 应用层展示结果与 trace 调用链
```

## 五、运行方式

先启动框架：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\framework\stop_all.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\framework\start_all.ps1
```

再运行本案例接口脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\framework\test_cases\run_case2_sales_reconciliation.ps1
```

脚本会输出：

- 本案例 trace_id
- 每一步接口 HTTP 状态
- 最终 trace 调用链地址
- 本次运行结果文件

运行后查看完整接口传输内容：

```text
http://127.0.0.1:8100/api/v1/traces/{trace_id}/calls
```

也可以打开页面：

```text
http://127.0.0.1:8100/monitor?trace_id={trace_id}
```

## 六、验收重点

- 每个接口是否都有 request 和 response。
- 流程执行引擎是否调用权限模块。
- 三路核对是否体现为三个独立子任务。
- 规则计算是否只做确定性计算，不让大模型心算金额。
- 发现疑点后是否进入人机协同确认。
- 拍板后是否通过 `data.update` 写回。
- 全链路是否使用同一个 `trace_id`。

说明：如果真实交付模块未启动，适配器会返回 `UPSTREAM_UNAVAILABLE`。这代表平台接口已经打到真实模块适配位置；要验证真实业务结果，需要启动对应交付模块并配置 `framework/config/module.env`。
