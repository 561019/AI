# 汉和 AI 工作台 L4 原型

基于 Vue 3 + Vite 的三栏业务应用层原型。

## 本地运行

```bash
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

## 当前实现

- 左栏：消息与通知、全部 Projects、账号级综合指挥中心。
- 支持新建 Project 和在当前 Project 内新建对话；创建后自动定位到对应工作空间。
- 所有带历史上下文的对话条目显示环形占用进度；75% 提示偏高、90% 提示即将满载，并可沉淀后续接为新对话。
- 中栏：Project 专属指挥中心、对话、意图确认和受理回执。
- 综合指挥中心采用账号级对话交互，可用自然语言下发统筹、风险、汇报等指令并跳转到对应 Project。
- 右栏：个人能力、当前对话资料、当前 Project 独立知识库。
- 右栏最右侧功能栏：会话数据、Agent、Skill、知识库、文件；进入对话默认打开会话数据。
- 会话数据：区分自动与人工环节，展示追踪编号、停滞卡点、核对依据和可沉淀业务资产。
- Agent/Skill：集团共用与个人自建分开；两类能力均在中心对话中完成创建、微调、停用与恢复。Agent 支持发起升级、推荐升层，Skill 支持发布升档；所有版本、测试和调用记录可追溯。
- 知识库：个人库可由当前对话新建，并支持补材料和维护；集团库的内容查看、补资料、维护与管理责任配权严格分层。拥有内容查看权即自动承担日常维护责任；配权仅能在已有查看权人员中指定责任人，绝不授予或返回库内业务内容。
- 文件：Project 总览可搜索 Project 共享文件与全部会话文件，并可直达来源对话；会话内支持名称搜索、产出文件下载、产出文件和 Project 共享文件引用回对话继续修改。
- 固定 Projects：我的工作汇报、我的队伍。
- 演示账号：负责人、业务员、采购员、财务人员。
- 权限以账号 ID 和权限列表驱动，不在组件中硬编码角色判断。
- 登录页支持演示账号登录、账号创建和退出；注册账号默认仅拥有本人工作汇报权限，正式环境替换为统一身份认证接口。

## 接口预留

正式接入时，演示账号和静态数据应替换为业务应用层接口：

```text
GET  /api/me
GET  /api/me/permissions
POST   /api/gateway/account/v1/sessions          # 登录，返回 access token / session
DELETE /api/gateway/account/v1/sessions          # 退出当前会话
POST   /api/gateway/account/v1/accounts          # 创建账号
GET    /api/gateway/account/v1/me                # 当前账号与组织归属
GET    /api/gateway/account/v1/me/permissions    # 当前账号实时权限
GET  /api/projects
GET  /api/projects/{projectId}/conversations
GET  /api/projects/{projectId}/knowledge-files
GET  /api/conversations/{conversationId}/context-files
POST /api/conversations/{conversationId}/messages
POST /api/tasks/{traceId}/actions
```

账户网关基础地址通过 `VITE_ACCOUNT_GATEWAY_BASE_URL` 配置；前端适配器位于 `src/services/auth-api.js`。正式接入后，登录成功只应以网关返回的当前账号和权限快照为准，前端不得根据岗位名称推断权限。

个人知识库与 Project 知识库必须保持独立类型、独立接口和独立权限校验。

## 知识库权限与治理

知识库的新建、补材料、维护和管理责任配权均由右栏台账进入当前中栏对话；右栏不承载独立管理表单。用户用自然语言描述变更后，中心对话展示确认卡并写入操作回执。配权确认卡只暴露治理编号、责任候选人与审计规则，不返回任何库内业务内容。

- 内容面：`knowledge.group.view` 是集团库内容、库名、文件清单、检索和维护入口的前置条件；没有该权限时，接口不得返回业务内容或内容元数据。
- 维护面：具备内容查看权的用户自动承担日常维护责任，可使用维护入口；`knowledge.group.supplement` 仅额外控制“补材料”写入能力。
- 治理面：`knowledge.group.grant` 只允许登记或调整维护责任人，不包含内容查看权。纯配权管理员只看治理编号、责任关系和审计记录，不能看到库名、文件数、业务资料或检索结果。
- 配权约束：责任人候选人必须先拥有该库的内容查看权。配权接口不得借由 `assigneeId` 新增看权，服务端必须拒绝任何 `contentAccessGranted: true` 的配权请求。

```text
GET  /api/knowledge-bases/{knowledgeBaseId}/content     # 要求内容查看权
POST /api/application/knowledge-governance/commands    # L4 治理与维护命令
{
  operation: create_from_conversation | supplement | maintain | assign_steward,
  accountId,
  knowledgeBaseId,
  conversationId,
  payload: {
    assigneeId?,
    governanceOnly?,
    contentAccessGranted: false,
    prerequisite?: "knowledge.group.view"
  }
}
```

服务端需要分别校验：内容读取、补材料、维护和管理责任配权；同一请求不得同时承担“授予看权”和“指定责任人”两种语义。L4 适配器位于 `src/services/knowledge-governance-api.js`，不直接调用 L2。

## Agent / Skill 对话式管理

- 右侧 Agent 台账提供 `+ 新建 Agent`、微调、发起升级、推荐升层、停用入口；右侧 Skill 台账提供 `+ 新建 Skill`、微调、发布升档、停用入口；恢复作为停用后的自然语言指令。
- 新建、微调与升级/升档均在中心对话完成“自然语言描述 -> 资产去重装配或规则调整 -> 多模型一致性测试 -> 主备模型选择 -> 确认存入台账”的流程。
- 新建与微调均为个人私有版本；Agent 推荐升层、Skill 发布升档后才会成为组织可复用资产，原创建人保留养护责任。

前端只调用 L4 应用层适配器 `src/services/agent-management-api.js`，不直接调用 L2：

```text
POST /api/application/capability-management/commands
{
  operation: create | fine_tune | upgrade | promote | publish | deactivate | restore,
  accountId,
  capabilityId,
  capabilityType: agent | skill,
  conversationId,
  payload
}
```

正式接入时由该 L4 应用接口完成身份、权限与审计校验，再向 L2 编排服务下发执行命令；界面不依赖 L2 的具体实现。
