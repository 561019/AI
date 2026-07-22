from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleSpec:
    code: str
    layer: str
    name_cn: str
    port: int
    interface: str
    delivery_root: str
    integration_status: str
    notes: str
    capabilities: tuple[str, ...]


# L2 业务引擎层：架构图口径为十四个业务引擎。
# 其中意图分析、流程执行、内容产出、规则计算已在 core.seed_capabilities 中作为深度接入能力登记；
# 这里登记其余需要标准适配器承接的业务引擎。
BUSINESS_MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        "document-table-parsing",
        "business_engine",
        "文档表格解析引擎",
        8036,
        "/api/v1/document-table/instructions",
        "联调文件-7.20-解压/HanHe/HanHe/Documentparsing",
        "adapter_registered",
        "按架构图 v2.7 归入 L2 业务引擎层，负责文档解析、表格抽取与文档包生成。",
        ("document.parse", "document.table.extract", "document.package.build"),
    ),
    ModuleSpec(
        "data-operation",
        "business_engine",
        "数据操作引擎",
        8031,
        "/api/v1/data/instructions",
        "联调文件-7.20-解压/2.4-2.12模块和联调--陈宗贤/模块和联调--陈宗贤/数据操作引擎_联调包_v0_2_20260719",
        "adapter_registered",
        "L2 业务数据操作引擎；负责业务数据整合、增删改查、聚合和追踪，物理存取下沉到 L1 数据模块。",
        ("data.search", "data.persist", "data.trace", "data.read", "data.create", "data.update", "data.delete", "data.aggregate"),
    ),
    ModuleSpec(
        "analysis-prediction",
        "business_engine",
        "分析预测引擎",
        8030,
        "/api/v1/analysis/instructions",
        "联调文件-7.20-解压/2.6分析预测引擎(1)/分析预测引擎",
        "adapter_registered",
        "真实交付入口为 POST /v1/analysis-jobs/evaluate。",
        ("analysis.financial_statement", "analysis.price_forecast", "analysis.business_metric"),
    ),
    ModuleSpec(
        "monitoring-reminder",
        "business_engine",
        "监控提醒引擎",
        8034,
        "/api/v1/monitoring/instructions",
        "联调文件-7.20-解压/监控提醒引擎_v0.8/monitor_reminder_engine_v08_integration",
        "adapter_registered",
        "L2 监控项、提醒、待办、升级和恢复处理引擎。",
        (
            "monitor.item.register", "monitor.item.update", "monitor.item.enable", "monitor.item.pause",
            "monitor.item.resume", "monitor.item.disable", "reminder.handle",
            "reminder.confirm.record", "reminder.escalate.record", "reminder.recover.record",
            "monitor.trace.query",
        ),
    ),
    ModuleSpec(
        "project-management",
        "business_engine",
        "项目管理引擎",
        8033,
        "/api/v1/projects/instructions",
        "联调文件-7.20-解压/项目管理引擎_v0.6(1)(1)/project_management_engine_v06_integration",
        "adapter_registered",
        "真实交付入口为 POST /api/v1/l2/internal/messages。",
        (
            "project.register.simple", "project.register.major", "project.approval.result.record",
            "project.member.add", "project.member.remove", "project.member.query", "project.member.update",
            "project.query", "project.trace.query", "project.list.query", "project.closure.execute",
            "project.archive.catalog.query", "project.archive.authorization.record",
            "project.archive.authorized.query", "project.archive.authorization.query",
            "project.grade.change.request", "project.grade.change.result.record",
            "project.task.progress.record", "project.task.final.callback", "project.task.query",
        ),
    ),
    ModuleSpec(
        "external-system-integration",
        "business_engine",
        "外部系统对接引擎",
        8037,
        "/api/v1/external-systems/instructions",
        "联调文件-7.20-解压/待接入/外部系统对接引擎",
        "adapter_placeholder",
        "架构图 L2 第三阶段引擎；目前预留标准接口与适配器位置。",
        ("external.system.invoke", "external.api.call", "external.callback.handle"),
    ),
    ModuleSpec(
        "knowledge-qa",
        "business_engine",
        "知识库问答引擎",
        8038,
        "/api/v1/knowledge-qa/instructions",
        "联调文件-7.20-解压/2.8-2.9交付资料/engines/local_knowledge_base_v0_1",
        "adapter_registered",
        "L2 问答办理引擎；读取 L1 知识库、检索重排等基础能力后形成业务回答。",
        ("knowledge.query", "knowledge.qa.answer", "knowledge.qa.contextual_answer"),
    ),
    ModuleSpec(
        "digital-asset",
        "business_engine",
        "数字资产引擎",
        8032,
        "/api/v1/assets/instructions",
        "联调文件-7.20-解压/2.4-2.12模块和联调--陈宗贤/模块和联调--陈宗贤/数字资产引擎_联调包_v0_2_20260719_交付版",
        "adapter_registered",
        "只管智能体、技能、知识库三类数字资产，不包含业务数据。",
        (
            "asset.create", "asset.update", "asset.delete", "asset.query",
            "skill.model_evaluation.register", "skill.development.request", "skill.implementation.register",
            "knowledge_source.register", "knowledge_source.result.register",
        ),
    ),
    ModuleSpec(
        "knowledge-map",
        "business_engine",
        "知识地图引擎",
        8039,
        "/api/v1/knowledge-map/instructions",
        "联调文件-7.20-解压/待接入/知识地图引擎",
        "adapter_placeholder",
        "架构图 v2.7 新增 L2 引擎；负责按个人知识地图选择现成技能、智能体、知识库或共享资源。",
        ("knowledge_map.create", "knowledge_map.update", "knowledge_map.select_resource", "knowledge_map.query"),
    ),
    ModuleSpec(
        "multimedia-generation",
        "business_engine",
        "多媒体生成引擎",
        8035,
        "/api/v1/multimedia/instructions",
        "联调文件-7.20-解压/2.8-2.9交付资料/engines/multimedia_engine_v1_1",
        "adapter_registered",
        "L2 第四阶段引擎；负责多媒体生成、海报规划和文生图任务。",
        ("multimedia.generate", "multimedia.poster.plan", "multimedia.text_to_image"),
    ),
)


# L1 基础模块层：架构图口径为十五个基础模块。
# 权限管理、大模型调度、流程模板管理已在 core.seed_capabilities 中作为深度接入能力登记；
# 这里登记其余需要标准适配器承接的基础模块。
FOUNDATION_MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        "context-prompt-management",
        "foundation",
        "上下文与提示词管理",
        8059,
        "/api/v1/context-prompts/instructions",
        "联调文件-7.20-解压/待接入/上下文与提示词管理",
        "adapter_placeholder",
        "L1 基础模块；负责上下文保存、提示词模板、提示词渲染和会话上下文读取。",
        ("context.save", "context.retrieve", "prompt.template.retrieve", "prompt.render"),
    ),
    ModuleSpec(
        "foundation-data",
        "foundation",
        "数据基础模块",
        8060,
        "/api/v1/foundation-data/instructions",
        "联调文件-7.20-解压/待接入/数据基础模块",
        "adapter_placeholder",
        "L1 数据模块；负责物理数据读写、数据权限范围内取数、数据源登记。",
        ("foundation_data.read", "foundation_data.write", "foundation_data.query", "foundation_data.source.register"),
    ),
    ModuleSpec(
        "account-gateway",
        "foundation",
        "账号网关",
        8050,
        "/api/v1/accounts/instructions",
        "联调文件-7.20-解压/account_gateway_integration_v1_0(2)/account_gateway_integration_v1_0",
        "adapter_registered",
        "账号、真人身份、组织事实、资源目录和账号生命周期入口。",
        (
            "account.identity.resolve", "account.identity.verify", "account.resource.query",
            "account.create", "account.list", "account.update", "account.delete",
            "account.freeze", "account.handover_confirm", "account.offboarding_assets.query",
        ),
    ),
    ModuleSpec(
        "human-collaboration",
        "foundation",
        "人机协同",
        8052,
        "/api/v1/human/instructions",
        "联调文件-7.20-解压/L1_11_human_collaboration_first_stage_submit/human_collaboration_demo_first_stage",
        "adapter_registered",
        "真人待办、回复、提醒、升级和查询基础模块。",
        ("human.task.create", "human.task.respond", "human.task.remind", "human.task.escalate", "human.task.query"),
    ),
    ModuleSpec(
        "evolution-mechanism",
        "foundation",
        "进化机制",
        8054,
        "/api/v1/evolution/instructions",
        "联调文件-7.20-解压/jinhuajizhi 1/jinhuajizhi 1/L1-1.3进化机制联调包",
        "adapter_registered",
        "候选、风险检查、确认、审批、发布、回滚和审计接口位。",
        (
            "evolution.candidate.create", "evolution.risk_check", "evolution.confirm",
            "evolution.approve", "evolution.publish", "evolution.rollback", "evolution.audit.query",
        ),
    ),
    ModuleSpec(
        "control-mechanism",
        "foundation",
        "驾驭机制",
        8061,
        "/api/v1/control/instructions",
        "联调文件-7.20-解压/待接入/驾驭机制",
        "adapter_placeholder",
        "L1 基础模块；负责人对智能体/技能/流程的控制策略、人工接管和运行边界。",
        ("control.policy.apply", "control.override.request", "control.session.monitor"),
    ),
    ModuleSpec(
        "knowledge-base",
        "foundation",
        "知识库",
        8055,
        "/api/v1/knowledge/instructions",
        "联调文件-7.20-解压/2.8-2.9交付资料/engines/local_knowledge_base_v0_1",
        "adapter_registered",
        "L1 知识库存储与检索基础模块；切分、向量化、检索重排作为知识库内部基础能力暴露。",
        (
            "knowledge.retrieve", "knowledge.material.get",
            "chunk.split", "vector.embed", "vector.index.upsert",
            "search.query", "search.rerank", "search.retrieve_context",
        ),
    ),
    ModuleSpec(
        "execution-sandbox",
        "foundation",
        "执行沙箱",
        8053,
        "/api/v1/sandbox/instructions",
        "联调文件-7.20-解压/1.14执行沙箱/1.14执行沙箱",
        "adapter_registered",
        "执行任务和浏览器沙箱能力。",
        ("sandbox.run_task", "sandbox.run_browser", "sandbox.result.query"),
    ),
    ModuleSpec(
        "memory-management",
        "foundation",
        "记忆管理",
        8062,
        "/api/v1/memory/instructions",
        "联调文件-7.20-解压/待接入/记忆管理",
        "adapter_placeholder",
        "L1 基础模块；负责记忆写入、检索、候选决策和审计。",
        ("memory.record", "memory.retrieve", "memory.candidate.decide", "memory.audit.query"),
    ),
    ModuleSpec(
        "device-system-interface",
        "foundation",
        "设备与系统接口",
        8063,
        "/api/v1/device-systems/instructions",
        "联调文件-7.20-解压/待接入/设备与系统接口",
        "adapter_placeholder",
        "L1 基础模块；负责设备调用、系统接口调用和事件接收。",
        ("device.command.invoke", "system.interface.call", "system.event.receive"),
    ),
    ModuleSpec(
        "security-compliance",
        "foundation",
        "安全合规",
        8051,
        "/api/v1/security/instructions",
        "联调文件-7.20-解压/1.9安全合规模块(1)/安全合规模块",
        "adapter_registered",
        "安全策略、敏感词、输出审查与动作前合规检查入口。",
        ("security.guardrail.check", "security.output.review", "security.action.precheck"),
    ),
    ModuleSpec(
        "cost-control",
        "foundation",
        "成本管控",
        8064,
        "/api/v1/cost/instructions",
        "联调文件-7.20-解压/待接入/成本管控",
        "adapter_placeholder",
        "L1 基础模块；负责成本估算、成本记录、额度检查和用量归集。",
        ("cost.estimate", "cost.record", "cost.limit.check", "usage.meter.record"),
    ),
)


ALL_MODULES: tuple[ModuleSpec, ...] = BUSINESS_MODULES + FOUNDATION_MODULES
MODULE_BY_CODE = {item.code: item for item in ALL_MODULES}
CAPABILITY_TO_MODULE = {capability: item for item in ALL_MODULES for capability in item.capabilities}


def additional_capabilities() -> list[tuple[str, str, str, str, str, str, str, int]]:
    rows: list[tuple[str, str, str, str, str, str, str, int]] = []
    for module in ALL_MODULES:
        for capability in module.capabilities:
            rows.append((
                capability,
                module.layer,
                module.code,
                f"http://127.0.0.1:{module.port}{module.interface}",
                "sync",
                "capability.invoke",
                "0.2",
                1,
            ))
    return rows
