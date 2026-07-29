(() => {
  const KEY = "jhj.agent-store.v2";
  const safeRead = () => {
    try { return JSON.parse(window.localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; }
  };
  const write = (value) => {
    window.localStorage.setItem(KEY, JSON.stringify(value));
    return value;
  };
  const userKey = (tenantId, userId) => `${tenantId}::${userId}`;
  const readAgentContext = (tenantId, userId, scenarioId) => {
    const store = safeRead();
    const agents = store[userKey(tenantId, userId)] || [];
    const agent = agents.find((item) => item.scenarioId === scenarioId && item.status === "ACTIVE");
    if (!agent) return { code: "AGENT_NOT_FOUND", tenantId, userId, scenarioId, agent: null };
    return { code: "AGENT_FOUND", tenantId, userId, scenarioId, agent };
  };
  const saveAgentVersion = (tenantId, userId, agentId, candidateVersion, approval) => {
    if (!approval?.userConfirmed || !approval?.riskCleared) return { code: "WRITE_REJECTED", reason: "USER_OR_RISK_NOT_CONFIRMED" };
    const store = safeRead();
    const key = userKey(tenantId, userId);
    const agents = store[key] || [];
    const index = agents.findIndex((item) => item.agentId === agentId);
    const current = index >= 0 ? agents[index] : { agentId, scenarioId: candidateVersion.scenarioId, status: "ACTIVE", versions: [] };
    const version = { ...candidateVersion, createdAt: new Date().toISOString(), approval, status: "ACTIVE" };
    current.versions = (current.versions || []).map((item) => ({ ...item, status: "HISTORICAL" }));
    current.versions.push(version);
    current.currentVersionId = version.versionId;
    if (index >= 0) agents[index] = current; else agents.push(current);
    write({ ...store, [key]: agents });
    return { code: "VERSION_SAVED", agent: current, version };
  };
  const rollbackAgentVersion = (tenantId, userId, agentId, targetVersionId, reason) => {
    const store = safeRead();
    const key = userKey(tenantId, userId);
    const agents = store[key] || [];
    const agent = agents.find((item) => item.agentId === agentId);
    if (!agent || !agent.versions.some((item) => item.versionId === targetVersionId)) return { code: "ROLLBACK_TARGET_NOT_FOUND" };
    agent.versions = agent.versions.map((item) => ({ ...item, status: item.versionId === targetVersionId ? "ACTIVE" : "HISTORICAL" }));
    agent.currentVersionId = targetVersionId;
    agent.lastRollback = { reason, at: new Date().toISOString() };
    write({ ...store, [key]: agents });
    return { code: "ROLLBACK_COMPLETED", agent };
  };
  window.JinhuajizhiAgentStoreV2 = Object.freeze({ key: KEY, readAgentContext, saveAgentVersion, rollbackAgentVersion });
})();
