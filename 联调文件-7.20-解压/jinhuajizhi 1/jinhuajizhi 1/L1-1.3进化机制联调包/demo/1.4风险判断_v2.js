(() => {
  const rules = [
    { key: "changesProductionAction", label: "涉及生产或安全动作", level: "HIGH", route: "BLOCK_OR_SPECIALIST_REVIEW" },
    { key: "changesPermission", label: "涉及账号或权限变更", level: "HIGH", route: "BLOCK_OR_SPECIALIST_REVIEW" },
    { key: "externalOutput", label: "涉及外部发布或客户消息", level: "HIGH", route: "HUMAN_APPROVAL" },
    { key: "sensitiveEmployeeData", label: "涉及员工关系或心理健康敏感数据", level: "HIGH", route: "SPECIALIST_REVIEW" },
    { key: "sharedTemplate", label: "更新共享模板或组织级 Agent", level: "MEDIUM", route: "HUMAN_APPROVAL" },
    { key: "onlyReminder", label: "只生成提醒，不执行动作", level: "LOW", route: "PRIVATE_OR_USER_CONFIRM" },
    { key: "evidenceReady", label: "证据完整且可追溯", level: "LOW", route: "PRIVATE_OR_USER_CONFIRM" }
  ];
  const scenarioOverrides = {
    "SCN-02": ["changesProductionAction"],
    "SCN-04": ["sensitiveEmployeeData"],
    "SCN-06": ["sensitiveEmployeeData"],
    "SCN-08": ["sensitiveEmployeeData"]
  };
  const check = ({ scenarioId, scenarioRisk, candidate = {}, scope = "PRIVATE", evidenceReady = true }) => {
    const matched = new Set(scenarioOverrides[scenarioId] || []);
    if (scope === "SHARED" || scope === "ORGANIZATION") matched.add("sharedTemplate");
    if (candidate.changesProductionAction) matched.add("changesProductionAction");
    if (candidate.changesPermission) matched.add("changesPermission");
    if (candidate.externalOutput) matched.add("externalOutput");
    if (candidate.sensitiveEmployeeData) matched.add("sensitiveEmployeeData");
    if (!evidenceReady) return { level: "MEDIUM", route: "COLLECT_EVIDENCE", requiresApproval: false, blocked: true, reasons: ["证据不足，不能进入发布"] };
    const hits = rules.filter((rule) => matched.has(rule.key));
    const level = hits.some((rule) => rule.level === "HIGH") ? "HIGH" : hits.some((rule) => rule.level === "MEDIUM") || scenarioRisk === "MEDIUM" ? "MEDIUM" : "LOW";
    const route = level === "HIGH" ? (hits.some((rule) => rule.route === "SPECIALIST_REVIEW") ? "SPECIALIST_REVIEW" : "BLOCK_OR_SPECIALIST_REVIEW") : level === "MEDIUM" ? "HUMAN_APPROVAL" : "PRIVATE_OR_USER_CONFIRM";
    return { level, route, requiresApproval: level !== "LOW", blocked: route === "BLOCK_OR_SPECIALIST_REVIEW" || route === "SPECIALIST_REVIEW", reasons: hits.length ? hits.map((rule) => rule.label) : ["未命中高风险规则"] };
  };
  window.JinhuajizhiRiskServiceV2 = Object.freeze({ rules, check });
})();
