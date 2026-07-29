# 前端 UI 合并说明

本目录来自 `前端.zip`，仅作为新版 UI 的隔离合并区。

## 当前状态

- 已纳入当前 `Web/workbench/src`，但没有被 `main.js` 或 `App.vue` 引用。
- 不会影响现有登录、上传、对话、项目、知识库等真实后端交互。
- 当前真实接口仍由 `src/services/*.js` 负责。

## 已保护文件

以下文件不得直接被新包覆盖：

```text
src/App.vue
src/main.js
src/services/platform-api.js
src/services/auth-api.js
src/services/workspace-api.js
src/services/knowledge-governance-api.js
src/services/agent-management-api.js
package.json
vite.config.js
```

## 新包风险

新包包含 `router`、`stores`、`api` 等结构，且部分文本存在编码乱码。直接覆盖当前项目会导致：

- 后端真实接口被模拟 API 替换。
- 登录、上传、对话确认、任务查询等链路失效。
- 需要新增 `pinia`、`vue-router` 依赖。
- 当前已经打通的 L4 应用网关交互被绕开。

## 后续融合建议

1. 先迁移纯 UI 组件，例如侧栏、右侧面板、弹窗、样式 token。
2. 每迁移一个组件，都让它继续调用当前 `src/services` 接口。
3. 不允许页面组件直接调用 L1/L2 模块端口。
4. 不允许把 `src/api` 替换成真实接口层。
5. 如果要引入 `router` 或 `pinia`，必须单独评估并做一次完整前端架构调整。

推荐对接关系：

```text
Vue 页面组件
  ↓
src/services/*.js
  ↓
L4 应用网关 8100
  ↓
L2/L1 后端模块
```

