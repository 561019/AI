"use strict";

const ASSET_TYPES = {
  agent: { label: "Agent", code: "AG", copy: "面向岗位的组合入口，编排已启用技能与知识库，不自行计算。" },
  skill: { label: "技能", code: "SK", copy: "必须绑定白名单固定工具、输入输出、版本和测试证据。" },
  knowledge_base: { label: "知识库", code: "KB", copy: "知识源容器，登记来源、处理状态与可见边界。" },
};

const SCOPE_LABELS = {
  personal: "个人岗位级",
  department: "部门级",
  company: "公司级",
  group: "集团级（待制度确认）",
};

const STATUS_LABELS = {
  draft: "草稿",
  personal_active: "个人启用",
  active: "已启用",
  pending_adoption: "待采纳审批",
  pending_publish: "待发布审批",
  pending: "待审批",
  published: "已发布",
  disabled: "已停用",
  frozen: "已冻结",
  rejected: "已驳回",
  deleted: "已删除",
  adopted: "已被部门采纳（保留）",
  registered: "已登记",
  success: "成功",
  failed: "失败",
  requested: "已申请，待L1回执",
  ready: "L1实例就绪",
  ready_to_index: "待L1索引",
  indexed: "已切片并建立向量索引",
  blocked_no_l1: "缺少L1实例",
  not_started: "未开始",
  not_started: "未开始",
  unknown: "未返回",
  synced: "已同步",
  immediate: "即时结果",
  accepted: "受理回执",
};

const WORKFLOW_LABELS = {
  adoption: "个人成果采纳",
  publish: "公共范围发布",
  department_publish: "部门级发布",
  company_publish: "公司级发布",
};

const ROLE_LABELS = {
  employee: "普通员工",
  department_approver: "部门审批岗位",
  company_approver: "公司审批岗位",
  platform_operator: "平台技术运维",
  unassigned: "未入岗",
};

const state = {
  actorId: "",
  data: emptyData(),
  currentView: "overview",
  catalogMode: "personal",
  selectedAssetId: "",
  selectedType: "agent",
  selectedScenarioCode: "",
  l4Result: null,
  runtimeResult: null,
  loading: false,
};
let stateRequestSequence = 0;

function emptyData() {
  return {
    currentActor: null,
    actors: [],
    assets: [],
    workflows: [],
    sources: [],
    attachments: [],
    foundationCalls: [],
    flowTasks: [],
    function_registry: [],
    l4Requests: [],
    l4Scenarios: [],
    tools: [],
    developmentRequests: [],
    knowledgeBaseInstances: [],
    validations: [],
    executions: [],
    versions: [],
    logs: [],
    stats: {},
    scopePolicies: {},
    labels: {},
  };
}

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) return "—";
  const raw = String(value).replace("T", " ");
  return raw.length > 19 ? raw.slice(0, 19) : raw;
}

function assetId(asset) { return asset?.asset_id ?? asset?.id ?? ""; }
function assetName(asset) { return asset?.asset_name ?? asset?.name ?? "未命名资产"; }
function assetType(asset) { return asset?.asset_type ?? asset?.type ?? "agent"; }
function actorId(actor) { return actor?.userId ?? actor?.user_id ?? actor?.id ?? ""; }

function newProtocolId(prefix) {
  const token = globalThis.crypto?.randomUUID?.().replaceAll("-", "")
    || `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${token}`;
}

function buildFlowEnvelope(action, serviceCode, capabilityId, payload) {
  const token = newProtocolId("flow");
  return {
    protocol_version: "1.0",
    message_id: newProtocolId("msg"),
    trace_id: newProtocolId("trace"),
    request_id: newProtocolId("req"),
    parent_message_id: "msg_l4_console",
    source: { layer: "L2", service_code: "l2.workflow_execution" },
    target: { layer: "L2", service_code: "l2.digital_asset" },
    channel: "l2_internal",
    route_type: "task.dispatch",
    action,
    service_code: serviceCode,
    capability_id: capabilityId,
    capability_dictionary_version: "mock_2026.07.17",
    registry_version: "mock_registry_2026.07.17",
    actor: { person_id: state.actorId, tenant_id: "tenant_hanhe" },
    context: {
      workflow_instance_id: `wf_${token}`,
      node_id: `node_${token}`,
      task_id: `task_${token}`,
      data_refs: [],
    },
    idempotency_key: `idem_${token}`,
    deadline_at: "2099-12-31T23:59:59+08:00",
    payload,
  };
}

function actorById(id) {
  return state.data.actors.find((actor) => actorId(actor) === id);
}

function actorName(id) {
  if (!id) return "—";
  return actorById(id)?.name ?? id;
}

function currentActor() {
  return state.data.currentActor ?? actorById(state.actorId) ?? null;
}

function currentActorId() {
  return actorId(currentActor()) || state.actorId;
}

function typeLabel(type) {
  return ASSET_TYPES[type]?.label ?? state.data.labels?.assetTypes?.[type] ?? type ?? "—";
}

function scopeLabel(scope) {
  return SCOPE_LABELS[scope] ?? state.data.labels?.scopes?.[scope] ?? scope ?? "—";
}

function statusLabel(status) {
  return STATUS_LABELS[status] ?? state.data.labels?.statuses?.[status] ?? status ?? "—";
}

function statusTone(status) {
  if (["published", "personal_active", "active", "approved", "success", "synced", "parsed", "immediate"].includes(status)) return "success";
  if (["pending", "pending_publish", "pending_adoption", "draft", "waiting", "not_started", "accepted"].includes(status)) return "warning";
  if (["disabled", "frozen", "rejected", "failed", "denied", "deleted"].includes(status)) return "danger";
  return "info";
}

function badge(label, tone = "") {
  return `<span class="badge ${escapeHtml(tone)}">${escapeHtml(label)}</span>`;
}

function capability(subject, key) {
  return subject?.capabilities?.[key] === true;
}

function normalizeDecision(value, fallbackReason) {
  if (typeof value === "boolean") return { allowed: value, reason: fallbackReason || (value ? "服务端判定允许" : "服务端判定拒绝") };
  if (value && typeof value === "object") {
    return {
      allowed: value.allowed !== undefined
        ? value.allowed
        : (value.result === "allow" || value.decision === "allow"),
      reason: value.reason ?? value.message ?? fallbackReason ?? "服务端未返回说明",
    };
  }
  return { allowed: false, reason: fallbackReason ?? "服务端未返回该判定" };
}

function resourceDecision(asset) {
  return normalizeDecision(asset?.resourceAccess ?? asset?.access?.resource ?? asset?.resourceCallable, asset?.resourceCallableReason);
}

function dataDecision(asset) {
  return normalizeDecision(asset?.permissionDecision?.viewContent, "由外部权限管理 Mock 按当前真人判定资产内容访问");
}

function isMetadataOnly(asset) {
  return asset?.metadataOnly === true || asset?.redacted === true || dataDecision(asset).allowed === false;
}

async function request(path, options = {}) {
  const method = options.method ?? "GET";
  const url = new URL(path, window.location.origin);
  const suppliedActor = options.body?.actor;
  const selectedActor = options.actor
    ?? (typeof suppliedActor === "object" ? suppliedActor.person_id : suppliedActor)
    ?? state.actorId;
  if (selectedActor) url.searchParams.set("actor", selectedActor);

  const init = { method, headers: { Accept: "application/json" } };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    const body = { ...options.body };
    if (!body.actor) body.actor = selectedActor;
    init.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw new Error(`无法连接后端服务：${error.message}`);
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    const error = new Error(payload.message || `请求失败（HTTP ${response.status}）`);
    error.code = payload.code || `HTTP_${response.status}`;
    throw error;
  }
  return payload;
}

async function loadState(requestedActor = state.actorId, options = {}) {
  const requestSequence = ++stateRequestSequence;
  state.loading = true;
  setConnectionBanner("正在从服务端读取身份过滤后的状态…", false);
  try {
    const payload = await request("/api/state", { actor: requestedActor || undefined });
    // 快速切换真人时，只允许最后一次请求写回页面，避免甲的数据覆盖丙的页面。
    if (requestSequence !== stateRequestSequence) return;
    state.data = { ...emptyData(), ...(payload.data ?? payload) };
    const serverActor = actorId(state.data.currentActor);
    state.actorId = serverActor || requestedActor || actorId(state.data.actors[0]);
    if (state.data.currentActor?.metadataOnly === true && state.catalogMode === "personal") {
      state.catalogMode = "all";
    }
    updateActorUrl(state.actorId);
    renderAll();
    setConnectionBanner("", false);
    if (options.message) toast(options.message);
  } catch (error) {
    if (requestSequence !== stateRequestSequence) return;
    setConnectionBanner(`${error.code ? `[${error.code}] ` : ""}${error.message}`, true);
    toast(error.message, true);
  } finally {
    if (requestSequence === stateRequestSequence) state.loading = false;
  }
}

// 切换真人时，表单、筛选、详情和弹窗都属于上一位真人的临时界面状态，绝不能带给下一位真人。
function clearActorEphemeralState() {
  state.selectedAssetId = "";
  state.catalogMode = "personal";
  state.selectedType = "agent";
  state.selectedScenarioCode = "";
  state.l4Result = null;
  state.runtimeResult = null;
  closeModal();

  const assetForm = $("#assetForm");
  if (assetForm) assetForm.reset();
  const sourceForm = $("#sourceForm");
  if (sourceForm) sourceForm.reset();
  const l4Form = $("#l4RequestForm");
  if (l4Form) l4Form.reset();
  const runtimeForm = $("#runtimeForm");
  if (runtimeForm) runtimeForm.reset();
  $("#sourceFormPanel")?.classList.add("hidden");

  ["catalogSearch", "catalogTypeFilter", "catalogStatusFilter"].forEach((id) => {
    const field = $("#" + id);
    if (field) field.value = "";
  });
  closeAssetDetail();
}

async function mutate(path, body = {}, successMessage = "操作已提交") {
  try {
    const payload = await request(path, { method: "POST", body });
    closeModal();
    await loadState(state.actorId, { message: payload.message || successMessage });
    return true;
  } catch (error) {
    toast(`${error.code ? `[${error.code}] ` : ""}${error.message}`, true);
    return false;
  }
}

function updateActorUrl(id) {
  if (!id) return;
  const url = new URL(window.location.href);
  url.searchParams.set("actor", id);
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function setConnectionBanner(message, isError) {
  const banner = $("#connectionBanner");
  if (!message) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.textContent = message;
  banner.classList.remove("hidden");
  banner.classList.toggle("error", Boolean(isError));
}

let toastTimer;
function toast(message, isError = false) {
  const node = $("#toast");
  clearTimeout(toastTimer);
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.remove("hidden");
  toastTimer = setTimeout(() => node.classList.add("hidden"), 3400);
}

function renderAll() {
  renderActorSelector();
  renderCreatePage();
  renderOverview();
  renderL4();
  renderRuntime();
  renderCatalog();
  renderWorkflows();
  renderSources();
  renderRegistry();
  renderAudit();
  routeTo(location.hash.slice(1) || state.currentView || "overview", false);
}

function renderActorSelector() {
  const select = $("#actorSelect");
  const actors = state.data.actors;
  select.innerHTML = actors.map((actor) => {
    const label = [actor.name, ROLE_LABELS[actor.role] ?? actor.role, actor.department].filter(Boolean).join(" · ");
    return `<option value="${escapeHtml(actorId(actor))}">${escapeHtml(label)}</option>`;
  }).join("");
  select.value = state.actorId;

  const actor = currentActor();
  const position = actor?.positionCode ?? actor?.position_code ?? "未返回岗位编码";
  const company = actor?.company ?? "南宁汉和";
  $("#actorContext").textContent = actor ? `${company} · 岗位 ${position} · 服务端实时判权` : "未定位当前真人";
  $("#assetDepartment").value = actor?.department ?? "";
}

function renderOverview() {
  const assets = state.data.assets;
  const workflows = state.data.workflows;
  const stats = state.data.stats || {};
  const pending = workflows.filter((flow) => flow.status === "pending");
  const myTasks = pending.filter((flow) => capability(flow, "approve") || capability(flow, "reject"));
  const denyCount = stats.denyCount ?? stats.denied ?? stats.deniedActions ?? state.data.logs.filter((log) => String(log.decision_result).toLowerCase() === "deny").length;
  const metadataOnlyCount = assets.filter(isMetadataOnly).length;
  const publishedCount = stats.published ?? assets.filter((asset) => asset.status === "published").length;

  const cards = [
    ["当前可见资产", stats.visibleAssetCount ?? stats.visibleAssets ?? assets.length, "服务端已按当前真人过滤", ""],
    ["公共已发布", stats.publishedCount ?? publishedCount, "不包含个人启用资产", "success"],
    ["我的待审批", myTasks.length, "固定岗位模板定位的待办", myTasks.length ? "warning" : ""],
    ["内容已脱敏", metadataOnlyCount, "仅技术元数据可见", metadataOnlyCount ? "warning" : ""],
    ["权限拒绝留痕", denyCount, "拒绝同样是验证证据", denyCount ? "danger" : ""],
    ["L4 场景请求", stats.l4RequestCount ?? state.data.l4Requests.length, "均有追踪编号与标准回复", ""],
  ];
  $("#overviewStats").innerHTML = cards.map(([label, value, note, tone]) => `
    <article class="stat-card ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>
  `).join("");

  $("#overviewTasks").innerHTML = myTasks.length ? myTasks.slice(0, 5).map((flow) => `
    <button class="compact-item" type="button" data-jump="workflows">
      <strong>${escapeHtml(WORKFLOW_LABELS[flow.kind] ?? flow.kind)} · ${escapeHtml(flow.asset_id)}</strong>
      <span>${escapeHtml(flow.approval_position || "待定位审批岗位")}</span>
    </button>
  `).join("") : `<div class="empty-state">当前没有可处理待办</div>`;

  $("#overviewAssets").innerHTML = assets.length ? assets.slice(0, 6).map((asset) => `
    <article class="asset-card">
      <header><span class="badge info">${escapeHtml(typeLabel(assetType(asset)))}</span>${badge(statusLabel(asset.status), statusTone(asset.status))}</header>
      <h4>${escapeHtml(assetName(asset))}</h4>
      <p>${escapeHtml(asset.description || "暂无说明")}</p>
      <footer><span>${escapeHtml(assetId(asset))}</span><span>${escapeHtml(scopeLabel(asset.scope))}</span></footer>
    </article>
  `).join("") : `<div class="empty-state">当前真人没有可见资产</div>`;
}

function l4ScenarioByCode(code) {
  return state.data.l4Scenarios.find((scenario) => scenario.code === code) || null;
}

function l4ResponseLabel(type) {
  return { immediate: "即时结果", accepted: "受理回执", rejected: "拒绝原因" }[type] || type || "未返回";
}

function syncL4ScenarioForm(forceText = false) {
  const scenario = l4ScenarioByCode(state.selectedScenarioCode);
  if (!scenario) return;
  const select = $("#l4ScenarioSelect");
  const mode = $("#l4RequestMode");
  const service = $("#l4ServiceCode");
  const text = $("#l4RequestText");
  if (select) select.value = scenario.code;
  if (mode) mode.value = scenario.request_mode;
  if (service) service.value = scenario.service_code;
  if (text && (forceText || text.dataset.scenario !== scenario.code)) {
    text.value = scenario.default_request || "";
    text.dataset.scenario = scenario.code;
  }
  $$("#l4ScenarioCards [data-l4-scenario]").forEach((card) => card.classList.toggle("active", card.dataset.l4Scenario === scenario.code));
}

function renderL4() {
  const scenarios = state.data.l4Scenarios || [];
  if (!scenarios.length) {
    $("#l4ScenarioCards").innerHTML = `<div class="empty-state">服务端未返回 L4 场景登记</div>`;
    $("#l4ScenarioSelect").innerHTML = "";
    $("#l4RequestRows").innerHTML = `<tr><td colspan="7"><div class="empty-state">暂无场景请求</div></td></tr>`;
    return;
  }
  if (!l4ScenarioByCode(state.selectedScenarioCode)) state.selectedScenarioCode = scenarios[0].code;
  $("#l4ScenarioCards").innerHTML = scenarios.map((scenario) => `
    <button type="button" class="scenario-card ${scenario.code === state.selectedScenarioCode ? "active" : ""}" data-l4-scenario="${escapeHtml(scenario.code)}">
      <span class="scenario-tag">${escapeHtml(scenario.interface)}</span>
      <strong>${escapeHtml(scenario.title)}</strong>
      <p>${escapeHtml(scenario.l4_application)}</p>
      <small>${escapeHtml(scenario.service_code)} · ${escapeHtml(scenario.downstream)}</small>
    </button>
  `).join("");
  $("#l4ScenarioSelect").innerHTML = scenarios.map((scenario) => `<option value="${escapeHtml(scenario.code)}">${escapeHtml(scenario.title)}</option>`).join("");
  syncL4ScenarioForm(false);

  const calls = state.data.l4Requests || [];
  $("#l4RequestRows").innerHTML = calls.length ? calls.map((call) => {
    const scenario = l4ScenarioByCode(call.scenario_code);
    const tone = statusTone(call.response_type);
    return `<tr>
      <td class="asset-cell"><strong>${escapeHtml(call.trace_id)}</strong><small>${escapeHtml(call.request_id)}</small></td>
      <td>${escapeHtml(scenario?.title || call.scenario_code)}<br><span class="muted">${escapeHtml(call.service_code)}</span></td>
      <td>${escapeHtml(call.request_mode === "natural_language" ? "自然语言" : "格式化请求")}</td>
      <td>${badge(l4ResponseLabel(call.response_type), tone)}</td>
      <td>${escapeHtml(call.decision_code)}</td>
      <td>${escapeHtml(formatTime(call.created_at))}</td>
      <td><button type="button" data-l4-action="detail" data-id="${escapeHtml(call.request_id)}">查看调用链</button></td>
    </tr>`;
  }).join("") : `<tr><td colspan="7"><div class="empty-state">当前真人还没有 L4 场景请求</div></td></tr>`;
  renderL4Result();
}

function renderL4Result() {
  const panel = $("#l4ResultPanel");
  const result = state.l4Result;
  if (!result) {
    panel.classList.add("hidden");
    return;
  }
  const response = result.standard_response || {};
  const resolvedAsset = result.resolved_asset;
  const tone = statusTone(result.response_type);
  $("#l4ResultBoundary").textContent = result.execution_boundary || "数字资产引擎只返回受治理的资产与调用边界，不执行真实业务处理。";
  $("#l4ResponseSummary").innerHTML = [
    ["标准回复", l4ResponseLabel(result.response_type)],
    ["追踪编号", result.trace_id],
    ["服务代码", result.service_code],
    ["定位资产", resolvedAsset?.asset_name || result.asset_id || "拒绝时不暴露资产"],
    ["判定代码", result.decision_code],
  ].map(([label, value], index) => `<div class="response-meta"><span>${escapeHtml(label)}</span><strong class="${index === 0 ? tone : ""}">${escapeHtml(value || "—")}</strong></div>`).join("");

  const decisions = result.decisions || {};
  $("#l4DecisionGrid").innerHTML = Object.keys(decisions).length ? Object.entries(decisions).map(([key, decision]) => {
    const labels = {
      sourceAllowed: "L4 来源白名单",
      actorResolved: "当前真人定位",
      serviceMatched: "服务目录匹配",
      resourceCallable: "资源调用权限",
      businessDataBoundary: "业务数据边界",
    };
    return decisionCard(labels[key] || key, decision, decision.reason || "服务端未返回说明");
  }).join("") : `<div class="empty-state">当前身份只能查看调用技术元数据</div>`;

  const route = result.route || [];
  $("#l4Route").innerHTML = route.length ? route.map((step) => `
    <article class="route-step ${result.response_type === "rejected" && (step.component === "数字资产引擎" || step.layer === "L4" && step.action === "接收标准回复") ? "denied" : ""}">
      <span class="route-seq">${escapeHtml(step.seq)}</span>
      <span class="route-layer">${escapeHtml(step.layer)}</span>
      <strong>${escapeHtml(step.component)}</strong>
      <div><b>${escapeHtml(step.action || "")}</b><p>${escapeHtml(step.result || "")}</p></div>
    </article>
  `).join("") : `<div class="empty-state">调用链已脱敏</div>`;
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function submitL4Request(form) {
  const values = Object.fromEntries(new FormData(form));
  try {
    const payload = await request("/api/l4/requests", {
      method: "POST",
      body: {
        scenario_code: values.scenarioCode,
        request_mode: values.requestMode,
        request_text: values.requestText,
        source_layer: values.sourceLayer,
      },
    });
    state.l4Result = payload.data;
    await loadState(state.actorId);
    routeTo("l4", false);
    toast(payload.message || "L4 请求已完成治理验证");
  } catch (error) {
    toast(`${error.code ? `[${error.code}] ` : ""}${error.message}`, true);
  }
}

function renderRuntime() {
  const targets = state.data.assets
    .filter((asset) => ["agent", "skill"].includes(assetType(asset)) && asset.resourceCallable === true && capability(asset, "viewContent"))
    .sort((a, b) => (assetType(a) === "agent" ? -1 : 1) - (assetType(b) === "agent" ? -1 : 1));
  const select = $("#runtimeTargetSelect");
  const previous = select.value;
  select.innerHTML = targets.length
    ? targets.map((asset) => `<option value="${escapeHtml(assetId(asset))}">${escapeHtml(typeLabel(assetType(asset)))} · ${escapeHtml(assetName(asset))}</option>`).join("")
    : `<option value="">当前真人没有可调用的 Agent 或技能</option>`;
  if (targets.some((asset) => assetId(asset) === previous)) select.value = previous;
  select.disabled = !targets.length;
  $("#runtimeForm button[type='submit']").disabled = !targets.length;

  const result = state.runtimeResult;
  const resultPanel = $("#runtimeResult");
  if (!result) {
    resultPanel.innerHTML = `<div class="empty-state">尚未执行。选择 Agent 或技能后提交真实参数。</div>`;
  } else {
    const output = result.output || {};
    const abnormalItems = output.abnormal_items || [];
    resultPanel.innerHTML = `
      <div class="panel-head"><div><h3>本次固定工具联调结果</h3><p>追踪编号 ${escapeHtml(result.trace_id)}；跨引擎执行为联调 Mock</p></div>${badge(output.conclusion === "abnormal" ? "发现异常" : "参数正常", output.conclusion === "abnormal" ? "danger" : "success")}</div>
      <div class="runtime-evidence">
        ${meta("固定工具", `${result.tool_id}@${result.tool_version}`)}
        ${meta("规则版本", output.rule_version || "—")}
        ${meta("异常项", String(output.abnormal_count ?? 0))}
        ${meta("确认状态", result.confirmation_status || "—")}
      </div>
      <div class="runtime-route">${(result.route || []).map((step, index) => `<span><b>${index + 1}</b>${escapeHtml(step)}</span>`).join("")}</div>
      ${abnormalItems.length ? `<ul class="rule-list">${abnormalItems.map((item) => `<li><b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.message)}；期望 ${escapeHtml(item.expected)}</span></li>`).join("")}</ul>` : `<div class="masked-notice success-note">全部参数在固定规则范围内，无需人工确认。</div>`}
      ${result.confirmation_status === "pending" ? `<button type="button" class="primary" data-runtime-confirm="${escapeHtml(result.execution_id)}">由当前真人确认结果</button>` : ""}
    `;
  }

  const rows = state.data.executions || [];
  $("#executionRows").innerHTML = rows.length ? rows.map((item) => {
    const output = item.output || {};
    const chain = item.agent_asset_id ? `Agent → ${item.skill_asset_id}` : `技能 ${item.skill_asset_id}`;
    return `<tr><td>${escapeHtml(item.trace_id)}</td><td>${escapeHtml(chain)}</td><td>${escapeHtml(`${item.tool_id}@${item.tool_version}`)}</td><td>${item.metadataOnly ? "已脱敏" : badge(output.conclusion || item.status, output.conclusion === "abnormal" ? "danger" : "success")}</td><td>${escapeHtml(item.confirmation_status || "—")}</td><td>${escapeHtml(formatTime(item.created_at))}</td></tr>`;
  }).join("") : `<tr><td colspan="6"><div class="empty-state">当前真人还没有执行记录</div></td></tr>`;
}

async function submitRuntime(form) {
  const values = Object.fromEntries(new FormData(form));
  const target = findAsset(values.targetId);
  if (!target) return toast("目标资产已不在当前可调用集合", true);
  try {
    const payload = await request("/api/l4/capability-executions", {
      method: "POST",
      body: {
        source_layer: "L4",
        target_asset_id: values.targetId,
        service_code: `function.${assetType(target)}.runtime`,
        request_text: "检查当前批次的温度、pH和溶氧并返回异常项",
        input: { temperature_c: Number(values.temperature), ph: Number(values.ph), dissolved_oxygen_pct: Number(values.oxygen) },
      },
    });
    state.runtimeResult = payload.data;
    await loadState(state.actorId);
    routeTo("runtime", false);
    toast(payload.message || "固定工具联调已完成");
  } catch (error) {
    toast(`${error.code ? `[${error.code}] ` : ""}${error.message}`, true);
  }
}

async function confirmRuntime(executionId) {
  try {
    const payload = await request(`/api/executions/${encodeURIComponent(executionId)}/confirm`, { method: "POST", body: {} });
    state.runtimeResult = payload.data;
    await loadState(state.actorId);
    routeTo("runtime", false);
    toast(payload.message || "结果已由当前真人确认");
  } catch (error) {
    toast(`${error.code ? `[${error.code}] ` : ""}${error.message}`, true);
  }
}

function renderCreatePage() {
  $("#assetTypeCards").innerHTML = Object.entries(ASSET_TYPES).map(([key, item]) => `
    <button type="button" class="type-card ${key === state.selectedType ? "active" : ""}" data-asset-type="${key}">
      <span>${escapeHtml(item.label)}</span><strong>创建${escapeHtml(item.label)}</strong><p>${escapeHtml(item.copy)}</p>
    </button>
  `).join("");

  const typeSelect = $("#assetTypeSelect");
  typeSelect.innerHTML = Object.entries(ASSET_TYPES).map(([key, item]) => `<option value="${key}">${escapeHtml(item.label)}</option>`).join("");
  typeSelect.value = state.selectedType;
  $("#assetFormTitle").textContent = `创建${typeLabel(state.selectedType)}草稿`;

  const skillMode = state.selectedType === "skill";
  const agentMode = state.selectedType === "agent";
  $("#skillDevelopmentFields").classList.toggle("hidden", !skillMode);
  $("#agentSkillField").classList.toggle("hidden", !agentMode);
  $("#agentSkillSelect").required = agentMode;
  $("#agentEntrySkillSelect").required = agentMode;
  $("#assetToolSelect").innerHTML = `<option value="">请选择已登记固定工具</option>${state.data.tools.map((tool) =>
    `<option value="${escapeHtml(`${tool.tool_id}@${tool.version}`)}">${escapeHtml(tool.tool_name)} · ${escapeHtml(tool.version)}</option>`
  ).join("")}`;
  const callableSkills = state.data.assets.filter((asset) => assetType(asset) === "skill" && asset.resourceCallable === true);
  $("#agentSkillSelect").innerHTML = callableSkills.length
    ? callableSkills.map((asset) => `<option value="${escapeHtml(assetId(asset))}">${escapeHtml(assetName(asset))} · ${escapeHtml(assetId(asset))}</option>`).join("")
    : `<option value="" disabled>当前真人没有可关联的已启用技能</option>`;
  $("#agentEntrySkillSelect").innerHTML = callableSkills.length
    ? callableSkills.map((asset) => `<option value="${escapeHtml(assetId(asset))}">${escapeHtml(assetName(asset))}</option>`).join("")
    : `<option value="">当前真人没有可用入口Skill</option>`;
  const reusableAssets = (type) => state.data.assets.filter((asset) =>
    assetType(asset) === type && ["personal_active", "published"].includes(asset.status) && capability(asset, "viewContent")
  );
  const dependencyOptions = (items, empty) => items.length
    ? items.map((asset) => `<option value="${escapeHtml(assetId(asset))}">${escapeHtml(assetName(asset))} · ${escapeHtml(scopeLabel(asset.scope))}</option>`).join("")
    : `<option value="" disabled>${escapeHtml(empty)}</option>`;
  $("#agentKnowledgeBaseSelect").innerHTML = dependencyOptions(reusableAssets("knowledge_base"), "当前没有可关联知识库");
  ["inputDefinition", "outputDefinition", "acceptanceCriteria"].forEach((name) => {
    const field = document.querySelector(`[name="${name}"]`);
    if (field) field.required = skillMode;
  });
  syncSkillCreationMode();

  const policies = state.data.scopePolicies || {};
  const allowedScopes = currentActor()?.allowedCreateScopes;
  const scopes = Array.isArray(allowedScopes) && allowedScopes.length
    ? allowedScopes
    : (Object.keys(policies).length ? Object.keys(policies) : ["personal"]);
  $("#assetScopeSelect").innerHTML = scopes.map((scope) => {
    const policy = policies[scope] || {};
    const note = policy.createAllowed === false ? "（服务端可能拒绝）" : "";
    return `<option value="${escapeHtml(scope)}">${escapeHtml(scopeLabel(scope))}${note}</option>`;
  }).join("");
}

function syncSkillCreationMode() {
  const mode = $("#skillCreationMode")?.value || "bind_existing";
  const requestMode = mode === "request_development";
  $("#skillToolField")?.classList.toggle("hidden", requestMode);
  $("#skillCandidateSourceField")?.classList.toggle("hidden", !requestMode);
  if ($("#assetToolSelect")) $("#assetToolSelect").required = state.selectedType === "skill" && !requestMode;
  ["primaryModelId", "primaryModelVersion", "backupModelId", "backupModelVersion",
    "modelDatasetRef", "modelMetricName", "primaryMetricValue", "backupMetricValue"].forEach((name) => {
    const field = document.querySelector(`[name="${name}"]`);
    if (field) field.required = state.selectedType === "skill" && !requestMode;
  });
  const notice = $("#skillDevelopmentNotice");
  if (notice) {
    notice.textContent = requestMode
      ? "需求草稿只是研发任务，不具备执行能力，不能个人启用、发布，也不能被 Agent 绑定。实现进入固定工具登记库后，必须回到资产详情“绑定实现”并运行固定测试。"
      : "绑定已有工具只代表实现已找到，不代表验证通过。创建后仍须在资产详情运行固定测试，测试通过后才能启用或进入发布审批。";
  }
}

function catalogFilteredAssets() {
  const actor = currentActor();
  const id = currentActorId();
  const query = $("#catalogSearch")?.value.trim().toLowerCase() || "";
  const type = $("#catalogTypeFilter")?.value || "";
  const status = $("#catalogStatusFilter")?.value || "";
  return state.data.assets.filter((asset) => {
    const owner = asset.owner_real_id ?? asset.owner_id;
    const creator = asset.creator_id ?? owner;
    const maintainer = asset.maintainer_id;
    let modeMatch = true;
    if (state.catalogMode === "personal") modeMatch = asset.scope === "personal" && owner === id && ["draft", "personal_active"].includes(asset.status);
    if (state.catalogMode === "created") modeMatch = creator === id;
    if (state.catalogMode === "maintained") modeMatch = maintainer === id;
    if (state.catalogMode === "department") modeMatch = asset.scope === "department" && asset.owner_department === actor?.department && asset.status === "published";
    // 标签仅用于登记说明和检索；服务端已经先按当前真人过滤可见集，
    // 这里不能把标签当作任何权限条件。
    const tagText = (asset.tags || []).map((tag) => `${tag.key || ""} ${tag.value || ""}`).join(" ");
    const haystack = [assetId(asset), assetName(asset), actorName(owner), asset.description, tagText].join(" ").toLowerCase();
    return modeMatch && (!query || haystack.includes(query)) && (!type || assetType(asset) === type) && (!status || asset.status === status);
  });
}

function renderCatalog() {
  const types = [...new Set(state.data.assets.map(assetType))];
  const statuses = [...new Set(state.data.assets.map((asset) => asset.status).filter(Boolean))];
  fillFilter($("#catalogTypeFilter"), "全部类型", types, typeLabel);
  fillFilter($("#catalogStatusFilter"), "全部状态", statuses, statusLabel);
  $$("#catalogModes button").forEach((button) => button.classList.toggle("active", button.dataset.mode === state.catalogMode));

  const assets = catalogFilteredAssets();
  $("#catalogCount").textContent = `${assets.length} 项（服务端可见集内）`;
  $("#catalogRows").innerHTML = assets.length ? assets.map(renderAssetRow).join("") : `<tr><td colspan="8"><div class="empty-state">当前视图暂无匹配资产</div></td></tr>`;

  if (state.selectedAssetId) {
    const selected = state.data.assets.find((asset) => assetId(asset) === state.selectedAssetId);
    if (selected) renderAssetDetail(selected);
    else closeAssetDetail();
  }
}

function fillFilter(select, firstLabel, values, labeler) {
  if (!select) return;
  const previous = select.value;
  select.innerHTML = `<option value="">${escapeHtml(firstLabel)}</option>${values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(labeler(value))}</option>`).join("")}`;
  if (values.includes(previous)) select.value = previous;
}

function renderAssetRow(asset) {
  const ownerId = asset.owner_real_id ?? asset.owner_id;
  return `<tr>
    <td class="asset-cell"><strong>${escapeHtml(assetName(asset))}</strong><small>${escapeHtml(assetId(asset))}${asset.derived_from_asset_id ? ` · 来源 ${escapeHtml(asset.derived_from_asset_id)}` : ""}</small></td>
    <td>${escapeHtml(typeLabel(assetType(asset)))}</td>
    <td>${escapeHtml(asset.owner_department || "—")}<br><span class="muted">${escapeHtml(actorName(ownerId))}</span></td>
    <td>${escapeHtml(scopeLabel(asset.scope))}</td>
    <td>${badge(statusLabel(asset.status), statusTone(asset.status))}${isMetadataOnly(asset) ? `<br><span class="badge danger">仅元数据</span>` : ""}</td>
    <td>${escapeHtml(asset.current_version || asset.version || "v1.0")}</td>
    <td>${escapeHtml(formatTime(asset.updated_at || asset.created_at))}</td>
    <td><div class="table-actions">${assetActionButtons(asset)}</div></td>
  </tr>`;
}

function assetActionButtons(asset) {
  const id = escapeHtml(assetId(asset));
  const buttons = [];
  if (capability(asset, "viewMetadata") || capability(asset, "viewContent")) buttons.push(`<button type="button" data-asset-action="detail" data-id="${id}">详情</button>`);
  if (capability(asset, "modify")) buttons.push(`<button type="button" data-asset-action="update" data-id="${id}">修改</button>`);
  if (capability(asset, "submitSkillDevelopment")) buttons.push(`<button type="button" class="primary" data-asset-action="submit-skill-development" data-id="${id}">提交研发</button>`);
  if (capability(asset, "bindSkillImplementation")) {
    const bound = Boolean(asset.config?.tool_id && asset.config?.tool_version);
    buttons.push(`<button type="button" class="secondary" data-asset-action="bind-skill-implementation" data-id="${id}">${bound ? "更换实现" : "绑定实现"}</button>`);
  }
  if (capability(asset, "validateSkill")) buttons.push(`<button type="button" class="secondary" data-asset-action="validate-skill" data-id="${id}">运行技能测试</button>`);
  if (capability(asset, "registerModelEvaluation")) buttons.push(`<button type="button" class="secondary" data-asset-action="model-evaluation" data-id="${id}">登记主备模型</button>`);
  if (capability(asset, "requestL1KnowledgeBase")) buttons.push(`<button type="button" class="primary" data-asset-action="request-l1-kb" data-id="${id}">申请L1建库</button>`);
  if (capability(asset, "activatePersonal")) buttons.push(`<button type="button" class="secondary" data-asset-action="activate-personal" data-id="${id}">个人启用</button>`);
  if (capability(asset, "submitAdoption")) buttons.push(`<button type="button" class="secondary" data-asset-action="submit-adoption" data-id="${id}">申请部门采纳</button>`);
  if (capability(asset, "submitPublish")) buttons.push(`<button type="button" class="primary" data-asset-action="submit-publish" data-id="${id}">提交发布审批</button>`);
  if (capability(asset, "disable")) buttons.push(`<button type="button" data-asset-action="disable" data-id="${id}">停用</button>`);
  if (capability(asset, "deleteDraft")) buttons.push(`<button type="button" class="danger-outline" data-asset-action="delete-draft" data-id="${id}">删除草稿</button>`);
  return buttons.length ? buttons.join("") : `<span class="muted">无可执行动作</span>`;
}

function renderAssetDetail(asset) {
  const detail = $("#assetDetail");
  const resource = resourceDecision(asset);
  const data = dataDecision(asset);
  const relatedSources = state.data.sources.filter((source) => source.asset_id === assetId(asset));
  const versions = state.data.versions.filter((version) => version.asset_id === assetId(asset));
  const derived = asset.derived_from_asset_id ? state.data.assets.find((item) => assetId(item) === asset.derived_from_asset_id) : null;
  const validations = state.data.validations.filter((item) => item.asset_id === assetId(asset));
  const developmentRequests = (state.data.developmentRequests || []).filter((item) => item.asset_id === assetId(asset));
  const kbInstance = (state.data.knowledgeBaseInstances || []).find((item) => item.asset_id === assetId(asset));
  const config = asset.config || {};
  const requirement = config.requirement || {};
  const modelEvaluations = asset.modelEvaluations || [];
  const primaryModel = modelEvaluations.find((item) => item.model_role === "primary");
  const backupModel = modelEvaluations.find((item) => item.model_role === "backup");
  const developmentEvidence = assetType(asset) === "skill" && developmentRequests.length ? `
    <div class="panel-head"><div><h3>Skill 研发任务</h3><p>这是需求与实现之间的技术交接记录，不等于数字资产引擎已经自动生成代码；技术接入身份只能看到脱敏任务元数据。</p></div></div>
    <div class="compact-list">${developmentRequests.map((item) => `
      <article class="compact-item">
        <strong>${escapeHtml(item.development_id)} · ${escapeHtml(developmentStatusLabel(item.status))}</strong>
        <span>目标：${escapeHtml(item.target_system || "待分派")} · 提交人：${escapeHtml(actorName(item.submitter_id))} · 更新时间：${escapeHtml(formatTime(item.updated_at))}</span>
        ${item.candidate_tool_id ? `<span>候选：${escapeHtml(item.candidate_tool_id)}@${escapeHtml(item.candidate_tool_version)} · 回传方式：${escapeHtml(item.callback_mode === "mock" ? "演示 Mock" : "外部接口")}</span>` : `<span>尚未回传可执行候选，当前 Skill 仍不可调用。</span>`}
        <div class="table-actions">
          ${capability(item, "registerCandidate") ? `<button type="button" class="secondary" data-development-action="register-candidate" data-id="${escapeHtml(item.development_id)}">演示：模拟候选回传</button>` : ""}
          ${capability(item, "bindCandidate") ? `<button type="button" class="primary" data-asset-action="bind-skill-implementation" data-id="${escapeHtml(assetId(asset))}">绑定候选实现</button>` : ""}
        </div>
      </article>`).join("")}</div>` : assetType(asset) === "skill" && !isMetadataOnly(asset) ? `<div class="empty-state">尚未提交研发任务。需求草稿不会自动变成可执行 Skill。</div>` : "";
  const executableEvidence = assetType(asset) === "skill" && !isMetadataOnly(asset) ? `
    <div class="panel-head"><div><h3>Skill 研发与执行状态</h3><p>需求说明、可执行实现和测试证据是三件不同的事；只有最后一项通过，Skill 才能启用。</p></div></div>
    <div class="detail-meta">
      ${meta("生命周期阶段", skillStageLabel(config.lifecycle_stage))}
      ${meta("实现来源", skillCandidateSourceLabel(config.candidate_source))}
      ${meta("固定工具", config.tool_id || "未绑定")}
      ${meta("工具版本", config.tool_version || "—")}
      ${meta("验证状态", config.validation_status || "未验证")}
      ${meta("固定测试", `${validations.filter((item) => item.passed).length}/${validations.length} 通过`)}
      ${meta("主力模型", primaryModel ? `${primaryModel.model_id}@${primaryModel.model_version} · ${primaryModel.metric_name}=${primaryModel.metric_value}` : "未登记")}
      ${meta("备用模型", backupModel ? `${backupModel.model_id}@${backupModel.model_version} · ${backupModel.metric_name}=${backupModel.metric_value}` : "未登记")}
    </div>
    <div class="detail-meta">
      ${meta("输入定义", requirement.input_definition || "未填写")}
      ${meta("输出定义", requirement.output_definition || "未填写")}
      ${meta("验收标准", requirement.acceptance_criteria || "未填写")}
      ${meta("下一步", skillNextStep(config))}
    </div>` : assetType(asset) === "agent" && !isMetadataOnly(asset) ? `
    <div class="panel-head"><div><h3>Agent 编排关系</h3><p>Agent 不自行计算，只调用以下已发布技能。</p></div></div>
    <div class="detail-meta">
      ${meta("入口Skill", config.entry_skill_id || config.skill_ids?.[0] || "未配置")}
      ${meta("可用Skill", (config.skill_ids || []).join("、") || "无")}
      ${meta("关联知识库", (config.knowledge_base_ids || []).join("、") || "无")}
      ${meta("附件引用", (config.attachment_refs || []).join("、") || "无")}
    </div>` : "";
  const knowledgeBaseEvidence = assetType(asset) === "knowledge_base" ? `
    <div class="panel-head"><div><h3>L2 资产登记与 L1 知识库实例</h3><p>这里必须分清两层：本页面的知识库是 L2 治理资产；真正的切片、向量化和检索空间属于 L1 1.13。两者通过实例编号和命名空间显式映射。</p></div></div>
    <div class="decision-grid">
      <article class="decision-card"><strong>L2 知识库资产 · 已登记</strong><p>资产编号：${escapeHtml(assetId(asset))}</p><p>负责名称、责任人、范围、版本、权限和留痕，不执行文档解析或向量化。</p></article>
      <article class="decision-card ${kbInstance?.status === "ready" ? "" : "denied"}"><strong>L1 知识库实例 · ${escapeHtml(statusLabel(kbInstance?.status || "not_started"))}</strong><p>${kbInstance ? `申请编号：${escapeHtml(kbInstance.binding_id)} · L1实例：${escapeHtml(kbInstance.l1_kb_id || "未返回")} · 命名空间：${escapeHtml(kbInstance.namespace || "未返回")}` : "尚未申请 L1 实例；当前只能登记资产和原件，不能宣称可检索。"}</p><p>${kbInstance?.callback_mode === "mock" ? "演示 Mock 回执，不代表真实 L1 已接通。" : "只有收到 L1 回执后才建立映射。"}</p>${capability(kbInstance, "registerInstance") ? `<button type="button" class="secondary" data-kb-binding-action="register" data-id="${escapeHtml(kbInstance.binding_id)}">演示：Mock L1建库回调</button>` : ""}</article>
    </div>
    <div class="compact-list">${relatedSources.length ? relatedSources.map((source) => `<article class="compact-item"><strong>${escapeHtml(source.file_name)} · ${escapeHtml(statusLabel(source.vector_status))}</strong><span>解析：${escapeHtml(statusLabel(source.parse_status))} · 索引：${escapeHtml(source.index_evidence ? `${source.index_evidence.chunk_count} 切片 / ${source.index_evidence.vector_count} 向量 / ${source.index_evidence.index_version}` : "无索引证据")}</span></article>`).join("") : `<div class="empty-state">尚未登记知识源。没有知识源就不存在可检索内容。</div>`}</div>` : "";

  detail.innerHTML = `
    <div class="detail-header">
      <div><h3>${escapeHtml(assetName(asset))}</h3><p>${escapeHtml(asset.description || "暂无说明")}</p></div>
      <div>${badge(statusLabel(asset.status), statusTone(asset.status))} ${badge(scopeLabel(asset.scope), "info")}</div>
    </div>
    ${isMetadataOnly(asset) ? `<div class="masked-notice">当前真人只能查看技术元数据；业务内容、原件和解析内容已由服务端脱敏。</div>` : ""}
    <div class="detail-meta">
      ${meta("资产编号", assetId(asset))}
      ${meta("资产类型", typeLabel(assetType(asset)))}
      ${meta("创建人", actorName(asset.creator_id))}
      ${meta("责任人", actorName(asset.owner_real_id))}
      ${meta("维护人", actorName(asset.maintainer_id))}
      ${meta("当前版本", asset.current_version || "v1.0")}
      ${meta("贡献人", actorName(asset.contributor_id))}
      ${meta("归属部门", asset.owner_department || "—")}
      ${meta("知识源", `${relatedSources.length} 项`)}
      ${meta("标签", (asset.tags || []).map((tag) => `${tag.key}:${tag.value}`).join("、") || "无")}
      ${meta("版本记录", `${versions.length} 条`)}
      ${meta("衍生自", asset.derived_from_asset_id || "无")}
      ${meta("更新时间", formatTime(asset.updated_at || asset.created_at))}
    </div>
    ${asset.derived_from_asset_id ? `<div class="compact-item"><strong>采纳来源关系</strong><span>部门草稿 ${escapeHtml(assetId(asset))} 从个人资产 ${escapeHtml(asset.derived_from_asset_id)} 衍生；原个人资产仍由原创建人保留。${derived ? `来源名称：${escapeHtml(assetName(derived))}` : ""}</span></div>` : ""}
    <div class="decision-grid">
      ${decisionCard("资源可调用判定", resource, "判断当前真人能否发现并调用这个数字资源")}
      ${decisionCard("资产内容访问判定", data, "由外部权限管理 Mock 按当前真人实时判定；标签不承载权限")}
    </div>
    ${executableEvidence}
    ${developmentEvidence}
    ${knowledgeBaseEvidence}
    <div class="panel-head"><div><h3>服务端能力矩阵</h3><p>下列能力仅展示服务端返回为 true 的项目；前端不推导权限。</p></div></div>
    <div class="capability-list">${Object.entries(asset.capabilities || {}).filter(([, enabled]) => enabled === true).map(([key]) => badge(key, "info")).join("") || `<span class="muted">没有可执行能力</span>`}</div>
  `;
  detail.classList.remove("hidden");
  detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function skillStageLabel(stage) {
  return ({
    requirement_draft: "研发需求草稿",
    development_submitted: "研发任务已提交",
    candidate_ready: "候选实现已回传",
    implementation_bound: "已绑定实现，待测试",
    validation_passed: "固定测试通过",
    validation_failed: "固定测试失败",
  })[stage] || "待完善";
}

function skillCandidateSourceLabel(source) {
  return ({
    undecided: "待分派",
    evolution: "L1 进化机制代码候选",
    developer: "研发人员实现",
    existing_api: "已有 API / 工具",
    workflow: "流程编排组合",
  })[source] || "未登记";
}

function skillNextStep(config) {
  if (config.lifecycle_stage === "development_submitted") return "等待进化机制/研发队列回传候选实现；当前不可调用";
  if (config.lifecycle_stage === "candidate_ready") return "由需求创建人核对候选版本并绑定，再运行固定测试";
  if (!config.tool_id || !config.tool_version) return "交给进化机制/研发人员产出候选实现，再绑定登记版本";
  if (config.validation_status !== "passed") return "运行固定测试；失败则回到实现方修复，不能启用";
  return "可个人启用，或按固定审批模板提交部门/公司发布";
}

function developmentStatusLabel(status) {
  return ({
    submitted: "已提交研发",
    candidate_received: "候选已接收",
    ready_to_bind: "候选待绑定",
    bound: "候选已绑定",
    rejected: "候选被退回",
  })[status] || status || "未知状态";
}

function meta(label, value) {
  return `<div class="meta-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "—")}</strong></div>`;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function decisionCard(title, decision, copy) {
  const allowed = decision.allowed === true;
  return `<article class="decision-card ${allowed ? "" : "denied"}"><strong>${escapeHtml(title)} · ${allowed ? "允许" : "拒绝"}</strong><p>${escapeHtml(decision.reason || copy)}</p><p>${escapeHtml(copy)}</p></article>`;
}

function closeAssetDetail() {
  state.selectedAssetId = "";
  $("#assetDetail").classList.add("hidden");
  $("#assetDetail").innerHTML = "";
}

function renderWorkflows() {
  const flows = state.data.workflows;
  const pending = flows.filter((flow) => flow.status === "pending");
  const mine = pending.filter((flow) => flow.submitter_id === currentActorId());
  const tasks = pending.filter((flow) => capability(flow, "approve") || capability(flow, "reject"));
  const approved = flows.filter((flow) => flow.status === "approved");
  const stats = [
    ["待审批流程", pending.length, "服务端可见范围", pending.length ? "warning" : ""],
    ["我的申请", mine.length, "由我提交的待处理流程", ""],
    ["我的审批待办", tasks.length, "按固定岗位定位", tasks.length ? "danger" : ""],
    ["已批准", approved.length, "采纳与发布分两步留痕", "success"],
  ];
  $("#workflowStats").innerHTML = stats.map(([label, value, note, tone]) => `<article class="stat-card ${tone}"><span>${escapeHtml(label)}</span><strong>${value}</strong><small>${escapeHtml(note)}</small></article>`).join("");
  $("#workflowList").innerHTML = flows.length ? flows.map(renderWorkflowCard).join("") : `<div class="empty-state">当前真人没有可见流程</div>`;
}

function renderWorkflowCard(flow) {
  const asset = state.data.assets.find((item) => assetId(item) === flow.asset_id);
  const result = flow.result_asset_id ? state.data.assets.find((item) => assetId(item) === flow.result_asset_id) : null;
  const actions = [];
  if (capability(flow, "approve")) actions.push(`<button type="button" class="primary" data-workflow-action="approve" data-id="${escapeHtml(flow.workflow_id)}">批准</button>`);
  if (capability(flow, "reject")) actions.push(`<button type="button" class="danger-outline" data-workflow-action="reject" data-id="${escapeHtml(flow.workflow_id)}">驳回</button>`);
  return `<article class="workflow-card ${escapeHtml(flow.status || "")}">
    <div><h4>${escapeHtml(WORKFLOW_LABELS[flow.kind] ?? flow.kind ?? "审批流程")}</h4><p>${escapeHtml(flow.workflow_id)} · ${escapeHtml(asset ? assetName(asset) : flow.asset_id)}</p>${result ? `<p>已生成部门草稿：${escapeHtml(assetName(result))}（${escapeHtml(flow.result_asset_id)}）</p>` : ""}</div>
    <div class="workflow-route"><span>${escapeHtml(actorName(flow.submitter_id))}</span><i>→</i><span>${escapeHtml(flow.approval_position || "待定位岗位")}</span><i>→</i><span>${escapeHtml(flow.approver_id ? actorName(flow.approver_id) : "运行时按岗找人")}</span></div>
    <div><div>${badge(statusLabel(flow.status), statusTone(flow.status))}</div><div class="workflow-actions">${actions.join("")}</div>${flow.reason ? `<p>${escapeHtml(flow.reason)}</p>` : ""}</div>
  </article>`;
}

function renderSources() {
  const knowledgeBases = state.data.assets.filter((asset) => assetType(asset) === "knowledge_base" && capability(asset, "addSource"));
  $("#sourceAssetSelect").innerHTML = knowledgeBases.length ? knowledgeBases.map((asset) => `<option value="${escapeHtml(assetId(asset))}">${escapeHtml(assetName(asset))} · ${escapeHtml(assetId(asset))}</option>`).join("") : `<option value="">当前真人没有可登记知识源的知识库</option>`;
  $("#sourceRows").innerHTML = state.data.sources.length ? state.data.sources.map(renderSourceRow).join("") : `<tr><td colspan="8"><div class="empty-state">当前真人没有可见知识源记录</div></td></tr>`;
}

function renderSourceRow(source) {
  const asset = state.data.assets.find((item) => assetId(item) === source.asset_id);
  const sourceId = escapeHtml(source.source_id ?? source.id);
  const parseAction = capability(source, "parse") ? `<button type="button" class="secondary" data-source-action="parse" data-id="${sourceId}">触发解析</button>` : "";
  const indexAction = capability(source, "registerIndexResult") ? `<button type="button" class="primary" data-source-action="register-index" data-id="${sourceId}">演示：Mock索引回调</button>` : "";
  const detailAction = capability(source, "viewMetadata") ? `<button type="button" data-source-action="detail" data-id="${sourceId}">元数据</button>` : "";
  const downloadAction = capability(source, "download") ? `<button type="button" data-source-action="download" data-id="${sourceId}">下载原件</button>` : "";
  return `<tr>
    <td class="asset-cell"><strong>${escapeHtml(source.source_id ?? source.id)}</strong><small>${escapeHtml(asset ? assetName(asset) : source.asset_id)}</small></td>
    <td>${escapeHtml(source.file_name || "—")}<br><span class="muted">${escapeHtml(source.source_type || "—")}</span></td>
    <td>${sourceStatus(source.storage_status)}</td>
    <td>${sourceStatus(source.metadata_status ?? "unknown")}</td>
    <td>${sourceStatus(source.vector_status ?? "unknown")}</td>
    <td>${badge(statusLabel(source.parse_status), statusTone(source.parse_status))}<br><span class="muted">${escapeHtml(source.parser_service || "待流程编排")}</span></td>
    <td>${escapeHtml(source.description || source.message || (source.metadataOnly ? "仅技术元数据可见" : "—"))}</td>
    <td><div class="table-actions">${detailAction}${downloadAction}${parseAction}${indexAction}${detailAction || downloadAction || parseAction || indexAction ? "" : `<span class="muted">无可执行动作</span>`}</div></td>
  </tr>`;
}

function sourceStatus(status) {
  const normalized = status || "not_started";
  return `<div class="status-line"><span class="status-dot ${statusTone(normalized)}"></span><span>${escapeHtml(statusLabel(normalized))}</span></div>`;
}

function renderRegistry() {
  const items = state.data.function_registry ?? state.data.registry ?? [];
  $("#registryList").innerHTML = items.length ? items.map((item) => {
    const asset = state.data.assets.find((entry) => assetId(entry) === item.asset_id);
    return `<article class="registry-card">
      <span class="badge info">${escapeHtml(typeLabel(asset ? assetType(asset) : item.asset_type || "skill"))}</span>
      <h4>${escapeHtml(item.function_name || assetName(asset) || item.name)}</h4>
      <p>${escapeHtml(item.description || asset?.description || "已登记到 L2 服务目录")}</p>
      <div class="registry-meta"><span>登记编号：${escapeHtml(item.function_id || item.registry_id || "—")}</span><span>资产编号：${escapeHtml(item.asset_id || "—")}</span><span>服务范围：${escapeHtml(scopeLabel(item.scope || asset?.scope))}</span><span>同步状态：${escapeHtml(statusLabel(item.sync_status || "synced"))}</span><span>执行状态：${asset?.config?.validation_status === "passed" || assetType(asset) === "agent" ? "已具备可执行绑定" : "未验证"}</span><span>数据边界：调用时再次按当前真人判权</span></div>
    </article>`;
  }).join("") : `<div class="empty-state">暂无可见功能登记记录</div>`;
}

function renderAudit() {
  const logs = state.data.logs;
  const denies = logs.filter((log) => String(log.decision_result).toLowerCase().includes("deny") || String(log.result).toLowerCase().includes("deny"));
  const masked = state.data.assets.filter(isMetadataOnly).length;
  const pending = state.data.workflows.filter((flow) => flow.status === "pending").length;
  const cards = [
    ["服务端统一状态源", "已接入", "页面每次操作后重新请求 /api/state，不保存浏览器业务状态。", "result-pass"],
    ["权限拒绝留痕", `${denies.length} 条`, "直接编号访问和越权写操作必须在服务端拒绝并记录。", denies.length ? "result-pass" : "result-warn"],
    ["内容脱敏", `${masked} 项`, "平台技术人员若无数据权限，只返回技术元数据。", masked ? "result-pass" : "result-warn"],
    ["固定审批待办", `${pending} 项`, "审批岗位来自模板，流程中的真人由岗位实时定位。", "result-pass"],
  ];
  $("#verificationCards").innerHTML = cards.map(([label, value, copy, tone]) => `<article class="verification-card"><header><span>${escapeHtml(label)}</span><b class="${tone}">${escapeHtml(value)}</b></header><strong>${escapeHtml(label)}</strong><p>${escapeHtml(copy)}</p></article>`).join("");
  $("#auditRows").innerHTML = logs.length ? logs.map((log) => {
    const decision = String(log.decision_result || log.result || "").toLowerCase();
    const passed = ["allow", "allowed", "success", "pass", "通过", "成功"].some((token) => decision.includes(token));
    return `<tr><td>${escapeHtml(formatTime(log.created_at || log.time))}</td><td>${escapeHtml(log.request_id || log.log_id || "—")}</td><td>${escapeHtml(actorName(log.actor_id))}</td><td>${escapeHtml(log.action || "—")}</td><td>${escapeHtml(log.asset_id || "—")}</td><td>${badge(log.decision_result || log.result || "—", passed ? "success" : "danger")}</td><td>${escapeHtml(log.deny_reason || log.reason || "—")}${log.metadataOnly ? `<br><span class="badge danger">已脱敏</span>` : ""}</td></tr>`;
  }).join("") : `<tr><td colspan="7"><div class="empty-state">当前真人没有可见审计记录</div></td></tr>`;
  const flowTasks = state.data.flowTasks || [];
  $("#flowTaskRows").innerHTML = flowTasks.length ? flowTasks.map((item) => `<tr>
    <td>${escapeHtml(item.task_id)}</td><td>${escapeHtml(item.workflow_instance_id)}</td>
    <td>${escapeHtml(item.trace_id)}</td><td>${escapeHtml(item.service_code)}</td>
    <td>${badge(statusLabel(item.status), statusTone(item.status))}</td><td>${escapeHtml(formatTime(item.created_at))}</td>
  </tr>`).join("") : `<tr><td colspan="6"><div class="empty-state">尚无流程任务；创建一个资产即可生成证据。</div></td></tr>`;
  const calls = state.data.foundationCalls || [];
  $("#foundationCallRows").innerHTML = calls.length ? calls.map((item) => `<tr>
    <td>${escapeHtml(item.request_id || item.call_id)}</td><td>${escapeHtml(item.action)}</td>
    <td>${escapeHtml(item.asset_id || "—")}</td><td>${escapeHtml(item.account_gateway_result || "已脱敏")}</td>
    <td>${escapeHtml(item.permission_result || "已脱敏")}</td><td>${escapeHtml(item.compliance_result || "已脱敏")}</td>
    <td>${escapeHtml(item.adapter_mode || "L1 Mock adapter")}</td>
  </tr>`).join("") : `<tr><td colspan="7"><div class="empty-state">尚无基础模块调用证据。</div></td></tr>`;
}

function routeTo(view, updateHash = true) {
  const allowed = ["overview", "l4", "runtime", "create", "catalog", "workflows", "sources", "registry", "audit"];
  const target = allowed.includes(view) ? view : "overview";
  state.currentView = target;
  $$(".view").forEach((section) => section.classList.toggle("active", section.id === target));
  $$("#sideNav a").forEach((link) => link.classList.toggle("active", link.dataset.view === target));
  if (updateHash && location.hash !== `#${target}`) history.pushState(null, "", `${location.pathname}${location.search}#${target}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function findAsset(id) {
  return state.data.assets.find((asset) => assetId(asset) === id);
}

function handleAssetAction(action, id) {
  const asset = findAsset(id);
  if (!asset) return toast("资产已不在当前服务端可见集中", true);
  if (action === "detail") {
    state.selectedAssetId = id;
    renderAssetDetail(asset);
    return;
  }
  if (action === "update") return openUpdateModal(asset);
  if (action === "submit-skill-development") return openConfirm(
    "提交 Skill 研发需求",
    `提交后，当前需求草稿会被锁定，等待“${escapeHtml(skillCandidateSourceLabel(asset.config?.candidate_source))}”回传候选实现。此操作只创建研发任务，不会自动生成或启用代码。`,
    () => mutate(`/api/assets/${encodeURIComponent(id)}/submit-development`, {}, "Skill 研发任务已提交，等待候选实现回传"),
    "确认提交研发",
  );
  if (action === "bind-skill-implementation") return openSkillBindingModal(asset);
  if (action === "validate-skill") return openConfirm("运行技能固定测试", `服务端将使用已登记工具版本运行固定测试用例。测试通过后才能启用或提交发布。`, () => mutate(`/api/assets/${encodeURIComponent(id)}/validate-skill`, {}, "技能固定测试已通过"), "运行测试");
  if (action === "model-evaluation") return openModelEvaluationModal(asset);
  if (action === "request-l1-kb") return openConfirm(
    "申请 L1 知识库实例",
    `这一步只建立 L2 资产到 L1 1.13 的建库任务。提交后仍不能宣称“可检索”，必须等待 L1 返回实例编号与命名空间，并对知识源返回切片/向量索引证据。`,
    () => mutate(`/api/assets/${encodeURIComponent(id)}/request-l1-knowledge-base`, {}, "L1建库申请已提交，等待技术回调"),
    "提交建库申请",
  );
  if (action === "activate-personal") return openConfirm("个人启用", `个人启用仅供创建人本人使用，不等于公共发布。确认启用“${escapeHtml(assetName(asset))}”？`, () => mutate(`/api/assets/${encodeURIComponent(id)}/activate-personal`, { reason: "创建人个人启用" }, "个人资产已启用"), "确认个人启用");
  if (action === "submit-adoption") return openConfirm("申请部门采纳", `提交后由固定模板定位部门审批岗位。批准后原个人资产转为“已采纳归档”，同时生成带来源关系的部门草稿；部门草稿仍需单独提交发布审批。`, () => mutate(`/api/assets/${encodeURIComponent(id)}/submit-adoption`, { reason: "申请将个人成果采纳为部门资产" }, "采纳申请已提交"), "提交采纳申请");
  if (action === "submit-publish") return openConfirm("提交发布审批", `当前资产将进入${escapeHtml(scopeLabel(asset.scope))}固定发布流程，不会直接变成已发布。审批人由岗位模板定位。`, () => mutate(`/api/assets/${encodeURIComponent(id)}/submit-publish`, { target_scope: asset.scope, reason: "提交公共范围发布审批" }, "发布审批已提交"), "提交审批");
  if (action === "disable") return openConfirm("停用资产", `停用后不再允许调用，版本与审计记录继续保留。确认停用“${escapeHtml(assetName(asset))}”？`, () => mutate(`/api/assets/${encodeURIComponent(id)}/disable`, { reason: "维护人主动停用" }, "资产已停用"), "确认停用", true);
  if (action === "delete-draft") return openConfirm("删除草稿", `只允许创建人删除尚未启用、尚未发布的草稿。服务端会再次校验状态与身份。`, () => mutate(`/api/assets/${encodeURIComponent(id)}/delete-draft`, { reason: "创建人删除草稿" }, "草稿已删除"), "删除草稿", true);
}

function openSkillBindingModal(asset) {
  const tools = state.data.tools || [];
  const development = (state.data.developmentRequests || []).find((item) => item.asset_id === assetId(asset) && item.status === "ready_to_bind");
  const current = asset.config?.tool_id && asset.config?.tool_version
    ? `${asset.config.tool_id}@${asset.config.tool_version}`
    : development?.candidate_tool_id && development?.candidate_tool_version
      ? `${development.candidate_tool_id}@${development.candidate_tool_version}`
    : "";
  const options = tools.map((tool) => {
    const value = `${tool.tool_id}@${tool.version}`;
    return `<option value="${escapeHtml(value)}" ${value === current ? "selected" : ""}>${escapeHtml(tool.tool_name)} · ${escapeHtml(tool.version)}</option>`;
  }).join("");
  openModal("绑定 Skill 可执行实现", `
    <form id="skillBindingForm" class="form-grid">
      <div class="masked-notice full">这里不上传随意代码。只能选择已经进入固定工具登记库、具有明确版本且服务端可执行的实现。${development ? `研发任务 ${escapeHtml(development.development_id)} 已回传候选 ${escapeHtml(development.candidate_tool_id)}@${escapeHtml(development.candidate_tool_version)}。` : ""}绑定或更换实现后，旧测试证据立即失效。</div>
      <label class="full"><span>已登记固定工具 *</span><select name="toolBinding" required><option value="">请选择工具版本</option>${options}</select></label>
      <div class="modal-actions full"><button type="button" class="ghost" data-close-modal>取消</button><button type="submit" class="primary">绑定并进入待测试</button></div>
    </form>
  `);
  $("#skillBindingForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("toolBinding") || "");
    const separator = value.lastIndexOf("@");
    if (separator <= 0) return toast("请选择有效的固定工具版本", true);
    await mutate(`/api/assets/${encodeURIComponent(assetId(asset))}/bind-skill-implementation`, {
      tool_id: value.slice(0, separator),
      tool_version: value.slice(separator + 1),
    }, "Skill 实现已绑定，下一步请运行固定测试");
  });
}

function openModelEvaluationModal(asset) {
  const evaluations = Array.isArray(asset.modelEvaluations) ? asset.modelEvaluations : [];
  const latest = (role) => evaluations.find((item) => item.model_role === role) || {};
  const primary = latest("primary");
  const backup = latest("backup");
  openModal("登记 Skill 主力/备用模型评测", `
    <form id="modelEvaluationForm" class="form-grid">
      <div class="masked-notice full">
        模型登记是 Skill 资产证据，不是权限配置。主力模型和备用模型都必须经过同一数据集、同一指标的评测；登记后仍需完成固定工具测试，才能启用或进入发布审批。
      </div>
      <label><span>主力模型 *</span><input name="primary_model_id" required value="${escapeHtml(primary.model_id || "")}" placeholder="例如：model-fermentation-main" /></label>
      <label><span>主力模型版本 *</span><input name="primary_model_version" required value="${escapeHtml(primary.model_version || "")}" placeholder="例如：1.0.0" /></label>
      <label><span>备用模型 *</span><input name="backup_model_id" required value="${escapeHtml(backup.model_id || "")}" placeholder="例如：model-fermentation-backup" /></label>
      <label><span>备用模型版本 *</span><input name="backup_model_version" required value="${escapeHtml(backup.model_version || "")}" placeholder="例如：1.0.0" /></label>
      <label><span>评测数据集引用 *</span><input name="dataset_ref" required value="${escapeHtml(primary.dataset_ref || backup.dataset_ref || "dataset://skill-evaluation/fixed-v1")}" /></label>
      <label><span>评测指标 *</span><input name="metric_name" required value="${escapeHtml(primary.metric_name || backup.metric_name || "accuracy")}" /></label>
      <label><span>主力模型指标值 *</span><input name="primary_metric_value" type="number" min="0" max="1" step="0.0001" required value="${escapeHtml(primary.metric_value ?? "0.95")}" /></label>
      <label><span>备用模型指标值 *</span><input name="backup_metric_value" type="number" min="0" max="1" step="0.0001" required value="${escapeHtml(backup.metric_value ?? "0.90")}" /></label>
      <label><span>主力评测结论 *</span><select name="primary_conclusion" required><option value="passed" ${primary.conclusion !== "failed" ? "selected" : ""}>通过</option><option value="failed" ${primary.conclusion === "failed" ? "selected" : ""}>不通过</option></select></label>
      <label><span>备用评测结论 *</span><select name="backup_conclusion" required><option value="passed" ${backup.conclusion !== "failed" ? "selected" : ""}>通过</option><option value="failed" ${backup.conclusion === "failed" ? "selected" : ""}>不通过</option></select></label>
      <label class="full"><span>评测报告引用</span><input name="report_ref" value="${escapeHtml(primary.report_ref || backup.report_ref || "")}" placeholder="例如：report://skill-model-evaluation/EV-001" /></label>
      <div class="modal-actions full"><button type="button" class="ghost" data-close-modal>取消</button><button type="submit" class="primary">登记两项评测</button></div>
    </form>
  `);
  $("#modelEvaluationForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    const common = {
      dataset_ref: form.dataset_ref,
      metric_name: form.metric_name,
      report_ref: form.report_ref,
    };
    try {
      await request(`/api/assets/${encodeURIComponent(assetId(asset))}/model-evaluations`, {
        method: "POST",
        body: {
          ...common,
          model_role: "primary",
          model_id: form.primary_model_id,
          model_version: form.primary_model_version,
          metric_value: Number(form.primary_metric_value),
          conclusion: form.primary_conclusion,
        },
      });
      await request(`/api/assets/${encodeURIComponent(assetId(asset))}/model-evaluations`, {
        method: "POST",
        body: {
          ...common,
          model_role: "backup",
          model_id: form.backup_model_id,
          model_version: form.backup_model_version,
          metric_value: Number(form.backup_metric_value),
          conclusion: form.backup_conclusion,
        },
      });
      closeModal();
      await loadState(state.actorId, { message: "主力与备用模型评测已登记" });
      state.selectedAssetId = assetId(asset);
      routeTo("catalog", false);
      renderCatalog();
    } catch (error) {
      toast(`${error.code ? `[${error.code}] ` : ""}${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  });
}

function openCandidateCallbackModal(developmentId) {
  const development = (state.data.developmentRequests || []).find((item) => item.development_id === developmentId);
  if (!development) return toast("研发任务已不在当前服务端可见集中", true);
  const options = (state.data.tools || []).map((tool) => {
    const value = `${tool.tool_id}@${tool.version}`;
    return `<option value="${escapeHtml(value)}">${escapeHtml(tool.tool_name)} · ${escapeHtml(tool.version)}</option>`;
  }).join("");
  openModal("模拟外部候选实现回传", `
    <form id="candidateCallbackForm" class="form-grid">
      <div class="masked-notice full"><strong>这不是进化机制真实生成代码。</strong>这里只模拟外部研发系统完成开发后，通过回调接口把一个已经登记、可执行、带版本的固定工具候选交回数字资产引擎。</div>
      <label class="full"><span>研发任务</span><input value="${escapeHtml(development.development_id)} · ${escapeHtml(development.target_system || "待分派")}" disabled /></label>
      <label class="full"><span>候选固定工具 *</span><select name="toolBinding" required><option value="">请选择已登记工具版本</option>${options}</select></label>
      <label class="full"><span>候选制品引用</span><input name="artifact_uri" placeholder="例如：registry://skill/fermentation-checker/1.0.0" /></label>
      <label class="full"><span>实现方测试报告引用</span><input name="test_report_uri" placeholder="例如：report://skill-tests/DEV-001" /></label>
      <div class="modal-actions full"><button type="button" class="ghost" data-close-modal>取消</button><button type="submit" class="primary">模拟回传候选</button></div>
    </form>
  `);
  $("#candidateCallbackForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    const value = String(body.toolBinding || "");
    const separator = value.lastIndexOf("@");
    if (separator <= 0) return toast("请选择有效的固定工具版本", true);
    delete body.toolBinding;
    body.tool_id = value.slice(0, separator);
    body.tool_version = value.slice(separator + 1);
    body.callback_mode = "mock";
    await mutate(`/api/development-requests/${encodeURIComponent(developmentId)}/register-candidate`, body, "候选实现已回传，等待需求创建人绑定与测试");
  });
}

function openKbInstanceCallbackModal(bindingId) {
  const binding = (state.data.knowledgeBaseInstances || []).find((item) => item.binding_id === bindingId);
  if (!binding) return toast("L1建库申请已不在当前服务端可见集中", true);
  openModal("模拟 L1 知识库实例回调", `
    <form id="kbInstanceCallbackForm" class="form-grid">
      <div class="masked-notice full"><strong>这是 Mock 技术回调，不是真实 L1 已接通。</strong>它只验证数字资产引擎能接收并登记 L1 实例编号、命名空间和回调方式。</div>
      <label><span>L1实例编号 *</span><input name="l1_kb_id" required value="l1kb_${escapeHtml(binding.asset_id).replaceAll(/[^a-zA-Z0-9_-]/g, "_")}" /></label>
      <label><span>命名空间 *</span><input name="namespace" required value="hanhe.demo.${escapeHtml(binding.asset_id).replaceAll(/[^a-zA-Z0-9_-]/g, "_")}" /></label>
      <label class="full"><span>提供方</span><input name="provider" value="L1 1.13 知识库模块 Mock" /></label>
      <div class="modal-actions full"><button type="button" class="ghost" data-close-modal>取消</button><button type="submit" class="primary">登记 Mock 回执</button></div>
    </form>`);
  $("#kbInstanceCallbackForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    body.outcome = "ready";
    body.callback_mode = "mock";
    await mutate(`/api/knowledge-base-instances/${encodeURIComponent(bindingId)}/register`, body, "L1实例Mock回执已登记；下一步解析并索引知识源");
  });
}

function openSourceIndexCallbackModal(sourceId) {
  const source = state.data.sources.find((item) => (item.source_id ?? item.id) === sourceId);
  if (!source) return toast("知识源记录已不可见", true);
  openModal("模拟 L1 切片与向量索引回调", `
    <form id="sourceIndexCallbackForm" class="form-grid">
      <div class="masked-notice full"><strong>这不是数字资产引擎在做向量化。</strong>这里模拟 L1 完成切片和向量索引后，把数量、版本和状态回传给 L2 登记留痕。</div>
      <label><span>切片数量 *</span><input name="chunk_count" type="number" min="1" value="12" required /></label>
      <label><span>向量数量 *</span><input name="vector_count" type="number" min="1" value="12" required /></label>
      <label class="full"><span>索引版本 *</span><input name="index_version" value="mock-v1" required /></label>
      <div class="modal-actions full"><button type="button" class="ghost" data-close-modal>取消</button><button type="submit" class="primary">登记 Mock 索引回执</button></div>
    </form>`);
  $("#sourceIndexCallbackForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    body.outcome = "indexed";
    body.callback_mode = "mock";
    body.chunk_count = Number(body.chunk_count);
    body.vector_count = Number(body.vector_count);
    await mutate(`/api/sources/${encodeURIComponent(sourceId)}/register-index`, body, "L1索引Mock回执已登记；该知识源现在具备可检索证据");
  });
}

function openUpdateModal(asset) {
  openModal("修改资产草稿", `
    <form id="updateAssetForm" class="form-grid">
      <label class="full"><span>资产名称</span><input name="asset_name" required value="${escapeHtml(assetName(asset))}" /></label>
      <label class="full"><span>资产说明</span><textarea name="description" rows="4" required>${escapeHtml(asset.description || "")}</textarea></label>
      <label class="full"><span>修改说明</span><input name="change_reason" required placeholder="说明本次变更内容" /></label>
      <div class="modal-actions full"><button type="button" class="ghost" data-close-modal>取消</button><button type="submit" class="primary">保存并生成版本</button></div>
    </form>
  `);
  $("#updateAssetForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    body.change_summary = body.change_reason;
    await mutate(`/api/assets/${encodeURIComponent(assetId(asset))}/update`, body, "修改成功并生成新版本");
  });
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",").pop());
    reader.onerror = () => reject(new Error("浏览器读取文件失败"));
    reader.readAsDataURL(file);
  });
}

function openConfirm(title, copy, onConfirm, confirmLabel = "确认", danger = false) {
  openModal(title, `<p class="modal-copy">${copy}</p><div class="modal-actions"><button type="button" class="ghost" data-close-modal>取消</button><button type="button" id="modalConfirm" class="${danger ? "danger-outline" : "primary"}">${escapeHtml(confirmLabel)}</button></div>`);
  $("#modalConfirm").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    await onConfirm();
    event.currentTarget.disabled = false;
  });
}

function openModal(title, html) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modal").classList.remove("hidden");
}

function closeModal() {
  $("#modal").classList.add("hidden");
  $("#modalBody").innerHTML = "";
}

function bindEvents() {
  $("#actorSelect").addEventListener("change", (event) => {
    clearActorEphemeralState();
    loadState(event.target.value, { message: "已切换真人并清空上一位真人的临时界面数据" });
  });

  $("#sideNav").addEventListener("click", (event) => {
    const link = event.target.closest("a[data-view]");
    if (!link) return;
    event.preventDefault();
    routeTo(link.dataset.view);
  });

  document.addEventListener("click", (event) => {
    const jump = event.target.closest("[data-jump]");
    if (jump) routeTo(jump.dataset.jump);
    const type = event.target.closest("[data-asset-type]");
    if (type) {
      state.selectedType = type.dataset.assetType;
      renderCreatePage();
    }
    const scenarioCard = event.target.closest("[data-l4-scenario]");
    if (scenarioCard) {
      state.selectedScenarioCode = scenarioCard.dataset.l4Scenario;
      syncL4ScenarioForm(true);
    }
    const mode = event.target.closest("#catalogModes [data-mode]");
    if (mode) {
      state.catalogMode = mode.dataset.mode;
      closeAssetDetail();
      renderCatalog();
    }
    const assetAction = event.target.closest("[data-asset-action]");
    if (assetAction) handleAssetAction(assetAction.dataset.assetAction, assetAction.dataset.id);
    const developmentAction = event.target.closest("[data-development-action]");
    if (developmentAction?.dataset.developmentAction === "register-candidate") {
      openCandidateCallbackModal(developmentAction.dataset.id);
    }
    const kbBindingAction = event.target.closest("[data-kb-binding-action]");
    if (kbBindingAction?.dataset.kbBindingAction === "register") {
      openKbInstanceCallbackModal(kbBindingAction.dataset.id);
    }
    const workflowAction = event.target.closest("[data-workflow-action]");
    if (workflowAction) handleWorkflowAction(workflowAction.dataset.workflowAction, workflowAction.dataset.id);
    const sourceAction = event.target.closest("[data-source-action]");
    if (sourceAction) handleSourceAction(sourceAction.dataset.sourceAction, sourceAction.dataset.id);
    const l4Action = event.target.closest("[data-l4-action]");
    if (l4Action?.dataset.l4Action === "detail") {
      const call = state.data.l4Requests.find((item) => item.request_id === l4Action.dataset.id);
      if (call) {
        state.l4Result = call;
        renderL4Result();
      }
    }
    const runtimeConfirm = event.target.closest("[data-runtime-confirm]");
    if (runtimeConfirm) confirmRuntime(runtimeConfirm.dataset.runtimeConfirm);
    if (event.target.closest("[data-close-modal]")) closeModal();
  });

  $("#assetTypeSelect").addEventListener("change", (event) => {
    state.selectedType = event.target.value;
    renderCreatePage();
  });

  $("#l4ScenarioSelect").addEventListener("change", (event) => {
    state.selectedScenarioCode = event.target.value;
    syncL4ScenarioForm(true);
  });

  $("#l4RequestForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    await submitL4Request(event.currentTarget);
    button.disabled = false;
  });

  $("#runtimeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    await submitRuntime(event.currentTarget);
    button.disabled = false;
  });

  $("#closeL4Result").addEventListener("click", () => {
    state.l4Result = null;
    renderL4Result();
  });

  $("#assetForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const selectedValues = (selector) => Array.from($(selector).selectedOptions).map((option) => option.value).filter(Boolean);
    const entrySkillId = values.entrySkillId || "";
    const selectedSkills = [...new Set([entrySkillId, ...selectedValues("#agentSkillSelect")].filter(Boolean))];
    const config = { human_review_rule: values.humanReviewRule || null };
    if (values.type === "skill") {
      config.requirement = {
        input_definition: values.inputDefinition || "",
        output_definition: values.outputDefinition || "",
        acceptance_criteria: values.acceptanceCriteria || "",
      };
      config.candidate_source = values.candidateSource || "undecided";
      if (values.skillCreationMode === "bind_existing") {
        const separator = String(values.toolBinding || "").lastIndexOf("@");
        config.tool_id = separator > 0 ? values.toolBinding.slice(0, separator) : "";
        config.tool_version = separator > 0 ? values.toolBinding.slice(separator + 1) : "";
      }
    }
    if (values.type === "agent") {
      config.skill_ids = selectedSkills;
      config.entry_skill_id = entrySkillId;
      config.knowledge_base_ids = selectedValues("#agentKnowledgeBaseSelect");
      config.responsibility = values.description;
    }
    const payload = {
      asset_name: values.name,
      asset_type: values.type,
      scope: values.scope,
      description: values.description,
      owner_department: values.department,
      tags: String(values.tags || "").split(/[，,]/).map((value) => value.trim()).filter(Boolean)
        .map((value) => ({ key: "label", value })),
      config,
    };
    if (values.type === "skill" && values.skillCreationMode === "bind_existing") {
      payload.model_evaluations = [
        {
          model_role: "primary", model_id: values.primaryModelId,
          model_version: values.primaryModelVersion, dataset_ref: values.modelDatasetRef,
          metric_name: values.modelMetricName, metric_value: values.primaryMetricValue,
          conclusion: "passed",
        },
        {
          model_role: "backup", model_id: values.backupModelId,
          model_version: values.backupModelVersion, dataset_ref: values.modelDatasetRef,
          metric_name: values.modelMetricName, metric_value: values.backupMetricValue,
          conclusion: "passed",
        },
      ];
    }
    const creationMessage = values.type === "skill" && values.skillCreationMode === "request_development"
      ? "Skill 研发需求草稿已登记；当前不可执行"
      : "草稿已创建并登记";
    const ok = await mutate("/api/flow/tasks", buildFlowEnvelope(
      "asset.create",
      "l2.digital_asset.asset.create",
      "CAP.DIGITAL_ASSET.ASSET_CREATE",
      payload,
    ), `${creationMessage}；已生成流程任务与标准回执`);
    if (ok) {
      event.currentTarget.reset();
      renderActorSelector();
      renderCreatePage();
    }
  });

  $("#skillCreationMode").addEventListener("change", syncSkillCreationMode);

  ["catalogSearch", "catalogTypeFilter", "catalogStatusFilter"].forEach((id) => {
    $("#" + id).addEventListener(id === "catalogSearch" ? "input" : "change", () => renderCatalog());
  });

  $("#clearCatalogFilters").addEventListener("click", () => {
    $("#catalogSearch").value = "";
    $("#catalogTypeFilter").value = "";
    $("#catalogStatusFilter").value = "";
    renderCatalog();
  });

  $("#openSourceForm").addEventListener("click", () => $("#sourceFormPanel").classList.remove("hidden"));
  $("#cancelSourceForm").addEventListener("click", () => $("#sourceFormPanel").classList.add("hidden"));
  $("#sourceForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!values.assetId) return toast("当前真人没有可登记知识源的知识库", true);
    const file = event.currentTarget.elements.file.files[0];
    if (!file) return toast("请选择知识源文件", true);
    if (file.size > 10 * 1024 * 1024) return toast("单个知识源不能超过 10 MB", true);
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const dataBase64 = await fileAsBase64(file);
      const ok = await mutate(`/api/console/assets/${encodeURIComponent(values.assetId)}/knowledge-source-files`, {
        file_name: file.name,
        content_type: file.type || "application/octet-stream",
        data_base64: dataBase64,
        description: values.description,
      }, "知识源原件已上传并登记待解析任务");
      if (ok) {
        event.currentTarget.reset();
        $("#sourceFormPanel").classList.add("hidden");
      }
    } catch (error) {
      toast(error.message || "知识源文件读取失败", true);
    } finally {
      button.disabled = false;
    }
  });

  $("#resetDemo").addEventListener("click", () => openConfirm("重置演示数据", "这会清空当前演示操作并恢复服务端种子数据。", () => mutate("/api/reset", {}, "演示数据已重置"), "确认重置", true));
  window.addEventListener("hashchange", () => routeTo(location.hash.slice(1) || "overview", false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModal(); });
}

function handleWorkflowAction(action, id) {
  const flow = state.data.workflows.find((item) => item.workflow_id === id);
  if (!flow) return toast("流程已不在当前服务端可见集中", true);
  const approve = action === "approve";
  const copy = approve
    ? (flow.kind === "adoption" ? "批准采纳会将原个人资产归档，并生成带来源关系的部门草稿；不会直接完成部门发布。" : "批准后资产进入相应公共范围；资源可调用与底层数据权限仍分开判定。")
    : "驳回必须填写原因，流程、原资产和历史版本继续保留。";
  openModal(approve ? "批准流程" : "驳回流程", `
    <p class="modal-copy">${escapeHtml(copy)}</p>
    <label><span>审批意见</span><textarea id="workflowReason" rows="3" placeholder="填写审批依据或驳回原因"></textarea></label>
    <div class="modal-actions"><button type="button" class="ghost" data-close-modal>取消</button><button type="button" id="workflowConfirm" class="${approve ? "primary" : "danger-outline"}">${approve ? "批准" : "驳回"}</button></div>
  `);
  $("#workflowConfirm").addEventListener("click", async () => {
    const reason = $("#workflowReason").value.trim();
    if (!approve && !reason) return toast("驳回必须填写原因", true);
    await mutate(`/api/workflows/${encodeURIComponent(id)}/${action}`, { reason: reason || "符合固定模板与治理规范" }, approve ? "流程已批准" : "流程已驳回");
  });
}

function handleSourceAction(action, id) {
  const source = state.data.sources.find((item) => (item.source_id ?? item.id) === id);
  if (!source) return toast("知识源记录已不可见", true);
  if (action === "parse") {
    return openConfirm("触发文档解析", "数字资产引擎只发出处理请求并登记结果；具体解析由文档表格解析引擎承担。", () => mutate(`/api/sources/${encodeURIComponent(id)}/parse`, { reason: "经流程编排触发解析" }, "解析任务已提交"), "提交解析任务");
  }
  if (action === "register-index") return openSourceIndexCallbackModal(id);
  if (action === "download") {
    const link = document.createElement("a");
    link.href = `/api/knowledge-sources/${encodeURIComponent(id)}/download?actor=${encodeURIComponent(state.actorId)}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    return;
  }
  if (action === "detail") {
    openModal("知识源技术元数据", `
      ${source.metadataOnly ? `<div class="masked-notice">当前真人只能查看技术元数据，不能读取原件或解析内容。</div>` : ""}
      <div class="detail-meta">
        ${meta("记录编号", source.source_id ?? source.id)}
        ${meta("所属知识库", source.asset_id)}
        ${meta("文件名", source.file_name)}
        ${meta("文件类型", source.source_type)}
        ${meta("文件大小", formatBytes(source.size_bytes))}
        ${meta("SHA-256", source.checksum_sha256 || "外部对象未返回")}
        ${meta("解析服务", source.parser_service)}
        ${meta("解析状态", statusLabel(source.parse_status))}
        ${meta("L1索引状态", statusLabel(source.vector_status))}
        ${meta("索引证据", source.index_evidence ? `${source.index_evidence.chunk_count} 切片 / ${source.index_evidence.vector_count} 向量 / ${source.index_evidence.index_version}` : "无")}
      </div>
    `);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  const actorFromUrl = new URLSearchParams(location.search).get("actor") || "tester_a";
  loadState(actorFromUrl);
});
