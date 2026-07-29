window.DA_SEED_STATE = {
  actors: [
    { id: "tester_a", name: "测试员甲", role: "普通员工", department: "生物制造研发中心", canCreate: true, canPublishDepartment: false, canPublishCompany: false },
    { id: "tester_b", name: "测试员乙", role: "部门负责人", department: "生物制造研发中心", canCreate: true, canPublishDepartment: true, canPublishCompany: false },
    { id: "tester_c", name: "测试员丙", role: "非试点部门员工", department: "行政部", canCreate: true, canPublishDepartment: false, canPublishCompany: false },
    { id: "engine_admin", name: "数字资产管理员", role: "引擎负责人", department: "AI平台组", canCreate: true, canPublishDepartment: true, canPublishCompany: true },
  ],
  assets: [
    {
      id: "DE-0001", name: "农业技术服务数字员工", type: "digital_employee", department: "生物制造研发中心", owner: "测试员乙", maintainer: "研发资料负责人",
      scope: "department", status: "published", version: "v1.2", syncStatus: "synced", healthStatus: "healthy", metadataCompleteness: 96,
      description: "面向农技服务人员整理作物、土壤、产品和施用建议，输出须标注 AI 生成并待人工确认。", businessContext: "农业技术服务",
      relatedKnowledgeBaseIds: ["KB-0003"], relatedSkillIds: ["SK-0002"], relatedMaterialIds: ["MT-0001"], toolRef: "",
      createdAt: "2026-07-01 09:20:00", updatedAt: "2026-07-07 15:18:00"
    },
    {
      id: "DE-0002", name: "发酵工艺问答数字员工", type: "digital_employee", department: "生物制造研发中心", owner: "研发资料负责人", maintainer: "研发资料负责人",
      scope: "department", status: "pending", version: "v1.0", syncStatus: "unsynced", healthStatus: "warning", metadataCompleteness: 78,
      description: "围绕菌株、发酵批次、工艺规程和异常案例辅助研发人员定位资料，不替代专家判断。", businessContext: "发酵资料问答辅助",
      relatedKnowledgeBaseIds: ["KB-0001", "KB-0002"], relatedSkillIds: ["SK-0001"], relatedMaterialIds: ["MT-0002"], toolRef: "",
      createdAt: "2026-07-02 10:30:00", updatedAt: "2026-07-06 17:10:00"
    },
    {
      id: "DE-0003", name: "产品资料整理数字员工", type: "digital_employee", department: "产品技术部", owner: "产品资料负责人", maintainer: "产品技术部",
      scope: "department", status: "draft", version: "v1.0", syncStatus: "unsynced", healthStatus: "warning", metadataCompleteness: 72,
      description: "整理产品标准、试验报告和说明资料，输出内容须由产品负责人确认后发布。", businessContext: "产品资料沉淀",
      relatedKnowledgeBaseIds: ["KB-0003"], relatedSkillIds: [], relatedMaterialIds: ["MT-0003"], toolRef: "",
      createdAt: "2026-07-03 14:00:00", updatedAt: "2026-07-07 09:25:00"
    },
    {
      id: "SK-0001", name: "发酵异常识别技能", type: "skill", department: "生物制造研发中心", owner: "测试员乙", maintainer: "研发资料负责人",
      scope: "department", status: "published", version: "v1.1", syncStatus: "synced", healthStatus: "healthy", metadataCompleteness: 92,
      description: "编排发酵批次记录读取、阈值规则匹配、异常项输出和研发人员确认步骤。技能本身不做真实计算。", businessContext: "发酵过程质量检查",
      relatedKnowledgeBaseIds: ["KB-0001", "KB-0002"], relatedSkillIds: [], relatedMaterialIds: ["MT-0002"], toolRef: "fermentation_anomaly_checker_v1",
      createdAt: "2026-07-01 11:00:00", updatedAt: "2026-07-07 11:00:00"
    },
    {
      id: "SK-0002", name: "工艺参数检查技能", type: "skill", department: "生物制造研发中心", owner: "测试员乙", maintainer: "研发资料负责人",
      scope: "department", status: "published", version: "v1.0", syncStatus: "failed", healthStatus: "error", metadataCompleteness: 86,
      description: "编排温度、pH、溶氧、批次时间等参数检查步骤，底层判断由固定规则程序完成。", businessContext: "工艺参数复核",
      relatedKnowledgeBaseIds: ["KB-0001"], relatedSkillIds: [], relatedMaterialIds: [], toolRef: "fermentation_parameter_checker_v1",
      createdAt: "2026-07-02 09:10:00", updatedAt: "2026-07-06 13:45:00"
    },
    {
      id: "SK-0003", name: "多公司数据汇总技能", type: "skill", department: "AI平台组", owner: "数字资产管理员", maintainer: "AI平台组",
      scope: "company", status: "disabled", version: "v1.0", syncStatus: "not_required", healthStatus: "warning", metadataCompleteness: 68,
      description: "演示停用资产，不可被数字员工继续引用。", businessContext: "跨部门资料汇总",
      relatedKnowledgeBaseIds: [], relatedSkillIds: [], relatedMaterialIds: [], toolRef: "",
      createdAt: "2026-07-02 16:20:00", updatedAt: "2026-07-07 18:00:00"
    },
    {
      id: "KB-0001", name: "微生物肥料工艺知识库", type: "knowledge_base", department: "生物制造研发中心", owner: "测试员乙", maintainer: "研发资料负责人",
      scope: "department", status: "published", version: "v1.3", syncStatus: "not_required", healthStatus: "healthy", metadataCompleteness: 98,
      description: "登记菌株、发酵工艺、产品标准和实验结论等资料。文档解析由文档表格解析引擎完成。", businessContext: "研发知识沉淀",
      relatedKnowledgeBaseIds: [], relatedSkillIds: [], relatedMaterialIds: ["MT-0001"], toolRef: "",
      createdAt: "2026-06-30 10:00:00", updatedAt: "2026-07-07 10:00:00"
    },
    {
      id: "KB-0002", name: "菌株资料知识库", type: "knowledge_base", department: "生物制造研发中心", owner: "研发资料负责人", maintainer: "研发资料负责人",
      scope: "department", status: "draft", version: "v1.0", syncStatus: "not_required", healthStatus: "warning", metadataCompleteness: 70,
      description: "登记菌株来源、培养条件、实验批次和研发结论。", businessContext: "菌株资料管理",
      relatedKnowledgeBaseIds: [], relatedSkillIds: [], relatedMaterialIds: [], toolRef: "",
      createdAt: "2026-07-04 10:00:00", updatedAt: "2026-07-07 16:20:00"
    },
    {
      id: "KB-0003", name: "产品标准知识库", type: "knowledge_base", department: "产品技术部", owner: "产品资料负责人", maintainer: "产品技术部",
      scope: "department", status: "published", version: "v1.0", syncStatus: "not_required", healthStatus: "healthy", metadataCompleteness: 90,
      description: "登记产品标准、试验报告、应用案例和说明资料。", businessContext: "产品资料检索",
      relatedKnowledgeBaseIds: [], relatedSkillIds: [], relatedMaterialIds: ["MT-0003"], toolRef: "",
      createdAt: "2026-07-01 15:00:00", updatedAt: "2026-07-05 09:30:00"
    },
    {
      id: "MT-0001", name: "田间试验报告模板", type: "material", department: "产品技术部", owner: "产品资料负责人", maintainer: "产品技术部",
      scope: "department", status: "published", version: "v1.0", syncStatus: "not_required", healthStatus: "healthy", metadataCompleteness: 88,
      description: "作为农技服务和产品效果报告的结构参考，不直接作为功能登记。", businessContext: "试验报告沉淀",
      relatedKnowledgeBaseIds: ["KB-0003"], relatedSkillIds: [], relatedMaterialIds: [], toolRef: "",
      createdAt: "2026-07-02 15:00:00", updatedAt: "2026-07-05 12:00:00"
    },
    {
      id: "MT-0002", name: "发酵工艺规程样例", type: "material", department: "生物制造研发中心", owner: "研发资料负责人", maintainer: "研发资料负责人",
      scope: "personal", status: "draft", version: "v1.0", syncStatus: "not_required", healthStatus: "warning", metadataCompleteness: 61,
      description: "工艺规程样例素材，待补来源说明。", businessContext: "发酵工艺沉淀",
      relatedKnowledgeBaseIds: [], relatedSkillIds: [], relatedMaterialIds: [], toolRef: "",
      createdAt: "2026-07-06 09:20:00", updatedAt: "2026-07-06 09:20:00"
    },
    {
      id: "MT-0003", name: "产品说明素材", type: "material", department: "产品技术部", owner: "产品资料负责人", maintainer: "产品技术部",
      scope: "department", status: "published", version: "v1.0", syncStatus: "not_required", healthStatus: "healthy", metadataCompleteness: 91,
      description: "产品说明和农服案例素材，使用前必须产品负责人确认。", businessContext: "产品说明生成参考",
      relatedKnowledgeBaseIds: ["KB-0003"], relatedSkillIds: [], relatedMaterialIds: [], toolRef: "",
      createdAt: "2026-07-03 13:00:00", updatedAt: "2026-07-06 11:00:00"
    }
  ],
  versionRecords: [
    { id: "VR-0001", assetId: "SK-0001", assetName: "发酵异常识别技能", version: "v1.0", editor: "测试员乙", editedAt: "2026-07-01 11:00:00", reason: "初始创建", summary: "登记输入、步骤、底层工具引用", beforeSnapshot: null, afterSnapshot: { version: "v1.0" } },
    { id: "VR-0002", assetId: "SK-0001", assetName: "发酵异常识别技能", version: "v1.1", editor: "测试员乙", editedAt: "2026-07-07 11:00:00", reason: "完善人审规则", summary: "补充异常项清单研发人员确认要求", beforeSnapshot: { version: "v1.0" }, afterSnapshot: { version: "v1.1" } },
    { id: "VR-0003", assetId: "KB-0001", assetName: "微生物肥料工艺知识库", version: "v1.3", editor: "测试员乙", editedAt: "2026-07-07 10:00:00", reason: "补充工艺规程", summary: "新增发酵工艺资料登记", beforeSnapshot: { version: "v1.2" }, afterSnapshot: { version: "v1.3" } }
  ],
  publishRecords: [
    { id: "PR-0001", assetId: "SK-0001", assetName: "发酵异常识别技能", targetScope: "department", submitter: "测试员乙", approver: "研发负责人", status: "approved", time: "2026-07-07 11:05:00", note: "部门级发布通过" },
    { id: "PR-0002", assetId: "DE-0002", assetName: "发酵工艺问答数字员工", targetScope: "department", submitter: "研发资料负责人", approver: "研发负责人", status: "pending", time: "2026-07-06 17:10:00", note: "待确认问答边界和人工审核规则" }
  ],
  permissionChecks: [
    { id: "PC-0001", time: "2026-07-07 09:30:00", actor: "测试员丙", action: "修改资产", assetId: "KB-0001", assetName: "微生物肥料工艺知识库", result: "denied", reason: "1.8 已确认真人身份；1.1 判定其无研发中心资源管理权限" }
  ],
  syncRecords: [
    { id: "SR-0001", assetId: "DE-0001", assetName: "农业技术服务数字员工", assetType: "digital_employee", functionName: "农业技术服务", example: "根据土壤和作物给出施用建议", action: "登记", status: "success", callableScope: "生物制造研发中心", time: "2026-07-07 15:18:00", failReason: "", payload: { assetId: "DE-0001", functionName: "农业技术服务" } },
    { id: "SR-0002", assetId: "SK-0001", assetName: "发酵异常识别技能", assetType: "skill", functionName: "发酵异常识别", example: "检查这批发酵记录是否异常", action: "登记", status: "success", callableScope: "生物制造研发中心", time: "2026-07-07 11:05:00", failReason: "", payload: { assetId: "SK-0001", toolRef: "fermentation_anomaly_checker_v1" } },
    { id: "SR-0003", assetId: "SK-0002", assetName: "工艺参数检查技能", assetType: "skill", functionName: "工艺参数检查", example: "核对这批发酵参数是否超出范围", action: "登记", status: "failed", callableScope: "生物制造研发中心", time: "2026-07-06 13:45:00", failReason: "缺少示例句字段", payload: { assetId: "SK-0002" } }
  ],
  ingestionRecords: [
    { id: "KI-0001", knowledgeBaseId: "KB-0001", knowledgeBaseName: "微生物肥料工艺知识库", fileName: "发酵工艺规程.pdf", status: "已入库", parserEngine: "文档表格解析引擎 Mock", minioStatus: "成功", postgresStatus: "成功", milvusStatus: "成功", note: "经流程编排触发解析，数字资产引擎只记录建库状态。" },
    { id: "KI-0002", knowledgeBaseId: "KB-0002", knowledgeBaseName: "菌株资料知识库", fileName: "菌株资料汇编.docx", status: "待解析", parserEngine: "文档表格解析引擎 Mock", minioStatus: "成功", postgresStatus: "成功", milvusStatus: "未开始", note: "等待解析结果。" }
  ],
  healthRecords: [
    { id: "HC-0001", assetId: "SK-0001", assetName: "发酵异常识别技能", status: "healthy", checkedAt: "2026-07-07 11:10:00", issues: [] },
    { id: "HC-0002", assetId: "SK-0002", assetName: "工艺参数检查技能", status: "error", checkedAt: "2026-07-07 11:10:00", issues: ["已发布技能同步失败"] },
    { id: "HC-0003", assetId: "DE-0002", assetName: "发酵工艺问答数字员工", status: "warning", checkedAt: "2026-07-07 11:10:00", issues: ["待审批未同步功能登记库"] }
  ],
  operationLogs: [
    { id: "LOG-0001", time: "2026-07-07 15:18:00", actor: "测试员乙", type: "同步功能登记库", assetId: "DE-0001", assetName: "农业技术服务数字员工", result: "成功", note: "数字员工发布后登记功能" },
    { id: "LOG-0002", time: "2026-07-07 11:05:00", actor: "测试员乙", type: "发布资产", assetId: "SK-0001", assetName: "发酵异常识别技能", result: "成功", note: "部门级发布通过" },
    { id: "LOG-0003", time: "2026-07-07 09:30:00", actor: "测试员丙", type: "权限拦截", assetId: "KB-0001", assetName: "微生物肥料工艺知识库", result: "失败", note: "1.1 权限管理拒绝跨部门修改" }
  ],
  testRecords: [
    { id: "T-0001", name: "四类资产创建", status: "untested", lastRunAt: "", failReason: "", acceptance: "数字员工、技能、知识库、素材均可创建并写入台账。" },
    { id: "T-0002", name: "必填信息校验", status: "untested", lastRunAt: "", failReason: "", acceptance: "缺少名称、部门、范围或关键字段时阻止提交。" },
    { id: "T-0003", name: "资产修改生成版本", status: "untested", lastRunAt: "", failReason: "", acceptance: "修改不覆盖旧版本，生成新版本记录。" },
    { id: "T-0004", name: "版本对比与回滚", status: "untested", lastRunAt: "", failReason: "", acceptance: "回滚生成新版本而不是直接倒退版本号。" },
    { id: "T-0005", name: "发布审批", status: "untested", lastRunAt: "", failReason: "", acceptance: "部门级及以上发布进入审批或模拟审批。" },
    { id: "T-0006", name: "停用资产", status: "untested", lastRunAt: "", failReason: "", acceptance: "停用后资产不可继续同步为功能。" },
    { id: "T-0007", name: "权限拦截", status: "untested", lastRunAt: "", failReason: "", acceptance: "无权限人员操作被拦截并留痕。" },
    { id: "T-0008", name: "功能登记库同步", status: "untested", lastRunAt: "", failReason: "", acceptance: "发布数字员工/技能后生成同步记录。" },
    { id: "T-0009", name: "知识库三拆入库模拟", status: "untested", lastRunAt: "", failReason: "", acceptance: "展示 MinIO、PostgreSQL、Milvus 三拆状态。" },
    { id: "T-0010", name: "资产关系影响提示", status: "untested", lastRunAt: "", failReason: "", acceptance: "能展示引用和被引用关系。" },
    { id: "T-0011", name: "操作留痕完整性", status: "untested", lastRunAt: "", failReason: "", acceptance: "所有关键操作进入日志。" },
    { id: "T-0012", name: "一键演示闭环", status: "untested", lastRunAt: "", failReason: "", acceptance: "发酵异常识别技能完成 MVP 治理闭环。" }
  ],
  demoResult: null,
  counters: { demoSkill: 0, asset: 12, version: 3, publish: 2, permission: 1, sync: 3, ingestion: 2, health: 3, log: 3 }
};
