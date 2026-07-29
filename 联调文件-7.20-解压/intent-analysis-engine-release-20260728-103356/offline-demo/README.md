# Intent Analysis Engine 离线演示

入口文件：

```text
offline-demo/intent-offline-demo.html
```

使用方式：

1. 在文件管理器中打开项目目录。
2. 双击 `offline-demo/intent-offline-demo.html`。
3. 浏览器中直接演示，无需 Docker、backend、Postgres、Milvus 或网络。

适合汇报的输入：

```text
销售提成
帮我看看销售人员奖金怎么算
库存低于 提醒我
库存低于100时提醒我
把上个月各区域销售数据整理出来，算提成，再生成凭证
生成经营分析报告
```

说明：

- 这是离线演示版，内置轻量规则和语义匹配模拟。
- 展示重点是 Intent Analysis Engine 的命中层级、标准 TaskList、目标引擎选择和缺失输入澄清。
- 不调用真实业务执行引擎。
- 不调用真实 BGE、Milvus 或 LLM。
