(() => {
  const store = window.JinhuajizhiAgentStoreV2;
  const risk = window.JinhuajizhiRiskServiceV2;
  const STORAGE_KEY = "jhj.evolution-governance.v3";
  const AUDIT_KEY = "jhj.evolution-audit.v3";
  const IDEMPOTENCY_KEY = "jhj.evolution-idempotency.v3";

  const readJson = (key, fallback) => {
    try { return JSON.parse(window.localStorage.getItem(key) || "null") ?? fallback; } catch { return fallback; }
  };
  const writeJson = (key, value) => { window.localStorage.setItem(key, JSON.stringify(value)); return value; };
  const now = () => new Date().toISOString();
  const id = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const readCandidates = () => readJson(STORAGE_KEY, {});
  const readAudit = () => readJson(AUDIT_KEY, []);
  const readIdempotency = () => readJson(IDEMPOTENCY_KEY, {});
  const replay = (context, operation) => context.idempotencyKey ? readIdempotency()[`${operation}:${context.idempotencyKey}`] || null : null;
  const remember = (context, operation, response) => {
    if (!context.idempotencyKey) return response;
    writeJson(IDEMPOTENCY_KEY, { ...readIdempotency(), [`${operation}:${context.idempotencyKey}`]: response });
    return response;
  };
  const normalizeContext = (context = {}) => ({
    requestId: context.requestId || id("REQ"),
    actorId: context.actorId || "",
    actorType: context.actorType || "human",
    tenantId: context.tenantId || "TENANT-DEMO",
    subjectUserId: context.subjectUserId || context.userId || "",
    roles: Array.isArray(context.roles) ? context.roles : [],
    sourceApp: context.sourceApp || "L1-1.3-demo",
    idempotencyKey: context.idempotencyKey || ""
  });
  const audit = (eventType, context, extra = {}) => {
    const ctx = normalizeContext(context);
    const entry = { auditId: id("AUD"), eventType, requestId: ctx.requestId, actorId: ctx.actorId, actorType: ctx.actorType, tenantId: ctx.tenantId, sourceApp: ctx.sourceApp, createdAt: now(), ...extra };
    const next = [...readAudit(), entry];
    writeJson(AUDIT_KEY, next);
    return entry;
  };
  const fail = (code, reason, context, extra = {}) => ({ code, reason, audit: audit(code, context, extra) });
  const permission = (context, action, subjectUserId = "") => {
    const ctx = normalizeContext(context);
    if (!ctx.actorId || ctx.actorType !== "human") return { ok: false, code: "ACTOR_UNAUTHENTICATED", reason: "需要有效真人身份" };
    if (action === "CONFIRM_SELF" && ctx.actorId !== subjectUserId) return { ok: false, code: "ACTOR_FORBIDDEN", reason: "只有本人可以确认个人进化" };
    if (["APPROVE", "PUBLISH_SHARED", "ROLLBACK"].includes(action) && !ctx.roles.some((role) => ["BUSINESS_OWNER", "EVOLUTION_ADMIN", "AUDITOR"].includes(role))) {
      return { ok: false, code: "ACTOR_FORBIDDEN", reason: `缺少${action}权限` };
    }
    return { ok: true, context: ctx };
  };
  const saveCandidate = (candidate) => writeJson(STORAGE_KEY, { ...readCandidates(), [candidate.candidateId]: candidate });
  const loadCandidate = (candidateId) => readCandidates()[candidateId] || null;
  const normalizeRisk = (result) => ({
    ...result,
    level: String(result.level || "MEDIUM").toLowerCase(),
    decision: result.blocked ? (result.route === "COLLECT_EVIDENCE" ? "need_more_evidence" : "blocked") : result.requiresApproval ? "pending_approval" : "auto_publish"
  });

  const createCandidate = (input = {}, context = {}) => {
    const ctx = normalizeContext(context);
    const previous = replay(ctx, "createCandidate");
    if (previous) return previous;
    if (!ctx.actorId) return fail("ACTOR_UNAUTHENTICATED", "生成候选也必须记录发起真人", ctx);
    const candidateId = input.candidateId || id("EVO");
    const candidate = {
      candidateId,
      evolutionPath: input.evolutionPath || "SKILL_EVOLUTION",
      scenarioId: input.scenarioId || "SCN-01",
      subjectUserId: input.subjectUserId || ctx.subjectUserId,
      tenantId: ctx.tenantId,
      scope: input.scope || "PERSONAL",
      sourceRefs: input.sourceRefs || [],
      evidence: input.evidence || [],
      riskTags: input.riskTags || [],
      candidateVersion: input.candidateVersion || input,
      rollbackVersion: input.rollbackVersion || null,
      status: "candidate",
      createdBy: ctx.actorId,
      createdAt: now(),
      confirmation: null,
      approval: null,
      risk: null
    };
    saveCandidate(candidate);
    const entry = audit("CANDIDATE_CREATED", ctx, { candidateId, evolutionPath: candidate.evolutionPath, scenarioId: candidate.scenarioId, status: candidate.status });
    return remember(ctx, "createCandidate", { code: "CANDIDATE_CREATED", candidate, audit: entry });
  };

  const riskCheck = (input = {}, context = {}) => {
    const ctx = normalizeContext(context);
    const candidate = input.candidateId ? loadCandidate(input.candidateId) : input.candidate;
    if (!candidate) return fail("CANDIDATE_NOT_FOUND", "找不到候选", ctx);
    const version = candidate.candidateVersion || candidate;
    const result = normalizeRisk(risk ? risk.check({ scenarioId: candidate.scenarioId, scenarioRisk: version.risk || "MEDIUM", candidate: version, scope: candidate.scope === "PERSONAL" ? "PRIVATE" : candidate.scope, evidenceReady: version.evidenceReady !== false }) : { level: "medium", route: "HUMAN_APPROVAL", requiresApproval: true, blocked: false, reasons: ["未加载风险服务"] });
    const next = { ...candidate, risk: result, status: result.decision === "blocked" || result.decision === "need_more_evidence" ? result.decision : "candidate" };
    saveCandidate(next);
    const entry = audit("RISK_CHECKED", ctx, { candidateId: candidate.candidateId, riskLevel: result.level, decision: result.decision, matchedRules: result.reasons });
    return { code: "RISK_CHECKED", candidate: next, risk: result, audit: entry };
  };

  const confirm = (input = {}, context = {}) => {
    const ctx = normalizeContext(context);
    const candidate = loadCandidate(input.candidateId);
    if (!candidate) return fail("CANDIDATE_NOT_FOUND", "找不到候选", ctx);
    const allowed = permission(ctx, "CONFIRM_SELF", candidate.subjectUserId);
    if (!allowed.ok) return fail(allowed.code, allowed.reason, ctx, { candidateId: candidate.candidateId });
    if (["blocked", "need_more_evidence", "rejected", "published"].includes(candidate.status)) return fail("INVALID_STATE", `当前状态不可确认：${candidate.status}`, ctx, { candidateId: candidate.candidateId });
    const action = input.action || "KEEP";
    const nextStatus = action === "REJECT" ? "rejected" : action === "SNOOZE" ? "candidate" : candidate.risk?.decision === "pending_approval" ? "pending_approval" : "approved";
    const next = { ...candidate, status: nextStatus, confirmation: { actorId: ctx.actorId, action, comment: input.comment || "", riskNoticeShown: Boolean(input.riskNoticeShown), at: now() } };
    saveCandidate(next);
    const entry = audit("USER_CONFIRMED", ctx, { candidateId: candidate.candidateId, action, fromStatus: candidate.status, toStatus: nextStatus });
    return { code: action === "REJECT" ? "CANDIDATE_REJECTED" : "USER_CONFIRMED", candidate: next, audit: entry };
  };

  const approve = (input = {}, context = {}) => {
    const ctx = normalizeContext(context);
    const candidate = loadCandidate(input.candidateId);
    if (!candidate) return fail("CANDIDATE_NOT_FOUND", "找不到候选", ctx);
    const allowed = permission(ctx, "APPROVE", candidate.subjectUserId);
    if (!allowed.ok) return fail(allowed.code, allowed.reason, ctx, { candidateId: candidate.candidateId });
    const decision = input.decision || "APPROVE";
    const nextStatus = decision === "APPROVE" ? "approved" : "rejected";
    const next = { ...candidate, status: nextStatus, approval: { actorId: ctx.actorId, roles: ctx.roles, decision, comment: input.comment || "", at: now() } };
    saveCandidate(next);
    const entry = audit("APPROVAL_DECIDED", ctx, { candidateId: candidate.candidateId, decision, fromStatus: candidate.status, toStatus: nextStatus });
    return { code: decision === "APPROVE" ? "APPROVED" : "REJECTED", candidate: next, audit: entry };
  };

  const publish = (input = {}) => {
    const legacy = !input.candidateId && input.candidateVersion;
    let context = normalizeContext({ ...input, actorId: input.actorId || input.userId, subjectUserId: input.subjectUserId || input.userId, roles: input.roles || (input.approver ? ["BUSINESS_OWNER"] : []) });
    const previous = replay(context, "publish");
    if (previous) return previous;
    let candidateId = input.candidateId;
    if (legacy) {
      const created = createCandidate({ scenarioId: input.candidateVersion.scenarioId, subjectUserId: context.subjectUserId, scope: input.scope === "PRIVATE" ? "PERSONAL" : input.scope, candidateVersion: input.candidateVersion, rollbackVersion: input.candidateVersion.rollbackVersion || null }, context);
      if (created.code !== "CANDIDATE_CREATED") return created;
      candidateId = created.candidate.candidateId;
      const checked = riskCheck({ candidateId }, context);
      if (checked.code !== "RISK_CHECKED") return checked;
      if (input.userConfirmed) confirm({ candidateId, action: "KEEP", comment: "页面确认并保存", riskNoticeShown: true }, context);
      const current = loadCandidate(candidateId);
      if (current?.risk?.decision === "pending_approval" && input.approver) approve({ candidateId, decision: "APPROVE", comment: "演示责任人确认" }, context);
    }
    const candidate = loadCandidate(candidateId);
    if (!candidate) return fail("CANDIDATE_NOT_FOUND", "找不到候选", context);
    if (!["approved"].includes(candidate.status)) return fail("PUBLISH_BLOCKED", `候选尚未满足发布条件：${candidate.status}`, context, { candidateId });
    const action = candidate.scope === "PERSONAL" ? "CONFIRM_SELF" : "PUBLISH_SHARED";
    const allowed = permission(context, action, candidate.subjectUserId);
    if (!allowed.ok) return fail(allowed.code, allowed.reason, context, { candidateId });
    const version = candidate.candidateVersion || {};
    const saved = store?.saveAgentVersion ? store.saveAgentVersion(candidate.tenantId, candidate.subjectUserId, input.agentId || `AG-${candidate.subjectUserId}-${candidate.scenarioId}`, { ...version, versionId: version.versionId || id("VER"), scenarioId: candidate.scenarioId }, { userConfirmed: true, riskCleared: true, approver: candidate.approval?.actorId || candidate.confirmation?.actorId || context.actorId, auditId: candidate.confirmation?.at || now() }) : { code: "VERSION_SAVED" };
    const next = { ...candidate, status: saved.code === "VERSION_SAVED" ? "published" : candidate.status, publishedAt: saved.code === "VERSION_SAVED" ? now() : null };
    saveCandidate(next);
    const entry = audit("VERSION_PUBLISHED", context, { candidateId, fromStatus: candidate.status, toStatus: next.status, versionId: version.versionId || null });
    return remember(context, "publish", { code: saved.code, candidate: next, saved, audit: entry });
  };

  const rollback = (input = {}) => {
    const context = normalizeContext({ ...input, actorId: input.actorId || input.userId, subjectUserId: input.subjectUserId || input.userId, roles: input.roles || ["BUSINESS_OWNER"] });
    const allowed = permission(context, "ROLLBACK", input.subjectUserId || input.userId);
    if (!allowed.ok) return fail(allowed.code, allowed.reason, context);
    const result = store?.rollbackAgentVersion ? store.rollbackAgentVersion(input.tenantId || context.tenantId, input.userId || context.subjectUserId, input.agentId, input.targetVersionId, input.reason || "用户请求回退") : { code: "ROLLBACK_COMPLETED" };
    const entry = audit("VERSION_ROLLED_BACK", context, { agentId: input.agentId, targetVersionId: input.targetVersionId, reason: input.reason || "用户请求回退" });
    return { ...result, audit: entry };
  };

  const getAuditLog = (filters = {}) => readAudit().filter((entry) => !filters.candidateId || entry.candidateId === filters.candidateId);
  const getCandidate = (candidateId) => loadCandidate(candidateId);
  const reset = () => { window.localStorage.removeItem(STORAGE_KEY); window.localStorage.removeItem(AUDIT_KEY); window.localStorage.removeItem(IDEMPOTENCY_KEY); };

  window.JinhuajizhiGovernanceServiceV3 = Object.freeze({ createCandidate, riskCheck, confirm, approve, publish, rollback, getCandidate, getAuditLog, permission, reset, keys: { STORAGE_KEY, AUDIT_KEY, IDEMPOTENCY_KEY } });
})();
