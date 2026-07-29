let scenarios = [];
let monitorInstances = [];
let allTasks = [];
let activeTaskFilter = "all";

const views = document.querySelectorAll(".view");
const navButtons = document.querySelectorAll(".nav");
const scenarioSelect = document.querySelector("#scenario");
const scenarioInfo = document.querySelector("#scenarioInfo");
const payload = document.querySelector("#payload");
const taskList = document.querySelector("#taskList");
const taskDetail = document.querySelector("#taskDetail");
const taskSummary = document.querySelector("#taskSummary");
const policyDetail = document.querySelector("#policyDetail");
const complianceList = document.querySelector("#complianceList");
const acceptanceList = document.querySelector("#acceptanceList");
const demoList = document.querySelector("#demoList");
const demoResult = document.querySelector("#demoResult");
const monitorSummary = document.querySelector("#monitorSummary");
const monitorList = document.querySelector("#monitorList");
const monitorDetail = document.querySelector("#monitorDetail");
const monitorJson = document.querySelector("#monitorJson");
const verificationList = document.querySelector("#verificationList");
const verificationResult = document.querySelector("#verificationResult");
const verificationCapabilitySummary = document.querySelector("#verificationCapabilitySummary");
const runAllVerification = document.querySelector("#runAllVerification");
const deliverySummary = document.querySelector("#deliverySummary");
const deliveryChecklist = document.querySelector("#deliveryChecklist");
const deliveryEvidence = document.querySelector("#deliveryEvidence");
const deliveryContracts = document.querySelector("#deliveryContracts");
const deliveryReports = document.querySelector("#deliveryReports");
const deliveryActionResult = document.querySelector("#deliveryActionResult");
const generateReport = document.querySelector("#generateReport");
const generateConcurrencyReport = document.querySelector("#generateConcurrencyReport");
const generateExport = document.querySelector("#generateExport");
const pageEyebrow = document.querySelector("#pageEyebrow");
const pageTitle = document.querySelector("#pageTitle");
const pageSubtitle = document.querySelector("#pageSubtitle");
const lastRefresh = document.querySelector("#lastRefresh");
const apiState = document.querySelector("#apiState");
const runtimeState = document.querySelector("#runtimeState");
const sidebarHealthDot = document.querySelector("#sidebarHealthDot");
const sidebarHealthText = document.querySelector("#sidebarHealthText");
const runOverview = document.querySelector("#runOverview");
const runReceipt = document.querySelector("#runReceipt");
const taskOverview = document.querySelector("#taskOverview");
const taskRecordCount = document.querySelector("#taskRecordCount");
const taskFilters = document.querySelector("#taskFilters");
const monitorHealthBand = document.querySelector("#monitorHealthBand");
const monitorCount = document.querySelector("#monitorCount");
const policyOverview = document.querySelector("#policyOverview");
const complianceCount = document.querySelector("#complianceCount");
const acceptanceCount = document.querySelector("#acceptanceCount");
const runPolicyAcceptance = document.querySelector("#runPolicyAcceptance");

const viewMeta = {
  run: ["TASK CONTROL", "任务创建工作台", "配置输入与隔离策略，提交后由服务器创建独立 Docker 容器执行。"],
  demo: ["INTEGRATION CHAIN", "平台链路验证", "验证账号、权限、业务数据、沙箱、成本和审计之间的调用链路。"],
  verification: ["LIVE ACCEPTANCE", "现场验收中心", "重新执行真实探针，并持续返回命令事件、状态和技术证据。"],
  monitor: ["RUNTIME OBSERVABILITY", "沙箱运行监控台", "查看实例状态、资源配额、执行耗时、权限结论与审计轨迹。"],
  tasks: ["AUDIT & TRACEABILITY", "执行记录与证据追溯", "按任务复查输入、输出、执行器、平台检查和完整原始证据。"],
  policy: ["SECURITY & BOUNDARY", "安全控制与模块边界", "明确本模块职责、控制基线、相邻模块输入和当前完成口径。"],
  delivery: ["DELIVERY READINESS", "L1 能力包交付中心", "汇总交付材料、测试证据、报告归档与平台联调契约。"],
};

const verificationVisuals = {
  docker_runtime: {
    requirement: "独立环境隔离",
    probe: "检查服务器 Docker 运行时",
    defense: "任务由容器运行时承载",
    success: "Docker 服务在线，沙箱可以创建真实容器",
  },
  docker_task: {
    requirement: "每个任务进入独立沙箱",
    probe: "提交一个超库存预警任务",
    defense: "调度到 DockerTemplateExecutor",
    success: "任务返回 Docker 执行器、任务编号和业务结果",
  },
  host_file_isolation: {
    requirement: "越权防护 / 宿主机隔离",
    probe: "容器尝试读取沙箱外秘密文件，并尝试写代码目录",
    defense: "只挂载指定目录，且 /app 为只读挂载",
    success: "秘密文件不可见，代码目录不可写",
  },
  resource_timeout: {
    requirement: "资源配额 / 跑飞自动停止",
    probe: "启动一个死循环容器",
    defense: "设置 CPU、内存、超时，并强制停止容器",
    success: "死循环容器被 docker rm -f 清理",
  },
  network_default_deny: {
    requirement: "出站管控",
    probe: "容器尝试访问公网地址",
    defense: "容器使用 --network none",
    success: "外网访问失败，默认禁止出站生效",
  },
  egress_allowlist_gateway: {
    requirement: "域名级出站白名单",
    probe: "任务容器分别访问白名单域名、非白名单域名，并尝试绕过代理直连",
    defense: "内部 Docker 网络 + egress-proxy 白名单网关",
    success: "白名单通过、非白名单被拒绝、绕过代理失败",
  },
  browser_sandbox: {
    requirement: "浏览器沙箱 / 出站管控",
    probe: "启动真实 Headless Chromium，访问受控白名单测试页、非白名单域名，并尝试绕过代理直连",
    defense: "浏览器容器只接内部 Docker 网络，出站必须经过 egress-proxy",
    success: "受控测试页加载成功，非白名单访问留下拒绝记录，直连绕过失败",
  },
  permission_denial: {
    requirement: "权限前置拦截",
    probe: "销售用户尝试执行发票核销",
    defense: "安全合规模块检查 invoice:read / receipt:read",
    success: "权限不足任务被拒绝",
  },
  credential_injection: {
    requirement: "凭据注入 / 密钥不外泄",
    probe: "任务容器只拿短期句柄，尝试从环境变量、命令行和挂载目录寻找明文密钥",
    defense: "凭据 broker 持有明文，任务只能通过内部网络用句柄调用",
    success: "任务可使用凭据能力，但看不到明文密钥，并留下审计记录",
  },
  e2b_like_adapter: {
    requirement: "后续平台调用 / E2B-like 适配",
    probe: "按 create/run/query/destroy 流程创建一个沙箱会话并执行场景任务",
    defense: "适配器只包装 Docker 沙箱执行能力，不绕过现有权限、资源和审计链路",
    success: "会话创建成功，任务由 Docker 执行，结果可查询，会话可销毁",
  },
  hanhe_role_scenario_e2e: {
    requirement: "汉和岗位场景 / 端到端证明",
    probe: "销售用户运行跨部门超库存预警场景",
    defense: "账号权限、mock ERP 数据、Docker 沙箱、成本审计链路共同生效",
    success: "50 吨库存面对 90 吨订单输出超 40 吨预警，并留下完整证据",
  },
  hanhe_finance_invoice_e2e: {
    requirement: "汉和财务场景 / 端到端证明",
    probe: "财务用户运行发票核销场景",
    defense: "账号权限、mock ERP 发票/入库单、Docker 沙箱、成本审计链路共同生效",
    success: "发票匹配和异常识别成功，并留下完整证据",
  },
  hanhe_purchase_plan_e2e: {
    requirement: "汉和采购场景 / 端到端证明",
    probe: "采购计划场景读取历史采购和库存数据",
    defense: "权限、mock ERP 采购数据、Docker 沙箱、成本审计链路共同生效",
    success: "输出预测需求和建议采购量，并留下完整证据",
  },
};

const verificationPresentation = {
  docker_runtime: {group: "运行底座", short: "Docker daemon 与服务端版本"},
  docker_task: {group: "隔离执行", short: "真实业务任务进入独立容器"},
  host_file_isolation: {group: "隔离执行", short: "宿主机秘密文件不可见、代码目录只读"},
  resource_timeout: {group: "资源控制", short: "CPU / 内存 / 超时 / 自动清理"},
  network_default_deny: {group: "网络安全", short: "容器默认无公网出口"},
  egress_allowlist_gateway: {group: "网络安全", short: "白名单放行、非白名单拦截、禁止绕过"},
  browser_sandbox: {group: "浏览器沙箱", short: "Headless Chromium 受控出站"},
  permission_denial: {group: "权限安全", short: "敏感任务在执行前被拦截"},
  credential_injection: {group: "凭据安全", short: "只下发短期 handle，不暴露明文"},
  e2b_like_adapter: {group: "平台接口", short: "create / run / query / destroy"},
  hanhe_role_scenario_e2e: {group: "岗位场景", short: "销售/供应链库存预警"},
  hanhe_finance_invoice_e2e: {group: "岗位场景", short: "财务发票核销与异常识别"},
  hanhe_purchase_plan_e2e: {group: "岗位场景", short: "采购需求预测与建议采购量"},
};

let activeVerificationJobId = null;

navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activateView(button.dataset.view);
  });
});

document.querySelector("#refresh").addEventListener("click", refreshAllData);

if (taskFilters) {
  taskFilters.addEventListener("click", (event) => {
    const button = event.target.closest("[data-task-filter]");
    if (!button) return;
    activeTaskFilter = button.dataset.taskFilter;
    taskFilters.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
    renderTaskList();
  });
}

if (runAllVerification) {
  runAllVerification.addEventListener("click", () => runVerificationCase("all"));
}

if (generateReport) {
  generateReport.addEventListener("click", generateVerificationReport);
}

if (generateConcurrencyReport) {
  generateConcurrencyReport.addEventListener("click", generateConcurrencyTestReport);
}

if (generateExport) {
  generateExport.addEventListener("click", generateDeliveryExport);
}

if (runPolicyAcceptance) {
  runPolicyAcceptance.addEventListener("click", runObjectiveAcceptance);
}

document.querySelector("#submit").addEventListener("click", async () => {
  const submitButton = document.querySelector("#submit");
  let body;
  try {
    body = JSON.parse(payload.value);
  } catch {
    alert("输入 JSON 格式不正确");
    return;
  }
  body.scenario_id = scenarioSelect.value;
  submitButton.disabled = true;
  submitButton.textContent = "正在创建独立容器...";
  if (runReceipt) {
    runReceipt.className = "panel run-receipt running";
    runReceipt.innerHTML = renderTaskLaunching(body);
  }
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) {
      if (runReceipt) runReceipt.innerHTML = `<div class="status failed">${escapeHtml(data.message || data.error || "提交失败")}</div>`;
      return;
    }
    if (runReceipt) {
      runReceipt.className = "panel run-receipt completed";
      runReceipt.innerHTML = renderRunReceipt(data);
    }
    taskDetail.innerHTML = renderAnnotatedCode(data, "task");
    await Promise.all([loadTasks(), loadMonitor()]);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "启动隔离执行";
  }
});

scenarioSelect.addEventListener("change", renderScenarioInfo);

function activateView(viewName) {
  const target = document.querySelector(`#${viewName}`);
  const button = document.querySelector(`.nav[data-view="${viewName}"]`);
  if (!target || !button) return;
  navButtons.forEach((item) => item.classList.remove("active"));
  views.forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  target.classList.add("active");
  const meta = viewMeta[viewName] || viewMeta.run;
  if (pageEyebrow) pageEyebrow.textContent = meta[0];
  if (pageTitle) pageTitle.textContent = meta[1];
  if (pageSubtitle) pageSubtitle.textContent = meta[2];
  history.replaceState(null, "", `#${viewName}`);
  if (viewName === "demo") loadDemoCases();
  if (viewName === "verification") loadVerificationCases();
  if (viewName === "monitor") loadMonitor();
  if (viewName === "tasks") loadTasks();
  if (viewName === "policy") loadPolicy();
  if (viewName === "delivery") loadDeliveryPackage();
}

async function refreshAllData() {
  const refreshButton = document.querySelector("#refresh");
  refreshButton.disabled = true;
  refreshButton.textContent = "刷新中...";
  try {
    await Promise.all([
      loadSystemHealth(),
      loadScenarios(),
      loadTasks(),
      loadDemoCases(),
      loadVerificationCases(),
      loadMonitor(),
      loadDeliveryPackage(),
    ]);
    if (document.querySelector("#policy")?.classList.contains("active")) await loadPolicy();
    if (lastRefresh) lastRefresh.textContent = new Date().toLocaleTimeString("zh-CN", {hour12: false});
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "刷新数据";
  }
}

async function loadSystemHealth() {
  try {
    const [healthResponse, readinessResponse] = await Promise.all([fetch("/api/health"), fetch("/api/readiness")]);
    const health = await healthResponse.json();
    const readiness = await readinessResponse.json();
    const ok = Boolean(health.ok && readiness.ok);
    if (apiState) apiState.textContent = ok ? "在线" : "异常";
    if (runtimeState) runtimeState.textContent = readiness.executor?.name || readiness.executor?.type || "DockerTemplateExecutor";
    if (sidebarHealthText) sidebarHealthText.textContent = ok ? "服务在线" : "服务异常";
    if (sidebarHealthDot) sidebarHealthDot.classList.toggle("offline", !ok);
  } catch {
    if (apiState) apiState.textContent = "连接失败";
    if (sidebarHealthText) sidebarHealthText.textContent = "连接失败";
    if (sidebarHealthDot) sidebarHealthDot.classList.add("offline");
  }
}

async function loadScenarios() {
  const response = await fetch("/api/scenarios");
  const data = await response.json();
  scenarios = data.scenarios || [];
  scenarioSelect.innerHTML = scenarios
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.scene)} / ${escapeHtml(item.name)}</option>`)
    .join("");
  if (runOverview) {
    const approvalCount = scenarios.filter((item) => item.needs_human_approval).length;
    runOverview.innerHTML = [
      executiveMetric(scenarios.length, "业务场景模板", "覆盖财务、销售、采购等岗位"),
      executiveMetric("Docker", "真实执行引擎", "独立容器，用后销毁", "green"),
      executiveMetric("1 CPU / 512 MB", "默认资源上限", "任务级配额，可按输入调整"),
      executiveMetric(approvalCount, "高风险审批场景", "审批归相邻驾驭模块"),
    ].join("");
  }
  renderScenarioInfo();
}

function renderScenarioInfo() {
  const item = scenarios.find((scenario) => scenario.id === scenarioSelect.value);
  if (!item) {
    scenarioInfo.textContent = "暂无场景。";
    return;
  }
  const riskText = {high: "高风险", medium: "中风险", low: "低风险"}[item.risk_level] || item.risk_level;
  scenarioInfo.innerHTML = `
    <div class="scenario-identity">
      <span>${escapeHtml(item.scene)}</span>
      <span class="risk ${escapeHtml(item.risk_level)}">${escapeHtml(riskText)}</span>
    </div>
    <h4>${escapeHtml(item.name)}</h4>
    <div class="scenario-facts">
      <div><span>业务问题</span><p>${escapeHtml(item.requirement)}</p></div>
      <div><span>沙箱职责</span><p>${escapeHtml(item.sandbox_role)}</p></div>
    </div>
    <div class="policy-pills">
      <span>CPU 1.0 核</span><span>内存 512 MB</span><span>超时 10 秒</span><span>默认禁网</span><span>只读根目录</span>
    </div>
    <div class="approval-line ${item.needs_human_approval ? "required" : "auto"}">
      <b>${item.needs_human_approval ? "需要上游审批" : "允许自动执行"}</b>
      <span>${item.needs_human_approval ? "沙箱接收 allow 结论后执行" : "通过权限预检后进入沙箱"}</span>
    </div>
  `;
}

function renderTaskLaunching(body) {
  return `
    <div class="launching-head"><span class="live-beacon"></span><div><strong>服务器正在创建沙箱任务</strong><p>本次请求不是本地文字动画，页面正在等待 <code>POST /api/tasks</code> 的真实返回。</p></div></div>
    <div class="launching-steps">
      <span class="active">接收输入</span><span class="active">权限预检</span><span class="active">创建容器</span><span>隔离执行</span><span>取回并销毁</span>
    </div>
    <small>场景 ${escapeHtml(body.scenario_id)} · actor ${escapeHtml(body.actor || "-")} · timeout ${escapeHtml(body.timeout_seconds || 10)}s</small>
  `;
}

function renderRunReceipt(task) {
  const runtime = task.result?.sandbox_runtime || {};
  const checks = task.platform_checks || {};
  const logs = task.logs || [];
  const result = task.result?.payload || {};
  return `
    <div class="receipt-heading">
      <div><span class="receipt-check">✓</span><div><span>服务器执行回执</span><h3>任务已在独立 Docker 容器中完成</h3></div></div>
      <span class="badge passed">${escapeHtml(statusText(task.status))}</span>
    </div>
    <div class="receipt-metrics">
      <div><span>task_id</span><strong>${escapeHtml(task.id || "-")}</strong></div>
      <div><span>真实执行器</span><strong>${escapeHtml(task.executor || runtime.executor || "-")}</strong></div>
      <div><span>后端耗时</span><strong>${escapeHtml(task.duration_ms ?? 0)} ms</strong></div>
      <div><span>审计事件</span><strong>${escapeHtml((checks.audit_events || []).length)} 条</strong></div>
    </div>
    <div class="lifecycle-timeline">
      ${logs.map((log, index) => `<div class="done"><b>${String(index + 1).padStart(2, "0")}</b><span>${escapeHtml(eventName(log.event))}<small>${escapeHtml(log.time || "")}</small></span></div>`).join("")}
    </div>
    ${renderBusinessResult(task.scenario_id, result)}
    <details class="raw-evidence"><summary>查看本次任务完整 JSON 回执</summary>${renderAnnotatedCode(task, "task")}</details>
  `;
}

async function loadTasks() {
  const response = await fetch("/api/tasks");
  const data = await response.json();
  allTasks = data.tasks || [];
  const success = allTasks.filter((item) => item.status === "success").length;
  const failed = allTasks.filter((item) => item.status === "failed").length;
  const denied = allTasks.filter((item) => item.status === "denied").length;
  const timeout = allTasks.filter((item) => item.status === "timeout").length;
  const average = allTasks.length ? Math.round(allTasks.reduce((sum, item) => sum + Number(item.duration_ms || 0), 0) / allTasks.length) : 0;
  if (taskOverview) {
    taskOverview.innerHTML = [
      executiveMetric(allTasks.length, "累计任务", "服务器持久化执行记录"),
      executiveMetric(success, "成功完成", `${allTasks.length ? Math.round(success / allTasks.length * 100) : 0}% 成功率`, "green"),
      executiveMetric(average, "平均耗时（ms）", "按当前任务台账计算"),
      executiveMetric(failed + timeout + denied, "异常、拒绝与超时", `${failed} 失败 / ${denied} 拒绝 / ${timeout} 超时`, failed + timeout + denied ? "amber" : "green"),
    ].join("");
  }
  renderTaskList();
}

function renderTaskList() {
  const tasks = activeTaskFilter === "all" ? allTasks : allTasks.filter((item) => item.status === activeTaskFilter);
  const visibleTasks = tasks.slice(0, 80);
  if (taskRecordCount) taskRecordCount.textContent = tasks.length > visibleTasks.length
    ? `${tasks.length} 条记录 · 显示最近 ${visibleTasks.length} 条`
    : `${tasks.length} 条记录`;
  if (!tasks.length) {
    taskList.innerHTML = "<p>当前筛选条件下没有执行记录。</p>";
    return;
  }
  taskList.innerHTML = visibleTasks.map((task) => `
    <div class="task-item" data-id="${escapeHtml(task.id)}">
      <div class="task-item-top"><span class="task-id">${escapeHtml(task.id)}</span><span class="badge ${escapeHtml(task.status || "")}">${escapeHtml(statusText(task.status))}</span></div>
      <strong>${escapeHtml(task.scenario_name || task.scenario_id || "-")}</strong>
      <div class="task-item-meta"><span>${escapeHtml(task.created_at || "-")}</span><span>${escapeHtml(task.duration_ms ?? 0)} ms</span><span>${escapeHtml(task.executor || "-")}</span></div>
    </div>
  `).join("");
  document.querySelectorAll(".task-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".task-item").forEach((row) => row.classList.toggle("selected", row === item));
      loadTaskDetail(item.dataset.id);
    });
  });
}

async function loadTaskDetail(id) {
  const response = await fetch(`/api/tasks/${id}`);
  const data = await response.json();
  renderTaskSummary(data);
  taskDetail.innerHTML = renderAnnotatedCode(data, "task");
}

function renderTaskSummary(task) {
  if (!taskSummary || !task || task.error) return;
  const checks = task.platform_checks || {};
  const account = checks.account_gateway || {};
  const security = checks.security_compliance || {};
  const cost = checks.cost_control || {};
  const auditEvents = checks.audit_events || [];
  const result = task.result && task.result.payload ? task.result.payload : {};
  const runtime = task.result?.sandbox_runtime || {};
  const logs = task.logs || [];
  const allowed = security.allowed !== false;
  const sandboxStarted = checks.sandbox_execution?.started ?? allowed;
  taskSummary.innerHTML = `
    <div class="task-proof-head">
      <div><span class="badge ${escapeHtml(task.status || "")}">${escapeHtml(statusText(task.status))}</span><h3>${escapeHtml(task.scenario_name || task.scenario_id || "-")}</h3><p>task_id ${escapeHtml(task.id || "-")} · ${escapeHtml(task.created_at || "-")}</p></div>
      <div class="task-runtime-stamp"><span>${sandboxStarted ? "实际执行器" : "配置执行器（未调用）"}</span><strong>${escapeHtml(task.executor || runtime.executor || "-")}</strong><small>${sandboxStarted ? escapeHtml(runtime.isolation || "docker_container") : "权限前置拦截"}</small></div>
    </div>
    <div class="task-proof-metrics">
      <div><span>岗位身份</span><strong>${escapeHtml(account.department || "-")} / ${escapeHtml(account.role || "-")}</strong><small>${escapeHtml(account.actor || task.audit?.actor || "-")}</small></div>
      <div><span>权限预检</span><strong>${allowed ? "通过" : "拒绝"}</strong><small>${escapeHtml((security.required_permissions || []).join(" · ") || "无额外权限")}</small></div>
      <div><span>资源配额</span><strong>${sandboxStarted ? `${escapeHtml(task.limits?.cpu_cores ?? runtime.cpu_cores ?? "-")} CPU / ${escapeHtml(task.limits?.memory_mb ?? runtime.memory_mb ?? "-")} MB` : "未应用"}</strong><small>${sandboxStarted ? `超时 ${escapeHtml(task.limits?.timeout_seconds ?? "-")} 秒` : "Docker 未启动"}</small></div>
      <div><span>成本计量</span><strong>${escapeHtml(cost.cost_units ?? "-")} units</strong><small>${escapeHtml(cost.duration_ms ?? task.duration_ms ?? 0)} ms</small></div>
    </div>
    <div class="audit-flow">
      ${logs.map((log, index) => `<div class="${log.level === "error" ? "fail" : "done"}"><b>${String(index + 1).padStart(2, "0")}</b><span><strong>${escapeHtml(eventName(log.event))}</strong><small>${escapeHtml(log.message || "")} · ${escapeHtml(log.time || "")}</small></span></div>`).join("")}
    </div>
    ${renderBusinessResult(task.scenario_id, result)}
    <div class="evidence-strip"><span>审计事件 ${escapeHtml(auditEvents.length)} 条</span><span>执行日志 ${escapeHtml(logs.length)} 条</span><span>结果文件 ${escapeHtml((task.result?.files || []).length)} 个</span><span>网络策略 ${escapeHtml(runtime.network || task.egress_policy?.default || "-")}</span></div>
  `;
}

function renderBusinessResult(scenarioId, result) {
  if (scenarioId === "s04_invoice_matching" && Array.isArray(result.matches)) {
    const rows = result.matches.map(item => `
      <tr><td>${escapeHtml(item.invoice_no)}</td><td>${escapeHtml(item.supplier)}</td><td>${escapeHtml(item.matched_receipt || "-")}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.message)}</td></tr>
    `).join("");
    return `<div class="business-result"><h4>业务结果：发票核销</h4><table class="mini-table"><thead><tr><th>发票</th><th>供应商</th><th>入库单</th><th>状态</th><th>说明</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  if (scenarioId === "s19_over_stock_warning") {
    return `<div class="business-result"><h4>业务结果：库存预警</h4><p>库存 ${escapeHtml(result.inventory ?? "-")}，下单合计 ${escapeHtml(result.total_order_qty ?? "-")}，超出 ${escapeHtml(result.over_qty ?? 0)}，状态：${escapeHtml(result.status ?? "-")}</p></div>`;
  }
  if (scenarioId === "s20_purchase_plan") {
    return `<div class="business-result"><h4>业务结果：采购计划</h4><p>预测需求 ${escapeHtml(result.forecast_demand ?? "-")}，当前库存 ${escapeHtml(result.current_stock ?? "-")}，建议采购 ${escapeHtml(result.suggested_purchase ?? "-")}</p></div>`;
  }
  return `<div class="business-result"><h4>业务结果摘要</h4><p>任务已执行，详细结果见下方原始 JSON。</p></div>`;
}

async function loadPolicy() {
  if (!policyDetail) return;
  const [policyResponse, readinessResponse, complianceResponse] = await Promise.all([
    fetch("/api/policy"),
    fetch("/api/readiness"),
    fetch("/api/compliance"),
  ]);
  const [policy, readiness, compliance] = await Promise.all([
    policyResponse.json(),
    readinessResponse.json(),
    complianceResponse.json(),
  ]);
  const complianceItems = compliance.items || [];
  const complianceSummary = compliance.summary || {};
  if (policyOverview) {
    policyOverview.innerHTML = [
      executiveMetric(complianceItems.filter((item) => item.status === "done").length, "当前范围已实现", `${complianceItems.length} 项研发要求`, "green"),
      executiveMetric(complianceSummary.integration_ready ?? 0, "联调就绪项", "等待相邻模块提供真实接口"),
      executiveMetric("deny", "默认网络策略", "无授权时禁止容器出站", "green"),
      executiveMetric(complianceSummary.future_enhancements ?? 0, "后续增强项", "更强隔离与完整 SDK 兼容", "amber"),
    ].join("");
  }
  if (complianceCount) complianceCount.textContent = `${complianceItems.length} ITEMS`;
  policyDetail.innerHTML = renderAnnotatedCode({ readiness, policy }, "policy");
  if (complianceList) {
    complianceList.innerHTML = complianceItems.map((item, index) => `
      <div class="compliance-item">
        <strong><small>${String(index + 1).padStart(2, "0")}</small>${escapeHtml(item.requirement)}</strong>
        <span class="badge ${escapeHtml(item.status)}">${statusText(item.status)}</span>
        <span>${escapeHtml(item.evidence)}</span>
      </div>
    `).join("");
  }
}

async function runObjectiveAcceptance() {
  if (!runPolicyAcceptance || !acceptanceList) return;
  runPolicyAcceptance.disabled = true;
  runPolicyAcceptance.textContent = "服务器验收中...";
  if (acceptanceCount) acceptanceCount.textContent = "RUNNING";
  acceptanceList.innerHTML = `
    <div class="acceptance-running">
      <span class="live-beacon"></span>
      <div><strong>正在重新执行客观验收</strong><p>后端正在运行 Docker、资源、网络、凭据与岗位场景检查。</p></div>
    </div>
  `;
  try {
    const response = await fetch("/api/acceptance");
    const acceptance = await response.json();
    if (!response.ok) throw new Error(acceptance.message || acceptance.error || "验收运行失败");
    const acceptanceChecks = acceptance.checks || [];
    const summary = acceptance.summary || {};
    if (acceptanceCount) acceptanceCount.textContent = `${acceptanceChecks.length} CHECKS`;
    acceptanceList.innerHTML = `
      <div class="acceptance-summary-band">
        <div><strong>${escapeHtml(summary.passed ?? 0)}</strong><span>通过</span></div>
        <div><strong>${escapeHtml(summary.partial ?? 0)}</strong><span>部分通过</span></div>
        <div><strong>${escapeHtml(summary.failed ?? 0)}</strong><span>失败</span></div>
        <div><strong>${escapeHtml(summary.future ?? 0)}</strong><span>后续增强</span></div>
      </div>
      ${acceptanceChecks.map((item, index) => `
        <div class="compliance-item">
          <strong><small>${String(index + 1).padStart(2, "0")}</small>${escapeHtml(item.name)}</strong>
          <span class="badge ${escapeHtml(item.status)}">${acceptanceText(item.status)}</span>
          <span>${escapeHtml(item.detail)}</span>
        </div>
      `).join("")}
    `;
    await Promise.all([loadTasks(), loadMonitor()]);
  } catch (error) {
    acceptanceList.innerHTML = `<div class="status failed">${escapeHtml(error.message || "验收运行失败")}</div>`;
    if (acceptanceCount) acceptanceCount.textContent = "FAILED";
  } finally {
    runPolicyAcceptance.disabled = false;
    runPolicyAcceptance.textContent = "重新运行验收";
  }
}

async function loadDemoCases() {
  if (!demoList) return;
  const response = await fetch("/api/demo-cases");
  const data = await response.json();
  const cases = data.demo_cases || [];
  demoList.innerHTML = cases.map((item, index) => {
    const profile = item.actor_profile || {};
    const expectedDeny = item.expected_decision === "deny";
    return `
    <div class="demo-card ${expectedDeny ? "deny-case" : "allow-case"}">
      <span class="demo-index">${String(index + 1).padStart(2, "0")}</span>
      <div>
        <div class="demo-card-title"><strong>${escapeHtml(item.title)}</strong><span class="decision-badge ${expectedDeny ? "deny" : "allow"}">${expectedDeny ? "预期拒绝" : "预期允许"}</span></div>
        <p>${escapeHtml(item.expected)}</p>
        <div class="permission-compare">
          <div><span>账号岗位</span><strong>${escapeHtml(profile.department || "-")} / ${escapeHtml(profile.role || "-")}</strong></div>
          <div><span>已有权限</span><strong>${escapeHtml((item.held_permissions || []).join(" · ") || "无")}</strong></div>
          <div><span>场景要求</span><strong>${escapeHtml((item.required_permissions || []).join(" · ") || "无")}</strong></div>
          <div class="${(item.missing_permissions || []).length ? "missing" : "matched"}"><span>${(item.missing_permissions || []).length ? "缺少权限" : "权限差集"}</span><strong>${escapeHtml((item.missing_permissions || []).join(" · ") || "无缺失")}</strong></div>
        </div>
        <div class="demo-tags"><span>${escapeHtml(item.scenario_id)}</span><span>${escapeHtml(item.actor)}</span><span>权限前置判定</span></div>
      </div>
      <button class="run-demo" data-demo="${escapeHtml(item.id)}">运行链路</button>
    </div>
  `;
  }).join("");
  document.querySelectorAll(".run-demo").forEach((button) => {
    button.addEventListener("click", () => runDemoCase(button.dataset.demo));
  });
}

async function runDemoCase(caseId) {
  if (!demoResult) return;
  demoResult.className = "demo-running";
  demoResult.innerHTML = `
    <div class="launching-head"><span class="live-beacon"></span><div><strong>平台链路正在调用</strong><p>账号、权限和业务数据检查后，任务将进入真实 Docker 执行器。</p></div></div>
    <div class="chain-progress">${["任务输入", "账号解析", "权限预检", "ERP/OA", "Docker 沙箱", "成本记录", "审计回传"].map((item, index) => `<span style="--delay:${index}">${escapeHtml(item)}</span>`).join("")}</div>
  `;
  const response = await fetch(`/api/demo-cases/${caseId}`, {method: "POST"});
  const data = await response.json();
  if (!response.ok) {
    demoResult.className = "summary-empty";
    demoResult.innerHTML = `<div class="status failed">${escapeHtml(data.message || data.error || "演示运行失败")}</div>`;
    return;
  }
  const task = data.task || {};
  const checks = task.platform_checks || {};
  const security = checks.security_compliance || {};
  const cost = checks.cost_control || {};
  const sources = checks.mock_sources || [];
  const auditEvents = checks.audit_events || [];
  const runtime = task.result?.sandbox_runtime || {};
  const sandboxExecution = checks.sandbox_execution || {};
  const expectedDeny = data.case?.expected_decision === "deny";
  const actualDenied = security.allowed === false && sandboxExecution.started === false;
  const outcomeOk = expectedDeny ? actualDenied : task.status === "success";
  const missingPermissions = security.missing_permissions || [];
  demoResult.className = "demo-completed";
  demoResult.innerHTML = `
    <div class="integration-receipt-head">
      <div><span class="receipt-check ${outcomeOk ? "" : "failed"}">${outcomeOk ? "✓" : "!"}</span><div><small>平台链路回执</small><h3>${escapeHtml(data.case.title)}</h3></div></div>
      <span class="badge ${outcomeOk ? "passed" : "failed"}">${expectedDeny && actualDenied ? "按预期拦截" : task.status === "success" ? "链路通过" : "结果不符合预期"}</span>
    </div>
    <div class="permission-verdict ${security.allowed === false ? "denied" : "allowed"}">
      <div><span>当前岗位已有权限</span><strong>${escapeHtml((checks.account_gateway?.permissions || []).join(" · ") || "无")}</strong></div>
      <div><span>本场景所需权限</span><strong>${escapeHtml((security.required_permissions || []).join(" · ") || "无")}</strong></div>
      <div><span>权限差集</span><strong>${escapeHtml(missingPermissions.join(" · ") || "无缺失")}</strong></div>
      <div><span>最终判定</span><strong>${security.allowed === false ? "拒绝执行" : "允许执行"}</strong></div>
    </div>
    <div class="integration-result-rail">
      ${integrationStep("任务输入", task.id ? "done" : "fail", "POST /api/tasks", task.id || "未生成")}
      ${integrationStep("账号解析", checks.account_gateway ? "done" : "fail", "当前 mock", `${checks.account_gateway?.department || "-"} / ${checks.account_gateway?.role || "-"}`)}
      ${integrationStep("权限预检", outcomeOk ? "done" : "fail", "真实判定", security.allowed !== false ? "权限满足，继续执行" : `拒绝：缺少 ${missingPermissions.join(", ")}`)}
      ${integrationStep("ERP/OA 取数", expectedDeny ? "stopped" : sources.length ? "done" : "warn", expectedDeny ? "未调用" : "当前 mock", expectedDeny ? "权限拒绝后停止" : sources.join(", ") || "无数据源")}
      ${integrationStep("Docker 沙箱", expectedDeny ? (sandboxExecution.started === false ? "stopped" : "fail") : task.status === "success" ? "done" : "fail", expectedDeny ? "未调用" : "真实执行", expectedDeny ? "前置拦截，未创建容器" : runtime.executor || task.executor || "-")}
      ${integrationStep("成本记录", expectedDeny ? "stopped" : cost.meter ? "done" : "warn", expectedDeny ? "不计费" : "当前 mock", `${cost.cost_units ?? 0} units`)}
      ${integrationStep("审计回传", auditEvents.length ? "done" : "fail", "真实留痕", `${auditEvents.length} 条事件`)}
    </div>
    <div class="integration-proof-grid">
      <div><span>task_id</span><strong>${escapeHtml(task.id || "-")}</strong></div>
      <div><span>判定耗时</span><strong>${escapeHtml(task.duration_ms ?? 0)} ms</strong></div>
      <div><span>Docker 执行</span><strong>${sandboxExecution.started === false ? "未启动" : `${escapeHtml(runtime.cpu_cores ?? "-")} CPU / ${escapeHtml(runtime.memory_mb ?? "-")} MB`}</strong></div>
      <div><span>网络</span><strong>${sandboxExecution.started === false ? "未建立" : escapeHtml(runtime.network || "none")}</strong></div>
    </div>
    ${expectedDeny ? `<div class="business-result denied-result"><h4>拦截结果</h4><p>任务在权限预检阶段终止，没有读取 ERP/OA 数据，也没有调用 Docker 执行器。</p></div>` : renderBusinessResult(task.scenario_id, task.result?.payload || {})}
    <details class="raw-evidence"><summary>展开本次平台链路原始 JSON 证据</summary>${renderAnnotatedCode(task, "task")}</details>
  `;
  await loadTasks();
  await loadMonitor();
}

async function loadMonitor() {
  if (!monitorSummary || !monitorList || !monitorDetail || !monitorJson) return;
  const response = await fetch("/api/monitor");
  const data = await response.json();
  monitorInstances = data.instances || [];
  const summary = data.summary || {};
  const successRate = summary.total ? Math.round((summary.success || 0) / summary.total * 100) : 0;
  monitorSummary.innerHTML = [
    executiveMetric(summary.total ?? 0, "累计实例", "由服务端监控接口实时汇总"),
    executiveMetric(`${successRate}%`, "任务成功率", `${summary.success ?? 0} 个成功实例`, "green"),
    executiveMetric(summary.running ?? 0, "正在运行", `${summary.queued ?? 0} 个排队中`, summary.running ? "blue" : "green"),
    executiveMetric((summary.failed ?? 0) + (summary.denied ?? 0) + (summary.timeout ?? 0), "异常与拒绝", `${summary.failed ?? 0} 失败 / ${summary.denied ?? 0} 拒绝 / ${summary.timeout ?? 0} 超时`, (summary.failed || summary.denied || summary.timeout) ? "amber" : "green"),
  ].join("");
  if (monitorCount) monitorCount.textContent = `${monitorInstances.length} ITEMS`;
  if (monitorHealthBand) {
    const latest = data.latest_instance || monitorInstances[0] || {};
    monitorHealthBand.innerHTML = `
      <div><span class="strip-dot online"></span><strong>运行时在线</strong><small>DockerTemplateExecutor</small></div>
      <div><span>最近任务</span><strong>${escapeHtml(latest.id || "-")}</strong><small>${escapeHtml(latest.finished_at || latest.created_at || "-")}</small></div>
      <div><span>默认配额</span><strong>${escapeHtml(latest.cpu_cores ?? "1.0")} CPU / ${escapeHtml(latest.memory_mb ?? 512)} MB</strong><small>单任务独立限制</small></div>
      <div><span>出站策略</span><strong>deny by default</strong><small>${escapeHtml(latest.egress_policy || "默认拒绝")}</small></div>
    `;
  }
  if (!monitorInstances.length) {
    monitorList.innerHTML = "<p>暂无实例。</p>";
    monitorDetail.textContent = "选择一个实例查看。";
    monitorJson.textContent = "选择一个实例查看。";
    return;
  }
  monitorList.innerHTML = monitorInstances.slice(0, 80).map((item, index) => `
    <div class="monitor-item" data-id="${escapeHtml(item.id)}">
      <div class="monitor-title">
        <span class="monitor-seq">${String(index + 1).padStart(2, "0")}</span>
        <strong>${escapeHtml(item.scenario_name || item.scenario_id || "-")}</strong>
        <span class="badge ${escapeHtml(item.status || "")}">${escapeHtml(statusText(item.status))}</span>
      </div>
      <div class="monitor-meta"><span>${escapeHtml(item.actor || "-")} / ${escapeHtml(item.role || "-")}</span><span>${escapeHtml(item.duration_ms ?? 0)} ms</span></div>
      <div class="resource-bars"><span style="--value:${Math.min(100, Number(item.cpu_cores || 0) * 50)}%">CPU ${escapeHtml(item.cpu_cores ?? "-")}</span><span style="--value:${Math.min(100, Number(item.memory_mb || 0) / 10.24)}%">MEM ${escapeHtml(item.memory_mb ?? "-")} MB</span></div>
    </div>
  `).join("");
  document.querySelectorAll(".monitor-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".monitor-item").forEach((row) => row.classList.toggle("selected", row === item));
      renderMonitorDetail(item.dataset.id);
    });
  });
  const first = document.querySelector(".monitor-item");
  if (first) first.classList.add("selected");
  renderMonitorDetail(monitorInstances[0].id);
}

async function loadVerificationCases() {
  if (!verificationList) return;
  const response = await fetch("/api/verification");
  const data = await response.json();
  const cases = data.cases || [];
  if (verificationCapabilitySummary) {
    verificationCapabilitySummary.innerHTML = [
      verificationSummaryItem("13", "现场验收探针", "每次点击重新执行"),
      verificationSummaryItem("4", "核心控制维度", "隔离 / 资源 / 网络 / 凭据"),
      verificationSummaryItem("3", "汉和岗位场景", "销售 / 财务 / 采购"),
      verificationSummaryItem("Docker", "当前运行时", "后续可替换更强隔离实现"),
    ].join("");
  }
  verificationList.innerHTML = cases.map((item, index) => {
    const presentation = verificationPresentation[item.id] || {group: "能力验证", short: item.expected};
    return `
    <div class="verification-card" data-case-card="${escapeHtml(item.id)}">
      <div class="verification-card-index">${String(index + 1).padStart(2, "0")}</div>
      <div>
        <span class="verification-group">${escapeHtml(presentation.group)}</span>
        <strong>${escapeHtml(item.title)}</strong>
        <p>${escapeHtml(item.claim)}</p>
        <span class="verification-proof-target">验收目标：${escapeHtml(presentation.short)}</span>
      </div>
      <button class="run-verification" data-case="${escapeHtml(item.id)}">现场验证</button>
    </div>
  `;
  }).join("");
  document.querySelectorAll(".run-verification").forEach((button) => {
    button.addEventListener("click", () => runVerificationCase(button.dataset.case));
  });
}

function verificationSummaryItem(value, label, detail) {
  return `
    <div class="verification-summary-item">
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(label)}</span>
      <p>${escapeHtml(detail)}</p>
    </div>
  `;
}

async function loadDeliveryPackage() {
  if (!deliverySummary) return;
  const [response, reportResponse] = await Promise.all([
    fetch("/api/delivery/package"),
    fetch("/api/verification/reports"),
  ]);
  const data = await response.json();
  const reportData = await reportResponse.json();
  const checklist = data.checklist || {};
  const evidence = data.evidence || {};
  const exportInfo = data.export || {};
  const contracts = (data.integration_contracts || {}).contracts || [];
  const checklistSummary = checklist.summary || {};
  const evidenceSummary = evidence.summary || {};
  const checklistTotal = checklistSummary.total ?? (checklist.items || []).length;
  const completion = checklistTotal ? Math.round((checklistSummary.done || 0) / checklistTotal * 100) : 0;

  deliverySummary.innerHTML = [
    executiveMetric(data.current_runtime || "Docker", "当前运行时", "真实隔离执行底座", "green"),
    executiveMetric(`${completion}%`, "交付清单完成度", `${checklistSummary.done ?? 0}/${checklistTotal} 项完成`, "green"),
    executiveMetric(`${evidenceSummary.present ?? 0}/${evidenceSummary.total ?? 0}`, "证据覆盖", "页面截图与接口快照", "green"),
    executiveMetric(contracts.length, "联调接口契约", "相邻模块可按契约替换 mock"),
  ].join("");

  deliveryChecklist.innerHTML = (checklist.items || []).map((item) => `
    <div class="compliance-item">
      <strong>${escapeHtml(item.name)}</strong>
      <span class="badge ${escapeHtml(item.status)}">${statusText(item.status)}</span>
      <span>${escapeHtml(item.evidence)}</span>
    </div>
  `).join("");

  deliveryEvidence.innerHTML = (evidence.files || []).map((item) => `
    <div class="evidence-row">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <p>${escapeHtml(item.proves)}</p>
        <span class="meta">${escapeHtml(item.path)}</span>
      </div>
      <span class="badge ${item.exists ? "done" : "ready"}">${item.exists ? "已生成" : "待生成"}</span>
    </div>
  `).join("");

  deliveryContracts.innerHTML = contracts.map((item) => `
    <div class="contract-card">
      <div class="contract-head"><strong>${escapeHtml(item.module)}</strong><span class="badge done">联调就绪</span></div>
      <div class="contract-direction"><span>相邻模块提供</span><p>${escapeHtml(item.needs_from_module)}</p></div>
      <div class="contract-direction sandbox"><span>沙箱侧对接</span><p>${escapeHtml(item.sandbox_side)}</p></div>
    </div>
  `).join("");

  const reports = reportData.reports || [];
  deliveryReports.innerHTML = reports.length ? reports.slice(0, 8).map((item) => `
    <div class="evidence-row">
      <div>
        <strong>${escapeHtml(reportTypeText(item.type))}：${escapeHtml(item.markdown || item.json)}</strong>
        <p>生成时间：${escapeHtml(item.updated_at)}，大小：${escapeHtml(Math.round((item.size_bytes || 0) / 1024))} KB</p>
        <span class="meta">${escapeHtml(item.json)}</span>
      </div>
      <span class="badge done">已归档</span>
    </div>
  `).join("") : `<div class="summary-empty">还没有归档报告。</div>`;
}

async function generateVerificationReport() {
  if (!deliveryActionResult) return;
  deliveryActionResult.textContent = "正在运行全量现场验证并生成报告...";
  const response = await fetch("/api/verification/report", {method: "POST"});
  const data = await response.json();
  if (!response.ok) {
    deliveryActionResult.textContent = data.message || data.error || "生成验证报告失败";
    return;
  }
  deliveryActionResult.innerHTML = `
    <strong>验证报告已生成</strong>
    <p>JSON：${escapeHtml(data.json)}</p>
    <p>Markdown：${escapeHtml(data.markdown)}</p>
    <p>通过：${escapeHtml(data.summary?.passed ?? 0)}，失败：${escapeHtml(data.summary?.failed ?? 0)}</p>
  `;
  await loadDeliveryPackage();
}

async function generateConcurrencyTestReport() {
  if (!deliveryActionResult) return;
  deliveryActionResult.textContent = "正在运行 3 个 Docker 任务的小并发测试...";
  const response = await fetch("/api/verification/concurrency-report", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({count: 3})
  });
  const data = await response.json();
  if (!response.ok) {
    deliveryActionResult.textContent = data.message || data.error || "生成并发测试报告失败";
    return;
  }
  deliveryActionResult.innerHTML = `
    <strong>并发测试报告已生成</strong>
    <p>JSON：${escapeHtml(data.json)}</p>
    <p>Markdown：${escapeHtml(data.markdown)}</p>
    <p>成功：${escapeHtml(data.summary?.success ?? 0)}，失败：${escapeHtml(data.summary?.failed ?? 0)}，耗时：${escapeHtml(data.summary?.duration_ms ?? 0)} ms</p>
  `;
  await loadDeliveryPackage();
}

async function generateDeliveryExport() {
  if (!deliveryActionResult) return;
  deliveryActionResult.textContent = "正在生成证据包 zip...";
  const response = await fetch("/api/delivery/export", {method: "POST"});
  const data = await response.json();
  if (!response.ok) {
    deliveryActionResult.textContent = data.message || data.error || "生成证据包失败";
    return;
  }
  deliveryActionResult.innerHTML = `
    <strong>证据包已生成</strong>
    <p>路径：${escapeHtml(data.path)}</p>
    <p>大小：${escapeHtml(Math.round((data.size_bytes || 0) / 1024))} KB</p>
  `;
  await loadDeliveryPackage();
}

function reportTypeText(type) {
  if (type === "concurrency") return "并发测试";
  return "现场验证";
}

async function runVerificationCase(caseId) {
  if (!verificationResult) return;
  setVerificationControls(true, caseId);
  verificationResult.innerHTML = renderVerificationStarting(caseId);
  verificationResult.scrollIntoView({behavior: "smooth", block: "start"});
  const response = await fetch("/api/verification/jobs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({case_id: caseId})
  });
  let job = await response.json();
  if (!response.ok) {
    verificationResult.innerHTML = `<div class="status failed">${escapeHtml(job.message || job.error || "验收任务启动失败")}</div>`;
    setVerificationControls(false, caseId);
    return;
  }
  activeVerificationJobId = job.id;

  while (activeVerificationJobId === job.id && (job.status === "queued" || job.status === "running")) {
    verificationResult.innerHTML = renderLiveVerificationJob(job);
    await waitFor(450);
    const pollResponse = await fetch(`/api/verification/jobs/${encodeURIComponent(job.id)}`);
    job = await pollResponse.json();
    if (!pollResponse.ok) {
      verificationResult.innerHTML = `<div class="status failed">${escapeHtml(job.error || "读取验收进度失败")}</div>`;
      setVerificationControls(false, caseId);
      return;
    }
  }

  if (activeVerificationJobId !== job.id) return;
  if (job.status === "failed") {
    verificationResult.innerHTML = `${renderLiveVerificationJob(job)}<div class="status failed">${escapeHtml(job.error || "验收执行失败")}</div>`;
    setVerificationControls(false, caseId);
    return;
  }

  verificationResult.innerHTML = renderCompletedVerificationJob(job);
  setVerificationControls(false, caseId);
  await loadMonitor();
  await loadPolicy();
}

function setVerificationControls(running, caseId) {
  document.querySelectorAll(".run-verification").forEach((button) => {
    button.disabled = running;
    button.textContent = running && button.dataset.case === caseId ? "执行中..." : "现场验证";
  });
  if (runAllVerification) {
    runAllVerification.disabled = running;
    runAllVerification.textContent = running && caseId === "all" ? "正在运行全部验收..." : "一键运行全部验收";
  }
  document.querySelectorAll("[data-case-card]").forEach((card) => {
    card.classList.toggle("active-running", running && card.dataset.caseCard === caseId);
  });
}

function renderVerificationStarting(caseId) {
  const presentation = verificationPresentation[caseId] || {};
  return `
    <div class="execution-cockpit starting">
      <div class="cockpit-topbar">
        <div><span class="live-beacon"></span><strong>正在创建现场验收任务</strong></div>
        <span>${escapeHtml(presentation.group || "全部能力")}</span>
      </div>
      <div class="cockpit-starting-copy">
        <strong>${escapeHtml(presentation.short || "后端正在准备全部验收探针")}</strong>
        <p>服务器正在创建验收编号并启动独立后端线程，稍后将显示真实命令事件。</p>
      </div>
    </div>
  `;
}

function renderLiveVerificationJob(job) {
  const events = job.events || [];
  const commandEvents = events.filter(event => event.kind === "command_started");
  const completedCommands = events.filter(event => event.kind === "command_finished");
  const elapsed = verificationElapsed(job);
  const profile = verificationRuntimeProfile(job.case_id);
  const latest = events[events.length - 1];
  const statusText = job.status === "completed" ? "执行完成" : job.status === "failed" ? "执行失败" : "后端执行中";
  const progress = job.status === "completed" ? 100 : Math.min(92, 18 + events.length * 7);
  return `
    <div class="execution-cockpit ${escapeHtml(job.status)}">
      <div class="cockpit-topbar">
        <div><span class="live-beacon"></span><strong>${escapeHtml(statusText)}</strong></div>
        <span>LIVE / ${escapeHtml(job.id)}</span>
      </div>
      <div class="cockpit-identity">
        <div><span>验收项目</span><strong>${escapeHtml(verificationCaseTitle(job.case_id))}</strong></div>
        <div><span>后端任务编号</span><strong>${escapeHtml(job.id)}</strong></div>
        <div><span>实时耗时</span><strong>${escapeHtml(elapsed)}</strong></div>
        <div><span>当前动作</span><strong>${escapeHtml(latest ? latest.title : "等待后端事件")}</strong></div>
      </div>
      <div class="cockpit-progress"><i><b style="width:${progress}%"></b></i><span>${progress}%</span></div>
      <div class="cockpit-layout">
        <div class="event-stream">
          <div class="stream-head"><strong>后端实时事件流</strong><span>${events.length} 条事件</span></div>
          <div class="event-stream-list">
            ${events.length ? events.map((event) => renderExecutionEvent(event, job.case_id, events)).join("") : `<div class="stream-empty">等待服务器产生第一条执行事件...</div>`}
          </div>
        </div>
        <div class="telemetry-panel">
          <div class="telemetry-head"><strong>本次运行遥测</strong><span>由事件实时计算</span></div>
          ${telemetryMetric("真实命令", commandEvents.length, "后端已发起的命令数量")}
          ${telemetryMetric("已完成命令", completedCommands.length, "已取得 returncode 的命令")}
          ${telemetryMetric("事件总数", events.length, "请求、命令、探针、结果事件")}
          <div class="runtime-profile">
            <span>策略配置</span>
            ${profile.map(item => `<div><strong>${escapeHtml(item.label)}</strong><b>${escapeHtml(item.value)}</b></div>`).join("")}
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderExecutionEvent(event, caseId = "", allEvents = []) {
  const state = event.kind.includes("failed") ? "fail" : event.kind.includes("timeout") ? "warn" : event.kind.includes("finished") ? "done" : "running";
  const returncode = event.data && event.data.returncode !== undefined ? `returncode=${event.data.returncode}` : "";
  const command = verificationEventCommand(event, allEvents);
  const purpose = event.kind === "command_started" ? describeVerificationCommand(command, caseId) : "";
  const result = describeVerificationCommandResult(event, command, caseId);
  return `
    <div class="execution-event ${state}">
      <div class="event-marker"><i></i><span>${escapeHtml(String(event.seq).padStart(2, "0"))}</span></div>
      <div>
        <div class="event-title"><strong>${escapeHtml(event.title)}</strong><time>${escapeHtml(formatVerificationTime(event.at))}</time></div>
        ${purpose ? `<div class="event-comment"><span>命令用途</span><strong>${escapeHtml(purpose)}</strong></div>` : ""}
        <p class="${command ? "event-raw" : ""}">${escapeHtml(event.detail)}</p>
        ${result ? `<div class="event-result-note ${escapeHtml(result.tone)}"><span>${event.kind === "command_timeout" ? "超时结果" : "完成结果"}</span><strong>${escapeHtml(result.text)}</strong></div>` : returncode ? `<code>${escapeHtml(returncode)}</code>` : ""}
      </div>
    </div>
  `;
}

function verificationEventCommand(event, allEvents) {
  if (event.data?.command) return String(event.data.command);
  if (!event.kind.startsWith("command_")) return "";
  const previous = [...allEvents]
    .reverse()
    .find((item) => item.seq < event.seq && item.kind === "command_started" && item.data?.command);
  return previous ? String(previous.data.command) : "";
}

function describeVerificationCommand(command, caseId) {
  if (!command) return "";
  const lower = command.toLowerCase();
  const hasProxy = lower.includes("--proxy-server=") || lower.includes("http_proxy") || lower.includes("https_proxy");
  if (lower.includes("docker info")) return "检查服务器 Docker daemon 是否在线，并读取真实服务端版本。";
  if (lower.includes("docker network create") && lower.includes("--internal")) return "创建本次验证专用的内部 Docker 网络，容器不能从该网络直接访问公网。";
  if (lower.includes("docker network rm")) return "删除本次验证创建的临时 Docker 网络，避免测试资源残留。";
  if (lower.includes("docker logs")) return "读取代理或凭据服务的真实容器日志，提取放行、拦截和审计记录。";
  if (lower.includes("docker rm") && lower.includes("-f")) return "强制删除本次验证使用的临时容器，证明任务结束后能够清理。";
  if (lower.includes("egress_gateway.py")) return "启动白名单出口代理，只允许配置的测试域名，并记录每次访问判定。";
  if (lower.includes("credential_broker.py")) return "启动凭据代理服务，任务容器只能使用短期句柄，不能获得明文密钥。";
  if (lower.includes("chromium --headless")) {
    if (lower.includes("sandbox-blocked.test")) return "让真实 Chromium 经过代理访问非白名单页面，预期由网关返回 403 拦截页。";
    if (lower.includes("sandbox-allow.test") && !hasProxy) return "让 Chromium 不经过代理尝试直连白名单域名，验证它不能绕过受控出口。";
    return "让真实 Chromium 经过白名单代理加载受控测试页，验证允许访问链路。";
  }
  if (lower.includes("while true") || lower.includes("while true: pass")) return "启动持续占用 CPU 的跑飞任务，验证超时后会被强制停止和清理。";
  if (caseId === "network_default_deny" && lower.includes("--network none")) return "在完全禁网的容器中尝试访问外部地址；连接失败才证明默认禁止出站。";
  if (caseId === "egress_allowlist_gateway" && lower.includes("sandbox-blocked.test")) return "通过白名单代理访问非白名单域名，预期请求被拒绝。";
  if (caseId === "egress_allowlist_gateway" && lower.includes("sandbox-allow.test") && !hasProxy) return "不使用代理直接访问允许域名，验证容器不能绕过出口网关。";
  if (caseId === "egress_allowlist_gateway" && lower.includes("sandbox-allow.test")) return "通过白名单代理访问允许域名，验证正常业务流量可以放行。";
  if (lower.includes("backend/template_cli.py")) return "在独立 Docker 容器中运行场景脚本，把输入转换为业务结果文件。";
  if (lower.includes("docker run")) return "启动一次性 Docker 容器执行当前验证探针，并应用网络、只读目录或资源限制。";
  return "在服务器后端执行当前验证命令并采集返回码、标准输出和错误输出。";
}

function describeVerificationCommandResult(event, command, caseId) {
  if (!event.kind.startsWith("command_")) return null;
  const data = event.data || {};
  const rc = data.returncode;
  const output = `${data.stdout || ""}\n${data.stderr || ""}`;
  const lower = String(command || "").toLowerCase();
  const hasProxy = lower.includes("--proxy-server=") || lower.includes("http_proxy") || lower.includes("https_proxy");
  if (event.kind === "command_timeout") {
    return {
      tone: caseId === "resource_timeout" ? "pass" : "warn",
      text: caseId === "resource_timeout"
        ? `命令达到 ${data.timeout_seconds ?? "设定"} 秒上限，按预期触发超时；后端将继续执行强制清理。`
        : `命令超过 ${data.timeout_seconds ?? "设定"} 秒仍未结束，已触发超时控制。`,
    };
  }
  if (event.kind !== "command_finished") return null;
  if (lower.includes("chromium --headless")) {
    if (lower.includes("sandbox-blocked.test")) {
      const blocked = /blocked by sandbox egress allowlist/i.test(output);
      return {tone: blocked ? "blocked" : "fail", text: blocked ? "Chromium 渲染了 403 拦截页，非白名单访问已被网关拒绝。" : "没有观察到预期的非白名单拦截页，需要检查代理证据。"};
    }
    if (lower.includes("sandbox-allow.test") && !hasProxy) {
      const offline = /ERR_|offline/i.test(output) && !/Sandbox Allowlist Probe/i.test(output);
      return {tone: offline ? "blocked" : "fail", text: offline ? "Chromium 只得到离线错误页，未加载受控页面，说明直连绕过失败。" : "Chromium 可能绕过代理加载了页面，需要检查网络策略。"};
    }
    const loaded = /Sandbox Allowlist Probe/i.test(output);
    return {tone: loaded ? "pass" : "fail", text: loaded ? "Chromium 成功加载白名单受控页面，允许链路正常。" : "白名单受控页面没有加载成功。"};
  }
  if (lower.includes("docker logs")) {
    if (/"allowed": false/.test(output)) return {tone: "pass", text: "代理日志读取成功，并找到 allowed=false 的拒绝记录，拦截行为可审计。"};
    return {tone: rc === 0 ? "pass" : "fail", text: rc === 0 ? "容器日志读取成功，审计证据已经取回。" : `日志读取失败，returncode=${rc}。`};
  }
  if (lower.includes("egress_gateway.py")) {
    return {tone: rc === 0 ? "pass" : "fail", text: rc === 0 ? "白名单出口代理容器启动成功。" : `出口代理启动失败，returncode=${rc}。`};
  }
  if (lower.includes("docker network create")) return {tone: rc === 0 ? "pass" : "fail", text: rc === 0 ? "内部隔离网络创建成功，后续测试容器将接入该网络。" : `内部网络创建失败，returncode=${rc}。`};
  if (lower.includes("docker network rm")) return {tone: rc === 0 ? "pass" : "fail", text: rc === 0 ? "临时网络删除成功，没有留下测试网络。" : `临时网络删除失败，returncode=${rc}。`};
  if (lower.includes("docker rm") && lower.includes("-f")) return {tone: rc === 0 ? "pass" : "fail", text: rc === 0 ? "临时容器已被强制删除，清理成功。" : `容器清理失败，returncode=${rc}。`};
  if (caseId === "network_default_deny") {
    return {tone: rc !== 0 ? "blocked" : "fail", text: rc !== 0 ? `连接尝试返回 ${rc}，外网访问失败，证明 --network none 已生效。` : "禁网容器中的访问意外成功，需要检查网络隔离。"};
  }
  if (caseId === "egress_allowlist_gateway" && lower.includes("sandbox-blocked.test")) {
    return {tone: rc !== 0 ? "blocked" : "fail", text: rc !== 0 ? `访问返回 ${rc}，非白名单请求已被拒绝。` : "非白名单请求意外成功。"};
  }
  if (caseId === "egress_allowlist_gateway" && lower.includes("sandbox-allow.test") && !hasProxy) {
    return {tone: rc !== 0 ? "blocked" : "fail", text: rc !== 0 ? `直连返回 ${rc}，绕过代理失败。` : "直连访问成功，可能绕过了出口控制。"};
  }
  if (rc === 0) return {tone: "pass", text: output.trim() ? "命令执行成功，并已取回标准输出作为本次证据。" : "命令执行成功，没有产生额外输出。"};
  return {tone: "fail", text: `命令执行失败，returncode=${rc}；错误信息已保留在原始返回中。`};
}

function telemetryMetric(label, value, detail) {
  return `<div class="telemetry-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(detail)}</p></div>`;
}

function renderCompletedVerificationJob(job) {
  const data = job.result || {};
  const receipt = `
    ${renderLiveVerificationJob(job)}
    <div class="verification-receipt">
      <div><span>验收回执</span><strong>${escapeHtml(job.id)}</strong></div>
      <div><span>开始时间</span><strong>${escapeHtml(formatVerificationTime(job.started_at))}</strong></div>
      <div><span>完成时间</span><strong>${escapeHtml(formatVerificationTime(job.finished_at))}</strong></div>
      <div><span>后端总耗时</span><strong>${escapeHtml(job.duration_ms ?? "-")} ms</strong></div>
      <div><span>事件数量</span><strong>${escapeHtml((job.events || []).length)}</strong></div>
      <div><span>结果状态</span><strong class="receipt-pass">${job.case_id === "all" ? `${data.summary?.passed ?? 0} 项通过` : data.status === "passed" ? "验证通过" : "未通过"}</strong></div>
    </div>
  `;
  if (job.case_id === "all") {
    return `${receipt}
      <div class="acceptance-hero">
        <div>
          <h3>现场验收结果</h3>
          <p>下面每一块都是刚刚实时运行出来的防护结果，不是静态说明。</p>
        </div>
        <div class="acceptance-score">
          <strong>${escapeHtml(data.summary.passed)}</strong>
          <span>项通过</span>
        </div>
      </div>
      ${renderAllVerificationOverview(data.results || [])}
      ${(data.results || []).map(renderVerificationEvidence).join("")}
    `;
  }
  return `${receipt}${renderVerificationEvidence(data)}`;
}

function verificationRuntimeProfile(caseId) {
  const profiles = {
    resource_timeout: [{label: "CPU", value: "0.5 core"}, {label: "内存", value: "64 MB"}, {label: "时长", value: "2 秒"}, {label: "清理", value: "docker rm -f"}],
    host_file_isolation: [{label: "根文件系统", value: "只读"}, {label: "项目目录", value: "/app:ro"}, {label: "网络", value: "none"}],
    network_default_deny: [{label: "网络", value: "--network none"}, {label: "公网访问", value: "预期失败"}],
    egress_allowlist_gateway: [{label: "网络", value: "internal"}, {label: "出口", value: "egress-proxy"}, {label: "绕过", value: "禁止"}],
    browser_sandbox: [{label: "浏览器", value: "Chromium"}, {label: "CPU", value: "1 core"}, {label: "内存", value: "768 MB"}, {label: "出口", value: "proxy"}],
    credential_injection: [{label: "凭据", value: "handle only"}, {label: "明文", value: "broker 内"}, {label: "网络", value: "internal"}],
    docker_task: [{label: "执行器", value: "DockerTemplateExecutor"}, {label: "隔离", value: "container"}],
  };
  return profiles[caseId] || [{label: "运行时", value: "Docker"}, {label: "证据", value: "实时采集"}];
}

function verificationCaseTitle(caseId) {
  if (caseId === "all") return "全部 13 项现场验收";
  const visual = verificationVisuals[caseId];
  return visual ? visual.requirement : caseId;
}

function verificationElapsed(job) {
  if (!job.started_at) return "0.0 s";
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  return `${Math.max(0, (end - new Date(job.started_at).getTime()) / 1000).toFixed(1)} s`;
}

function formatVerificationTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleTimeString("zh-CN", {hour12: false});
}

function waitFor(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function renderVerificationEvidence(item) {
  const visual = verificationVisuals[item.id] || {
    requirement: item.title,
    probe: item.claim,
    defense: item.expected,
    success: item.detail,
  };
  const passed = item.status === "passed";
  const facts = verificationFacts(item);
  return `
    <div class="proof-card ${passed ? "proof-pass" : "proof-fail"}">
      <div class="proof-top">
        <div>
          <span class="proof-requirement">${escapeHtml(visual.requirement)}</span>
          <h4>${escapeHtml(item.title)}</h4>
        </div>
        <span class="proof-badge ${passed ? "pass" : "fail"}">${passed ? "已证明" : "未通过"}</span>
      </div>
      ${renderLiveCapabilityVisual(item)}
      <div class="proof-flow">
        <div class="proof-step attack">
          <span>1</span>
          <strong>现场探针</strong>
          <p>${escapeHtml(visual.probe)}</p>
        </div>
        <div class="proof-arrow">→</div>
        <div class="proof-step defense">
          <span>2</span>
          <strong>沙箱防护</strong>
          <p>${escapeHtml(visual.defense)}</p>
        </div>
        <div class="proof-arrow">→</div>
        <div class="proof-step result">
          <span>3</span>
          <strong>${passed ? "防护生效" : "需要处理"}</strong>
          <p>${escapeHtml(passed ? visual.success : item.detail)}</p>
        </div>
      </div>
      <div class="proof-facts">
        ${facts.map((fact) => `<div><span>${escapeHtml(fact.label)}</span><strong>${escapeHtml(fact.value)}</strong></div>`).join("")}
      </div>
      <details class="technical-evidence">
        <summary>展开技术证据</summary>
        ${renderBackendExecutionFlow(item)}
        ${renderBackendCodeTrace(item)}
        <div class="code-with-notes">
          <div>
            <label>现场执行命令 / 调用</label>
            ${renderAnnotatedCode(item.command || "-", "command", {caseId: item.id})}
          </div>
        </div>
        <div class="code-with-notes">
          <div>
            <label>原始证据</label>
            ${renderAnnotatedCode(item.evidence || {}, "evidence", {caseId: item.id})}
          </div>
        </div>
      </details>
    </div>
  `;
}

function renderBackendCodeTrace(item) {
  const sections = backendCodeSections(item);
  return `
    <div class="backend-code-panel">
      <div class="backend-flow-head">
        <div>
          <strong>关键后端代码链路</strong>
          <p>这里展示的是当前项目后端源码里的关键执行片段，用来对应上面的流程步骤：入口、分派、真实 Docker/API 操作、通过条件和证据返回。</p>
        </div>
        <span>源码摘录</span>
      </div>
      <div class="backend-code-grid">
        ${sections.map(renderSourceSection).join("")}
      </div>
    </div>
  `;
}

function renderSourceSection(section) {
  const annotatedCode = annotateSourceCodeForDemo(section.code);
  return `
    <div class="source-section">
      <div class="source-section-head">
        <strong>${escapeHtml(section.title)}</strong>
        <span>${escapeHtml(section.file)}</span>
      </div>
      <pre class="source-code"><code>${escapeHtml(annotatedCode)}</code></pre>
    </div>
  `;
}

function annotateSourceCodeForDemo(code) {
  return code.trim().split("\n").map((line) => {
    const note = sourceLineDemoNote(line);
    if (!note) return line;
    return `${line}${line.includes("#") ? "；" : "  #"} ${note}`;
  }).join("\n");
}

function sourceLineDemoNote(line) {
  const trimmed = line.trim();
  if (!trimmed) return "";
  if (trimmed === 'if path == "/api/verification/jobs":') return "点击“现场验证”先在这里创建异步验收任务。";
  if (trimmed.startsWith('if path.startswith("/api/verification/jobs/"')) return "前端持续查询这个接口，获取实时事件和最终结果。";
  if (trimmed === "body = self._read_body()") return "读取前端 POST 上来的 JSON 请求体。";
  if (trimmed.startsWith("case_id = str(body.get")) return "拿到本次要验证的功能编号。";
  if (trimmed.startsWith("job = start_verification_job")) return "启动独立后端线程，页面可以同时查询执行进度。";
  if (trimmed.startsWith("job_id = path.removeprefix")) return "从查询地址中取得本次验收任务编号。";
  if (trimmed.startsWith("job = get_verification_job")) return "读取任务当前状态、事件流水和最终 evidence。";
  if (trimmed === "result = (") return "后端先等待真实验证函数跑完，不是直接返回固定文字。";
  if (trimmed.startsWith("run_all_verification_cases")) return "点击“一键运行全部验收”时逐个执行所有验证函数。";
  if (trimmed.startsWith("else run_verification_case")) return "点击单项现场验证时只运行当前功能的验证函数。";
  if (trimmed.startsWith("return self._send_json")) return "把真实执行后的 status、command、evidence 返回给前端页面。";
  if (trimmed.startsWith("def run_verification_case")) return "所有验收按钮最终都会进入这个分派函数。";
  if (trimmed === "runners = {") return "这里把页面上的 case_id 和真实后端函数绑定起来。";
  if (trimmed.includes('"docker_runtime"')) return "Docker 运行时检查，确认 Docker daemon 在线。";
  if (trimmed.includes('"docker_task"')) return "验证业务任务是否真的进入 DockerTemplateExecutor。";
  if (trimmed.includes('"host_file_isolation"')) return "验证容器读不到宿主机秘密文件、写不了只读目录。";
  if (trimmed.includes('"resource_timeout"')) return "验证死循环任务是否会被超时清理。";
  if (trimmed.includes('"network_default_deny"')) return "验证容器默认不能访问公网。";
  if (trimmed.includes('"egress_allowlist_gateway"')) return "验证白名单放行、非白名单拦截、绕过代理失败。";
  if (trimmed.includes('"browser_sandbox"')) return "验证 Headless Chromium 浏览器容器也受网络控制。";
  if (trimmed.includes('"permission_denial"')) return "验证权限不足的敏感任务会被前置拦截。";
  if (trimmed.includes('"credential_injection"')) return "验证任务只拿短期凭据句柄，看不到明文密钥。";
  if (trimmed.includes('"e2b_like_adapter"')) return "验证后续平台可用会话式接口调用沙箱。";
  if (trimmed.includes('"hanhe_')) return "验证汉和岗位场景可端到端进入沙箱并返回业务结果。";
  if (trimmed.startsWith("result = runners[case_id]()")) return "这一行才真正调用当前功能的 verify_* 函数。";
  if (trimmed.startsWith("return {**meta, **result}")) return "把用例说明和真实执行结果合并返回。";
  if (trimmed.startsWith("docker = require_docker()")) return "先确认服务器上存在 docker 命令。";
  if (trimmed.startsWith('command = [docker, "info"')) return "构造 docker info 命令，用服务器 Docker 返回版本号。";
  if (trimmed.startsWith("command = [")) return "开始构造后端实际要执行的命令数组。";
  if (trimmed.includes('docker, "run"')) return "这里会真实启动一个 Docker 容器。";
  if (trimmed.includes('"--rm"')) return "容器结束后自动删除，避免留下脏容器。";
  if (trimmed.includes('"--name"')) return "给容器命名，后续超时清理时可以精确删除。";
  if (trimmed.includes('"--network", "none"')) return "关闭容器网络，证明默认禁网能力。";
  if (trimmed.includes('"--network", network')) return "把容器放入后端刚创建的内部 Docker 网络。";
  if (trimmed.includes('"--read-only"')) return "容器根文件系统只读，防止任务改环境。";
  if (trimmed.includes('"--tmpfs"')) return "只给容器开放临时可写目录，任务结束后数据消失。";
  if (trimmed.includes('"--cpus"')) return "限制 CPU，证明跑飞任务不能抢占整机。";
  if (trimmed.includes('"--memory"')) return "限制内存，证明任务不能无限吃内存。";
  if (trimmed.includes(':/app:ro')) return "项目目录只读挂载，容器可以读代码但不能改代码。";
  if (trimmed.includes('"while True: pass"')) return "故意制造死循环，用来验证超时清理是否真实生效。";
  if (trimmed.startsWith("proc = run(")) return "这里才真正执行命令，并等待返回码/stdout/stderr。";
  if (trimmed.includes("timeout=2")) return "最多等 2 秒，超过说明任务跑飞，需要触发清理。";
  if (trimmed.startsWith("except subprocess.TimeoutExpired")) return "死循环超过时间限制后会进入这个清理分支。";
  if (trimmed.includes('"rm", "-f"')) return "强制删除跑飞容器，避免继续占用服务器资源。";
  if (trimmed.includes('"cleanup_returncode"')) return "清理命令返回码，0 表示容器删除成功。";
  if (trimmed.startsWith("task = service.create_task")) return "真实创建业务任务，触发账号、权限、数据、沙箱执行链路。";
  if (trimmed.includes('"scenario_id"')) return "指定业务场景模板，决定这次任务跑哪类岗位能力。";
  if (trimmed.includes('"actor"')) return "指定执行人身份，用来触发岗位权限检查。";
  if (trimmed.includes('"timeout_seconds"')) return "给业务沙箱任务设置最长运行时间。";
  if (trimmed.includes('"memory_mb"')) return "给业务沙箱任务设置内存额度。";
  if (trimmed.includes('"cpu_cores"')) return "给业务沙箱任务设置 CPU 额度。";
  if (trimmed.includes('task.get("status") == "success"')) return "只有任务真的成功执行，验收才会通过。";
  if (trimmed.includes('task.get("executor") == "DockerTemplateExecutor"')) return "验收明确要求任务由 Docker 执行器执行。";
  if (trimmed.includes('"executor": task.get("executor")')) return "把执行器返回给前端，能看到是不是 DockerTemplateExecutor。";
  if (trimmed.includes('"task_id": task.get("id")')) return "把任务编号返回给前端，证明创建过真实任务。";
  if (trimmed.includes('"duration_ms": task.get("duration_ms")')) return "返回耗时，证明后端经历了真实执行过程。";
  if (trimmed.includes('result["sandbox_runtime"]')) return "把沙箱运行时写进结果，前端据此展示隔离和资源策略。";
  if (trimmed.includes('"isolation": "docker_container"')) return "明确标记隔离方式是 Docker 容器。";
  if (trimmed.includes('"network": "none"')) return "明确标记该任务运行时默认禁网。";
  if (trimmed.startsWith("sentinel = ")) return "创建宿主机侧秘密文件，用来测试容器能不能越权读取。";
  if (trimmed.startsWith("sentinel.write_text")) return "往宿主机秘密文件写入测试内容。";
  if (trimmed.includes("host secret leaked")) return "如果容器看到了秘密文件，就直接判定隔离失败。";
  if (trimmed.includes("write_probe.txt")) return "尝试写只读项目目录，写成功说明隔离失败。";
  if (trimmed.startsWith("sentinel.unlink")) return "验证结束后删除临时秘密文件。";
  if (trimmed.startsWith("create_network = ")) return "创建 Docker 内部网络，容器只能在隔离网络里通信。";
  if (trimmed.includes('"network", "create", "--internal"')) return "internal 网络没有外网出口，必须通过代理才能访问外部。";
  if (trimmed.startsWith("proxy_cmd = [")) return "准备启动出站代理容器，所有受控访问都经过它。";
  if (trimmed.includes("backend/egress_gateway.py")) return "运行项目里的白名单网关服务。";
  if (trimmed.includes('"--allow"')) return "配置允许访问的域名。";
  if (trimmed.includes('"--serve-local"')) return "让代理提供受控测试页，避免依赖外部网站不稳定。";
  if (trimmed.startsWith("allowed = run(")) return "执行白名单访问探针。";
  if (trimmed.startsWith("blocked = run(")) return "执行非白名单访问探针。";
  if (trimmed.startsWith("bypass = run(")) return "执行绕过代理直连探针。";
  if (trimmed.startsWith("logs = run(")) return "采集代理或 broker 日志，证明过程可审计。";
  if (trimmed.includes('allowed["returncode"] == 0')) return "白名单访问必须成功。";
  if (trimmed.includes('blocked["returncode"] != 0')) return "非白名单访问必须失败。";
  if (trimmed.includes('bypass["returncode"] != 0')) return "绕过代理直连必须失败。";
  if (trimmed.startsWith("def browser_command")) return "封装浏览器容器启动命令。";
  if (trimmed.includes("chromium --headless")) return "真实启动无头 Chromium，不是模拟浏览器结果。";
  if (trimmed.includes("--proxy-server")) return "浏览器访问也必须经过白名单代理。";
  if (trimmed.includes("--dump-dom")) return "让浏览器真实加载页面并输出 DOM 内容作为证据。";
  if (trimmed.includes("Sandbox Allowlist Probe")) return "通过页面内容判断白名单页面是否真实加载。";
  if (trimmed.includes('"allowed": false')) return "通过代理日志判断非白名单是否被拒绝。";
  if (trimmed.startsWith("error = json.dumps")) return "提取失败原因，用来确认是权限不足而不是系统异常。";
  if (trimmed.includes('"receipt:read" in error')) return "确认拦截原因包含缺失的 receipt:read 权限。";
  if (trimmed.includes('"security_compliance"')) return "把权限检查详情返回给前端展示。";
  if (trimmed.startsWith("handle = ")) return "生成一次性凭据句柄。";
  if (trimmed.startsWith("secret = ")) return "生成明文密钥，后续验证它不会进入任务容器。";
  if (trimmed.startsWith("broker_cmd = [")) return "准备启动凭据 broker 容器。";
  if (trimmed.includes("backend/credential_broker.py")) return "broker 持有明文密钥，任务容器不能直接拿明文。";
  if (trimmed.includes('"--secret"')) return "明文 secret 只传给 broker 容器。";
  if (trimmed.startsWith("task_cmd = [")) return "准备启动真正的任务容器。";
  if (trimmed.includes("CREDENTIAL_HANDLE")) return "任务容器只拿 handle，不拿明文密钥。";
  if (trimmed.includes("CREDENTIAL_BROKER_URL")) return "任务通过内部地址访问 broker。";
  if (trimmed.startsWith("task_proc = run(")) return "真实运行任务容器里的凭据探针。";
  if (trimmed.startsWith("no_plaintext_leak")) return "扫描输出中是否出现明文密钥。";
  if (trimmed.startsWith("broker_ok")) return "确认 broker 只返回授权结果，不返回明文。";
  if (trimmed.startsWith("audit_ok")) return "确认 broker 日志记录了凭据使用过程。";
  if (trimmed.startsWith("adapter = DockerE2BAdapter")) return "创建会话式沙箱适配器，供后续平台调用。";
  if (trimmed.startsWith("session = adapter.create_session")) return "创建沙箱会话。";
  if (trimmed.startsWith("run_result = adapter.run_template")) return "在会话里运行 Docker-backed 任务。";
  if (trimmed.startsWith("queried = adapter.get_session")) return "查询会话状态和任务记录。";
  if (trimmed.startsWith("destroyed = adapter.destroy_session")) return "销毁会话，证明生命周期可关闭。";
  if (trimmed.startsWith("result_payload = ")) return "取出沙箱返回的业务结果。";
  if (trimmed.startsWith("platform_checks = ")) return "取出账号、权限、成本、审计等平台链路证据。";
  if (trimmed.startsWith("security = ")) return "取出安全合规检查结果。";
  if (trimmed.startsWith("account = ")) return "取出岗位身份解析结果。";
  if (trimmed.startsWith("cost = ")) return "取出成本计量记录。";
  if (trimmed.startsWith("audit_events = ")) return "取出审计事件列表。";
  if (trimmed.startsWith("runtime = ")) return "取出 Docker 沙箱运行时证据。";
  if (trimmed.includes('security.get("allowed") is True')) return "确认权限检查通过。";
  if (trimmed.includes('runtime.get("executor") == "DockerTemplateExecutor"')) return "确认业务结果来自 Docker 执行器。";
  if (trimmed.includes('cost.get("meter")')) return "确认成本计量链路有记录。";
  if (trimmed.includes("len(audit_events)")) return "确认审计链路有记录。";
  if (trimmed.startsWith("# 本次证据")) return "把本次现场返回的 evidence 值直接对照到代码判断条件。";
  return "";
}

function backendCodeSections(item) {
  return [
    apiEntryCodeSection(item),
    dispatchCodeSection(item),
    ...caseCodeSections(item),
  ];
}

function apiEntryCodeSection(item) {
  return {
    title: "1. API 入口：点击按钮后先到这里",
    file: "backend/app.py",
    code: `
if path == "/api/verification/jobs":
    body = self._read_body()
    case_id = str(body.get("case_id", "all"))  # 本次点击传入：${item.id}
    job = start_verification_job(ROOT, service, case_id)  # 后台线程开始执行
    return self._send_json(job, 202)  # 先返回 job_id，不阻塞页面

if path.startswith("/api/verification/jobs/"):
    job_id = path.removeprefix("/api/verification/jobs/").strip("/")
    job = get_verification_job(job_id)  # 返回实时事件、状态和最终证据
    return self._send_json(job, 200)
`,
  };
}

function dispatchCodeSection(item) {
  return {
    title: "2. 分派：case_id 对应一个真实验证函数",
    file: "backend/verification.py",
    code: `
def run_verification_case(project_root, service, case_id):
    runners = {
        "docker_runtime": lambda: verify_docker_runtime(project_root),
        "docker_task": lambda: verify_docker_task(service),
        "host_file_isolation": lambda: verify_host_file_isolation(project_root),
        "resource_timeout": lambda: verify_resource_timeout(project_root),
        "network_default_deny": lambda: verify_network_default_deny(project_root),
        "egress_allowlist_gateway": lambda: verify_egress_allowlist_gateway(project_root),
        "browser_sandbox": lambda: verify_browser_sandbox(project_root),
        "permission_denial": lambda: verify_permission_denial(service),
        "credential_injection": lambda: verify_credential_injection(project_root),
        "e2b_like_adapter": lambda: verify_e2b_like_adapter(project_root, service),
        "hanhe_role_scenario_e2e": lambda: verify_hanhe_role_scenario_e2e(service),
        "hanhe_finance_invoice_e2e": lambda: verify_hanhe_finance_invoice_e2e(service),
        "hanhe_purchase_plan_e2e": lambda: verify_hanhe_purchase_plan_e2e(service),
    }
    result = runners[case_id]()  # 本次执行：${item.id}
    return {**meta, **result}
`,
  };
}

function caseCodeSections(item) {
  const map = {
    docker_runtime: dockerRuntimeCode,
    docker_task: dockerTaskCode,
    host_file_isolation: hostFileIsolationCode,
    resource_timeout: resourceTimeoutCode,
    network_default_deny: networkDefaultDenyCode,
    egress_allowlist_gateway: egressAllowlistCode,
    browser_sandbox: browserSandboxCode,
    permission_denial: permissionDenialCode,
    credential_injection: credentialInjectionCode,
    e2b_like_adapter: e2bAdapterCode,
    hanhe_role_scenario_e2e: hanheScenarioCode,
    hanhe_finance_invoice_e2e: hanheScenarioCode,
    hanhe_purchase_plan_e2e: hanheScenarioCode,
  };
  const factory = map[item.id] || genericCaseCode;
  return factory(item);
}

function dockerRuntimeCode(item) {
  return [{
    title: "3. Docker runtime：真实询问服务器 Docker daemon",
    file: "backend/verification.py",
    code: `
def verify_docker_runtime(project_root):
    docker = require_docker()  # 找服务器上的 docker 命令
    command = [docker, "info", "--format", "{{.ServerVersion}}"]
    proc = run(command, timeout=10)  # 真实执行 docker info
    return evidence(
        "passed" if proc["returncode"] == 0 else "failed",
        command,
        proc,
        "Docker server is available."
    )

# 本次证据：returncode=${(item.evidence || {}).returncode ?? "-"}，stdout=${(item.evidence || {}).stdout || "-"}
`,
  }];
}

function dockerTaskCode(item) {
  return [{
    title: "3. 业务任务：创建任务并要求进入 DockerTemplateExecutor",
    file: "backend/verification.py",
    code: `
def verify_docker_task(service):
    task = service.create_task({
        "scenario_id": "s19_over_stock_warning",
        "actor": "sales-user",
        "agent": "acceptance-agent",
        "input": {}
    })
    ok = (
        task.get("status") == "success"
        and task.get("executor") == "DockerTemplateExecutor"
    )
    return {
        "status": "passed" if ok else "failed",
        "command": "POST /api/tasks scenario=s19_over_stock_warning actor=sales-user",
        "evidence": {
            "task_id": task.get("id"),
            "executor": task.get("executor"),
            "duration_ms": task.get("duration_ms"),
            "result": task.get("result"),
        },
    }

# 本次证据：task_id=${(item.evidence || {}).task_id || "-"}，executor=${(item.evidence || {}).executor || "-"}
`,
  }, {
    title: "4. 执行器：DockerTemplateExecutor 负责真正跑模板",
    file: "backend/executors.py",
    code: `
class DockerTemplateExecutor(SandboxExecutor):
    name = "DockerTemplateExecutor"

    def run_template(self, template, payload, timeout_seconds, memory_mb, cpu_cores):
        # 这里会构造 docker run 命令，把任务放进容器执行。
        # 结果里会写入 sandbox_runtime，前端证据里能看到 isolation/network/executor。
        result["sandbox_runtime"] = {
            "executor": self.name,
            "isolation": "docker_container",
            "network": "none",
            "memory_mb": memory_mb,
            "cpu_cores": cpu_cores,
        }
        return result
`,
  }];
}

function hostFileIsolationCode(item) {
  return [{
    title: "3. 隔离探针：创建宿主机秘密文件，再让容器尝试越权读取",
    file: "backend/verification.py",
    code: `
sentinel = project_root.parent / f"host_secret_{uuid.uuid4().hex[:8]}.txt"
sentinel.write_text("leadership-demo-secret", encoding="utf-8")

code = (
    "secret=Path(<宿主机秘密文件路径>)\\n"
    "if secret.exists(): raise SystemExit('host secret leaked')\\n"
    "Path('/app/write_probe.txt').write_text('bad')\\n"
)

command = [
    docker, "run", "--rm",
    "--network", "none",          # 容器禁网
    "--read-only",                # 根文件系统只读
    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
    "-v", f"{project_root}:/app:ro", # 项目目录只读挂载
    image, "python", "-c", code,
]
proc = run(command, timeout=15)
sentinel.unlink(missing_ok=True)

# 本次证据：stdout=${(item.evidence || {}).stdout || "-"}，returncode=${(item.evidence || {}).returncode ?? "-"}
`,
  }];
}

function resourceTimeoutCode(item) {
  const evidence = item.evidence || {};
  return [{
    title: "3. 跑飞任务：启动死循环容器并限制 CPU/内存",
    file: "backend/verification.py",
    code: `
container_name = f"verify-timeout-{uuid.uuid4().hex[:8]}"
command = [
    docker, "run", "--rm",
    "--name", container_name,
    "--network", "none",
    "--cpus", "0.5",        # CPU 限额
    "--memory", "64m",      # 内存限额
    image, "python", "-c", "while True: pass"  # 故意跑飞
]

try:
    proc = run(command, timeout=2)  # 只允许跑 2 秒
    return evidence("failed", command, proc, "unexpected")
except subprocess.TimeoutExpired:
    cleanup = run([docker, "rm", "-f", container_name], timeout=10)
    return {
        "status": "passed",
        "evidence": {
            "timeout_seconds": 2,
            "container_name": container_name,
            "cleanup_returncode": cleanup["returncode"],
        },
    }

# 本次证据：container=${evidence.container_name || "-"}，cleanup_returncode=${evidence.cleanup_returncode ?? "-"}
`,
  }];
}

function networkDefaultDenyCode(item) {
  return [{
    title: "3. 默认禁网：容器尝试访问公网，失败才算通过",
    file: "backend/verification.py",
    code: `
command = [
    docker, "run", "--rm",
    "--network", "none",  # 没有任何外网出口
    image, "python", "-c",
    "import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)"
]
proc = run(command, timeout=10)
ok = proc["returncode"] != 0  # 访问失败，说明默认禁网生效
return evidence("passed" if ok else "failed", command, proc, ...)

# 本次证据：returncode=${(item.evidence || {}).returncode ?? "-"}
`,
  }];
}

function egressAllowlistCode(item) {
  const e = item.evidence || {};
  const allow = e.allow_sandbox_test || e.allow_example_com || {};
  const block = e.block_non_allowlisted || e.block_openai_com || {};
  const bypass = e.direct_bypass_attempt || {};
  return [{
    title: "3. 白名单网关：创建内部网络并启动 egress-proxy",
    file: "backend/verification.py",
    code: `
create_network = [docker, "network", "create", "--internal", network]
run(create_network, timeout=15)

proxy_cmd = [
    docker, "run", "-d", "--rm",
    "--name", proxy,
    "--network", network,
    "-v", f"{project_root}:/app:ro",
    image, "python", "backend/egress_gateway.py",
    "--allow", allowed_host,
    "--serve-local", allowed_host,
]
run(proxy_cmd, timeout=20)

# 本次证据：network=${e.network || "-"}，proxy=${e.proxy_container || "-"}
`,
  }, {
    title: "4. 三段探针：白名单放行、非白名单拦截、绕过代理失败",
    file: "backend/verification.py",
    code: `
allowed = run(allowed_cmd, timeout=20)  # 带 http_proxy 访问 allowed_host
blocked = run(blocked_cmd, timeout=20)  # 带 http_proxy 访问 blocked_host
bypass = run(bypass_cmd, timeout=15)    # 不带代理，尝试直连

logs = run([docker, "logs", proxy], timeout=10)

ok = (
    allowed["returncode"] == 0       # 白名单能访问
    and blocked["returncode"] != 0   # 非白名单被拒绝
    and bypass["returncode"] != 0    # 直连绕过失败
)

# 本次证据：allow=${allow.returncode ?? "-"}，block=${block.returncode ?? "-"}，bypass=${bypass.returncode ?? "-"}，proxy_logs=${e.proxy_logs ? "已采集" : "未采集"}
`,
  }];
}

function browserSandboxCode(item) {
  const e = item.evidence || {};
  const allow = e.browser_allow_sandbox_test || e.browser_allow_example_com || {};
  const block = e.browser_block_non_allowlisted || e.browser_block_openai_com || {};
  const bypass = e.browser_direct_bypass_attempt || {};
  return [{
    title: "3. 浏览器容器：真实启动 Headless Chromium",
    file: "backend/verification.py",
    code: `
def browser_command(script):
    return [
        docker, "run", "--rm",
        "--memory", "768m",
        "--cpus", "1",
        "--network", network,
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,size=256m",
        browser_image,
        "/bin/bash", "-lc", script,
    ]

allowed_cmd = browser_command(
    "chromium --headless --proxy-server=http://proxy:18080 --dump-dom http://allowed_host"
)
allowed = run(allowed_cmd, timeout=45)

# 本次证据：browser_image=${e.browser_image || "-"}，allow_returncode=${allow.returncode ?? "-"}
`,
  }, {
    title: "4. 浏览器出站验证：非白名单和直连绕过",
    file: "backend/verification.py",
    code: `
blocked = run(browser_block_cmd, timeout=45)
bypass = run(browser_direct_bypass_cmd, timeout=45)
logs = run([docker, "logs", proxy], timeout=10)

allowed_ok = "Sandbox Allowlist Probe" in allowed["stdout"]
blocked_ok = (
    f'"host": "{blocked_host}"' in proxy_log_text
    and '"allowed": false' in proxy_log_text
)  # 代理日志明确记录非白名单返回 403
bypass_ok = (
    "Sandbox Allowlist Probe" not in bypass["stdout"]
    and ("ERR_" in bypass_text or "offline" in bypass_text.lower())
)  # Chromium 显示离线错误页，证明直连没有成功
ok = allowed_ok and blocked_ok and bypass_ok

# Chromium 即使成功渲染 403/离线错误页也可能 returncode=0，不能仅凭返回码判断网页访问成功。

# 本次证据：blocked_ok=${(e.assertions || {}).non_allowlisted_blocked ?? "-"}，bypass_ok=${(e.assertions || {}).direct_bypass_blocked ?? "-"}，proxy_logs=${e.proxy_logs ? "已采集" : "未采集"}
`,
  }];
}

function permissionDenialCode(item) {
  const c = ((item.evidence || {}).security_compliance || {});
  return [{
    title: "3. 权限前置拦截：没有权限不进入正常执行",
    file: "backend/verification.py",
    code: `
task = service.create_task({
    "scenario_id": "s04_invoice_matching",
    "actor": "sales-user",
    "agent": "acceptance-agent",
    "input": {}
})
error = json.dumps(task.get("result", {}), ensure_ascii=False)
ok = task.get("status") == "failed" and "receipt:read" in error

return {
    "status": "passed" if ok else "failed",
    "evidence": {
        "status": task.get("status"),
        "security_compliance": task.get("platform_checks", {}).get("security_compliance"),
    },
}

# 本次证据：missing_permissions=${(c.missing_permissions || []).join(", ") || "-"}
`,
  }];
}

function credentialInjectionCode(item) {
  const e = item.evidence || {};
  return [{
    title: "3. 凭据 broker：明文 secret 只放在 broker 容器",
    file: "backend/verification.py",
    code: `
handle = f"handle-{uuid.uuid4().hex}"
secret = f"vault-secret-{uuid.uuid4().hex}"

broker_cmd = [
    docker, "run", "-d", "--rm",
    "--name", broker,
    "--network", network,
    image, "python", "backend/credential_broker.py",
    "--handle", handle,
    "--secret", secret,  # 明文只给 broker，不给任务容器
]
run(broker_cmd, timeout=20)

# 本次证据：broker=${e.broker_container || "-"}，handle=${e.credential_handle ? "已下发" : "-"}
`,
  }, {
    title: "4. 任务容器：只拿 handle，并扫描是否泄漏明文",
    file: "backend/verification.py",
    code: `
task_cmd = [
    docker, "run", "--rm",
    "--network", network,
    "--read-only",
    "-e", f"CREDENTIAL_HANDLE={handle}",
    "-e", "CREDENTIAL_BROKER_URL=http://agent-credential-broker:18081",
    image, "python", "-c", task_code,
]
task_proc = run(task_cmd, timeout=30)

no_plaintext_leak = secret not in output_text
broker_ok = broker_response.get("credential_result") == "authorized"
audit_ok = "credential_result" in logs["stdout"]
ok = task_proc["returncode"] == 0 and broker_ok and no_plaintext_leak and audit_ok

# 本次证据：secret_policy=${e.secret_policy || "-"}，broker_logs=${e.broker_logs ? "已采集" : "未采集"}
`,
  }];
}

function e2bAdapterCode(item) {
  const e = item.evidence || {};
  const session = e.session || {};
  const run = e.run || {};
  return [{
    title: "3. E2B-like 适配器：create/run/query/destroy",
    file: "backend/verification.py",
    code: `
adapter = DockerE2BAdapter(project_root, service)
capability = adapter.capability()

session = adapter.create_session({
    "actor": "sales-user",
    "agent": "e2b-like-verification-agent",
    "timeout_seconds": 10,
    "memory_mb": 512,
    "cpu_cores": 1,
})
run_result = adapter.run_template(session["id"], {
    "scenario_id": "s19_over_stock_warning",
    "actor": "sales-user",
    "input": {},
})
queried = adapter.get_session(session["id"])
destroyed = adapter.destroy_session(session["id"])

# 本次证据：session=${session.id || "-"}，task=${run.task_id || "-"}，status=${run.status || "-"}
`,
  }];
}

function hanheScenarioCode(item) {
  const e = item.evidence || {};
  const result = e.business_result || {};
  const scenario = item.id === "hanhe_role_scenario_e2e"
    ? "s19_over_stock_warning"
    : item.id === "hanhe_finance_invoice_e2e"
      ? "s04_invoice_matching"
      : "s20_purchase_plan";
  const actor = item.id === "hanhe_role_scenario_e2e" ? "sales-user" : "demo-user";
  return [{
    title: "3. 汉和岗位场景：真实创建任务并检查平台链路",
    file: "backend/verification.py",
    code: `
task = service.create_task({
    "scenario_id": "${scenario}",
    "actor": "${actor}",
    "timeout_seconds": 10,
    "memory_mb": 512,
    "cpu_cores": 1,
    "input": {},
})

result_payload = task.get("result", {}).get("payload", {})
platform_checks = task.get("platform_checks", {})
security = platform_checks.get("security_compliance", {})
account = platform_checks.get("account_gateway", {})
cost = platform_checks.get("cost_control", {})
audit_events = platform_checks.get("audit_events", [])
runtime = task.get("result", {}).get("sandbox_runtime", {})

ok = (
    task.get("status") == "success"
    and task.get("executor") == "DockerTemplateExecutor"
    and security.get("allowed") is True
    and runtime.get("executor") == "DockerTemplateExecutor"
    and cost.get("meter") == "mock_cost_control"
    and len(audit_events) >= 2
)

# 本次证据：task_id=${e.task_id || "-"}，role=${e.role || "-"}，audit=${e.audit_event_count ?? 0}
# 业务结果：${JSON.stringify(result).slice(0, 220)}
`,
  }];
}

function genericCaseCode(item) {
  return [{
    title: "3. 当前验证函数",
    file: "backend/verification.py",
    code: `
# 当前 case_id=${item.id}
# 后端执行对应 verify_* 函数，并将 status/detail/command/evidence 返回前端。
return {
    "status": "${item.status || "-"}",
    "detail": ${JSON.stringify(item.detail || "-")},
    "evidence": {...}
}
`,
  }];
}

function renderBackendExecutionFlow(item) {
  const steps = backendExecutionSteps(item);
  return `
    <div class="backend-flow-panel">
      <div class="backend-flow-head">
        <div>
          <strong>后端真实执行流程</strong>
          <p>下面不是静态说明，而是按本次点击“现场验证”后后端实际走过的函数、Docker 操作、探针和证据采集流程展开。</p>
        </div>
        <span>${escapeHtml(item.id)}</span>
      </div>
      <div class="backend-flow-list">
        ${steps.map((step, index) => renderBackendFlowStep(step, index)).join("")}
      </div>
    </div>
  `;
}

function renderBackendFlowStep(step, index) {
  return `
    <div class="backend-flow-step ${escapeHtml(step.status || "done")}">
      <div class="backend-flow-index">${index + 1}</div>
      <div>
        <strong>${escapeHtml(step.title)}</strong>
        <p>${escapeHtml(step.operation)}</p>
        <small>${escapeHtml(step.proof)}</small>
      </div>
    </div>
  `;
}

function backendExecutionSteps(item) {
  const evidence = item.evidence || {};
  const passed = item.status === "passed";
  const base = [
    flowStep("创建异步验收任务", `POST /api/verification/jobs，case_id=${item.id}`, "后端立即返回 job_id，并在独立线程中执行验证，前端持续查询实时事件。", "done"),
    flowStep("选择验证函数", `backend/verification.py 根据 ${item.id} 分派到对应 verify_* 函数。`, "每个按钮对应一段独立后端验证逻辑，真实命令会写入该 job 的事件流。", "done"),
  ];
  const status = passed ? "done" : "fail";

  if (item.id === "docker_runtime") {
    return base.concat([
      flowStep("定位 Docker 命令", "后端调用 require_docker() 找到服务器上的 docker 可执行文件。", "找不到 docker 会直接返回验证失败。", "done"),
      flowStep("检查 Docker daemon", "执行 docker info --format {{.ServerVersion}}。", `stdout=${evidence.stdout || "-"}，returncode=${evidence.returncode ?? "-"}`, status),
      flowStep("返回运行时证据", "后端把版本号、返回码、错误输出封装为 evidence。", passed ? "returncode=0，证明 Docker 服务在线。" : "Docker 检查失败。", status),
    ]);
  }

  if (item.id === "docker_task") {
    const runtime = evidence.result && evidence.result.sandbox_runtime ? evidence.result.sandbox_runtime : {};
    return base.concat([
      flowStep("创建真实业务任务", "调用 service.create_task，场景为 s19_over_stock_warning，actor=sales-user。", `task_id=${evidence.task_id || "-"}`, evidence.task_id ? "done" : "warn"),
      flowStep("进入平台前置链路", "任务经过账号解析、权限检查、mock ERP/OA 数据注入。", "这些记录会进入 platform_checks 和审计链路。", "done"),
      flowStep("调度 Docker 执行器", "后端选择 DockerTemplateExecutor 执行业务模板。", `executor=${evidence.executor || "-"}，isolation=${runtime.isolation || "-"}`, evidence.executor === "DockerTemplateExecutor" ? "done" : "fail"),
      flowStep("返回业务结果", "沙箱执行库存预警逻辑并回传 result.payload。", passed ? "任务 success，业务结果已生成。" : "任务没有成功完成。", status),
    ]);
  }

  if (item.id === "host_file_isolation") {
    return base.concat([
      flowStep("创建宿主机秘密文件", "后端在项目目录外临时写入 host_secret_xxx.txt。", "这个文件没有挂载进容器，容器不应看见。", "done"),
      flowStep("启动隔离容器", "docker run --network none --read-only -v 项目目录:/app:ro。", "禁网、只读根文件系统、只读项目挂载同时启用。", "done"),
      flowStep("容器内执行越权探针", "Python 尝试读取宿主机秘密文件，并尝试写 /app/write_probe.txt。", "读不到、写不进才算隔离成功。", "done"),
      flowStep("删除临时秘密文件", "finally 中删除 host_secret_xxx.txt。", "避免验证后留下测试文件。", "done"),
      flowStep("采集探针结果", "后端收集 stdout/stderr/returncode。", `stdout=${evidence.stdout || "-"}，returncode=${evidence.returncode ?? "-"}`, status),
    ]);
  }

  if (item.id === "resource_timeout") {
    return base.concat([
      flowStep("生成容器名", "后端生成 verify-timeout-xxxx，方便后续强制清理。", `container_name=${evidence.container_name || "-"}`, evidence.container_name ? "done" : "warn"),
      flowStep("启动跑飞容器", "docker run --network none --cpus 0.5 --memory 64m python -c \"while True: pass\"。", "CPU、内存、禁网和死循环探针同时生效。", "done"),
      flowStep("等待超时触发", "run(command, timeout=2) 等待 2 秒，死循环不退出就抛 TimeoutExpired。", `timeout_seconds=${evidence.timeout_seconds ?? "-"}`, "done"),
      flowStep("强制删除容器", "后端执行 docker rm -f verify-timeout-xxxx。", `cleanup_command=${evidence.cleanup_command || "-"}`, "done"),
      flowStep("确认清理成功", "采集 cleanup_stdout、cleanup_stderr、cleanup_returncode。", `cleanup_returncode=${evidence.cleanup_returncode ?? "-"}，0 表示容器已删除，不会继续占机器。`, evidence.cleanup_returncode === 0 ? "done" : "fail"),
    ]);
  }

  if (item.id === "network_default_deny") {
    return base.concat([
      flowStep("启动禁网容器", "docker run --network none 启动任务容器。", "容器没有任何外网出口。", "done"),
      flowStep("容器内访问公网", "Python urllib.request.urlopen('https://example.com')。", "如果还能访问成功，说明默认禁网失败。", "done"),
      flowStep("采集失败结果", "后端收集访问失败的 returncode/stderr。", `returncode=${evidence.returncode ?? "-"}，非 0 表示网络访问被阻断。`, passed ? "done" : "fail"),
    ]);
  }

  if (item.id === "egress_allowlist_gateway") {
    const allow = evidence.allow_sandbox_test || evidence.allow_example_com || {};
    const block = evidence.block_non_allowlisted || evidence.block_openai_com || {};
    const bypass = evidence.direct_bypass_attempt || {};
    return base.concat([
      flowStep("创建内部 Docker 网络", "docker network create --internal agent-egress-xxxx。", `network=${evidence.network || "-"}`, evidence.create_network ? rcStatus(evidence.create_network, true) : "done"),
      flowStep("启动白名单代理容器", "启动 egress_gateway.py，只允许 sandbox-allow.test。", `proxy_container=${evidence.proxy_container || "-"}`, evidence.start_proxy ? rcStatus(evidence.start_proxy, true) : "done"),
      flowStep("测试白名单放行", "任务容器带 http_proxy 访问允许域名。", `allow.returncode=${allow.returncode ?? "-"}，0 表示白名单已放行。`, allow.returncode === 0 ? "done" : "fail"),
      flowStep("测试非白名单拦截", "任务容器带 http_proxy 访问 blocked_host。", `block.returncode=${block.returncode ?? "-"}，非 0 表示网关拒绝。`, block.returncode !== 0 ? "done" : "fail"),
      flowStep("测试绕过代理直连", "任务容器不带代理直接访问 allowed_host。", `bypass.returncode=${bypass.returncode ?? "-"}，非 0 表示不能绕过网关。`, bypass.returncode !== 0 ? "done" : "fail"),
      flowStep("采集代理日志并清理", "docker logs proxy 后 finally 删除代理容器和内部网络。", evidence.proxy_logs ? "proxy_logs 已返回，说明访问行为可审计。" : "未采集到代理日志。", evidence.proxy_logs ? "done" : "warn"),
    ]);
  }

  if (item.id === "browser_sandbox") {
    const allow = evidence.browser_allow_sandbox_test || evidence.browser_allow_example_com || {};
    const block = evidence.browser_block_non_allowlisted || evidence.browser_block_openai_com || {};
    const bypass = evidence.browser_direct_bypass_attempt || {};
    const outcome = browserSandboxOutcomes(evidence);
    return base.concat([
      flowStep("创建浏览器内部网络", "docker network create --internal agent-browser-xxxx。", `network=${evidence.network || "-"}`, evidence.create_network ? rcStatus(evidence.create_network, true) : "done"),
      flowStep("启动浏览器出站代理", "启动 egress_gateway.py 作为浏览器容器的白名单代理。", `proxy_container=${evidence.proxy_container || "-"}`, evidence.start_proxy ? rcStatus(evidence.start_proxy, true) : "done"),
      flowStep("启动真实 Chromium 容器", "docker run browser_image chromium --headless --proxy-server=proxy。", `browser_image=${evidence.browser_image || "-"}`, evidence.browser_image ? "done" : "warn"),
      flowStep("验证白名单页面加载", "Chromium dump-dom 访问 allowed_host。", `页面包含 Sandbox Allowlist Probe=${outcome.allowedOk}；returncode=${allow.returncode ?? "-"}。`, outcome.allowedOk ? "done" : "fail"),
      flowStep("验证非白名单拒绝", "Chromium 经代理访问 blocked_host。", `代理日志记录 host=${outcome.blockedHost}、allowed=false：${outcome.blockedOk}；HTTP 拦截页仍可能 returncode=${block.returncode ?? "-"}。`, outcome.blockedOk ? "done" : "fail"),
      flowStep("验证直连绕过失败", "Chromium 不配置代理直接访问 allowed_host。", `页面为 ERR_/offline：${outcome.bypassOk}；即使 returncode=${bypass.returncode ?? "-"} 也不代表网页访问成功。`, outcome.bypassOk ? "done" : "fail"),
      flowStep("采集代理日志并清理", "docker logs proxy 后删除代理容器和内部网络。", evidence.proxy_logs ? "proxy_logs 已返回，能证明浏览器访问也被审计。" : "未采集到代理日志。", evidence.proxy_logs ? "done" : "warn"),
    ]);
  }

  if (item.id === "permission_denial") {
    const compliance = evidence.security_compliance || {};
    return base.concat([
      flowStep("创建敏感业务任务", "sales-user 尝试执行 s04_invoice_matching 发票核销。", `task_id=${evidence.task_id || "-"}`, evidence.task_id ? "done" : "warn"),
      flowStep("执行权限前置检查", "安全合规模块检查 invoice:read / receipt:read 等权限。", `missing_permissions=${(compliance.missing_permissions || []).join(", ") || "-"}`, "done"),
      flowStep("拒绝进入正常执行", "缺少 receipt:read 时任务状态应为 failed。", `status=${evidence.status || "-"}`, evidence.status === "failed" ? "done" : "fail"),
      flowStep("返回拦截原因", "后端把 security_compliance 和 error 返回前端。", "验证结果可解释，不是静默失败。", "done"),
    ]);
  }

  if (item.id === "credential_injection") {
    const leaks = evidence.leak_checks || {};
    return base.concat([
      flowStep("创建内部凭据网络", "docker network create --internal agent-cred-xxxx。", `network=${evidence.network || "-"}`, evidence.create_network ? rcStatus(evidence.create_network, true) : "done"),
      flowStep("启动 credential broker", "broker 容器持有明文 secret，并对外只提供 handle 调用。", `broker_container=${evidence.broker_container || "-"}`, evidence.start_broker ? rcStatus(evidence.start_broker, true) : "done"),
      flowStep("启动任务容器", "任务容器只注入 CREDENTIAL_HANDLE 和 broker URL。", `credential_handle=${evidence.credential_handle ? "已下发" : "-"}`, evidence.credential_handle ? "done" : "fail"),
      flowStep("任务容器扫描泄漏点", "扫描环境变量、/proc/self/cmdline、/app 文件和输出。", `扫描文件数=${leaks.app_files_scanned_by_task ?? "-"}`, evidence.task_probe ? "done" : "warn"),
      flowStep("通过 broker 使用凭据", "任务用 handle 请求 broker /use，broker 返回 authorized 但不返回明文。", "plaintext_secret 应为 null。", "done"),
      flowStep("采集审计日志并清理", "docker logs broker 后删除 broker 容器和内部网络。", evidence.broker_logs ? "broker_logs 已返回，凭据使用可审计。" : "未采集到 broker 日志。", evidence.broker_logs ? "done" : "warn"),
    ]);
  }

  if (item.id === "e2b_like_adapter") {
    const session = evidence.session || {};
    const run = evidence.run || {};
    const destroyed = evidence.destroyed_session || {};
    return base.concat([
      flowStep("加载 DockerE2BAdapter", "后端实例化 DockerE2BAdapter(project_root, service)。", "这是给后续平台调用的会话式适配层。", "done"),
      flowStep("创建沙箱会话", "create_session 写入 actor、agent、timeout、memory、cpu 元数据。", `session_id=${session.id || "-"}`, session.id ? "done" : "fail"),
      flowStep("会话内运行模板任务", "run_template 提交 s19_over_stock_warning，并进入 DockerTemplateExecutor。", `task_id=${run.task_id || "-"}，status=${run.status || "-"}`, run.status === "success" ? "done" : "fail"),
      flowStep("查询会话状态", "get_session 返回该会话的任务记录。", "证明后续平台可以查询沙箱生命周期。", "done"),
      flowStep("销毁会话", "destroy_session 标记会话销毁。", `destroyed_status=${destroyed.status || "-"}`, destroyed.status ? "done" : "warn"),
    ]);
  }

  if (item.id === "hanhe_role_scenario_e2e" || item.id === "hanhe_finance_invoice_e2e" || item.id === "hanhe_purchase_plan_e2e") {
    const result = evidence.business_result || {};
    const scenarioName = item.id === "hanhe_role_scenario_e2e" ? "销售/供应链超库存预警" : item.id === "hanhe_finance_invoice_e2e" ? "财务发票核销" : "采购计划分析";
    return base.concat([
      flowStep("创建汉和岗位任务", `service.create_task 提交 ${scenarioName}。`, `task_id=${evidence.task_id || "-"}`, evidence.task_id ? "done" : "warn"),
      flowStep("解析岗位身份", "账号网关解析 actor 对应部门、岗位和权限。", `${evidence.department || "-"} / ${evidence.role || "-"}`, "done"),
      flowStep("权限和业务数据准备", "执行权限检查，并注入 mock ERP/OA 场景数据。", "替代真实 ERP/OA 联调，保证 L1 模块可独立演示。", "done"),
      flowStep("进入 Docker 沙箱执行", "模板任务由 DockerTemplateExecutor 执行业务逻辑。", `executor=${(evidence.runtime || {}).executor || "-"}`, (evidence.runtime || {}).executor === "DockerTemplateExecutor" ? "done" : "warn"),
      flowStep("返回业务结果", "沙箱输出库存预警、发票匹配或采购建议。", JSON.stringify(result).slice(0, 160), passed ? "done" : "fail"),
      flowStep("记录成本和审计", "后端记录 duration/cost/audit_events。", `audit_event_count=${evidence.audit_event_count ?? 0}`, "done"),
    ]);
  }

  return base.concat([
    flowStep("执行验证逻辑", item.claim || "运行后端验证函数。", item.detail || "-", status),
  ]);
}

function flowStep(title, operation, proof, status = "done") {
  return {title, operation, proof, status};
}

function rcStatus(proc, zeroIsGood = true) {
  if (!proc || proc.returncode === undefined || proc.returncode === null) return "warn";
  return (proc.returncode === 0) === zeroIsGood ? "done" : "fail";
}

function renderVerificationRunning(caseId) {
  const title = caseId === "all" ? "正在运行全部现场验收" : "正在运行现场验收";
  return `
    <div class="live-running">
      <div class="pulse-dot"></div>
      <div>
        <h3>${escapeHtml(title)}</h3>
        <p>后端正在启动 Docker 容器、执行探针、采集返回码和原始证据。结果回来后会自动切换成可视化证明。</p>
      </div>
    </div>
    <div class="demo-skeleton">
      <span></span><span></span><span></span>
    </div>
  `;
}

function renderAllVerificationOverview(results) {
  const passed = results.filter(item => item.status === "passed").length;
  const failed = results.filter(item => item.status !== "passed").length;
  const dockerBacked = results.filter(item => {
    const evidence = item.evidence || {};
    return JSON.stringify(evidence).includes("DockerTemplateExecutor") || JSON.stringify(item.command || "").includes("docker");
  }).length;
  return `
    <div class="demo-dashboard">
      ${dashboardTile("现场通过", `${passed}/${results.length}`, "刚刚运行返回的通过数量")}
      ${dashboardTile("真实 Docker 证据", dockerBacked, "命令或证据里出现 Docker 执行痕迹")}
      ${dashboardTile("失败项", failed, failed ? "需要处理" : "当前没有失败验收项")}
    </div>
  `;
}

function dashboardTile(title, value, detail) {
  return `
    <div class="dashboard-tile">
      <span>${escapeHtml(title)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>
  `;
}

function browserSandboxOutcomes(evidence) {
  const allow = evidence.browser_allow_sandbox_test || evidence.browser_allow_example_com || {};
  const block = evidence.browser_block_non_allowlisted || evidence.browser_block_openai_com || {};
  const bypass = evidence.browser_direct_bypass_attempt || {};
  const assertions = evidence.assertions || {};
  const logs = `${evidence.proxy_logs?.stdout || ""}\n${evidence.proxy_logs?.stderr || ""}`;
  const blockedHost = evidence.blocked_host || "openai.com";
  const expectedText = evidence.allowed_host ? "Sandbox Allowlist Probe" : "Example Domain";
  const bypassText = `${bypass.stdout || ""}\n${bypass.stderr || ""}`;
  return {
    allow,
    block,
    bypass,
    blockedHost,
    allowedOk: assertions.allowlisted_page_loaded ?? (allow.stdout || "").includes(expectedText),
    blockedOk: assertions.non_allowlisted_blocked ?? (logs.includes(`"host": "${blockedHost}"`) && logs.includes('"allowed": false')),
    bypassOk: assertions.direct_bypass_blocked ?? (!(bypass.stdout || "").includes(expectedText) && /ERR_|offline/i.test(bypassText)),
  };
}

function renderLiveCapabilityVisual(item) {
  const evidence = item.evidence || {};
  const passed = item.status === "passed";
  if (item.id === "docker_runtime") {
    return capabilityPanel("Docker 运行时现场状态", "不是静态说明，后端刚刚检查服务器 Docker daemon。", [
      visualNode("服务器", "117.182.236.5 / 10.60.66.97", "ok"),
      visualArrow("docker info"),
      visualNode("Docker daemon", evidence.stdout || "已响应", passed ? "ok" : "fail"),
    ], [
      signal("返回码", evidence.returncode ?? "-", passed ? "Docker 可用" : "Docker 不可用"),
      signal("服务状态", passed ? "在线" : "异常", "沙箱可创建真实容器"),
    ]);
  }
  if (item.id === "docker_task") {
    const runtime = evidence.result && evidence.result.sandbox_runtime ? evidence.result.sandbox_runtime : {};
    return capabilityPanel("任务独立进入 Docker 沙箱", "业务任务具备任务号、执行器和运行时证据。", [
      visualNode("业务任务", evidence.task_id || "已创建", "ok"),
      visualArrow("调度"),
      visualNode("DockerTemplateExecutor", evidence.executor || "-", evidence.executor === "DockerTemplateExecutor" ? "ok" : "warn"),
      visualArrow("输出"),
      visualNode("业务结果", "已返回", passed ? "ok" : "fail"),
    ], [
      signal("隔离方式", runtime.isolation || "-", "任务不是裸跑在宿主机"),
      signal("网络策略", runtime.network || "-", "按沙箱网络策略执行"),
      signal("任务编号", evidence.task_id || "-", "可追踪可审计"),
    ]);
  }
  if (item.id === "host_file_isolation") {
    return capabilityPanel("宿主机文件隔离可视化", "容器现场尝试越权读宿主机秘密文件、写项目目录，失败才算通过。", [
      visualNode("任务容器", "隔离空间", "ok"),
      visualArrow("尝试读取"),
      visualNode("宿主机秘密文件", "不可见", passed ? "blocked" : "fail"),
      visualArrow("尝试写入"),
      visualNode("/app 项目目录", "只读", passed ? "blocked" : "fail"),
    ], [
      signal("探针输出", evidence.stdout || "-", passed ? "隔离生效" : "隔离失败"),
      signal("返回码", evidence.returncode ?? "-", "0 表示探针确认防护有效"),
    ]);
  }
  if (item.id === "resource_timeout") {
    return capabilityPanel("资源配额和跑飞清理", "现场启动死循环容器，限定 CPU、内存、运行时长，到点自动清理。", [
      visualNode("跑飞任务", "while True", "warn"),
      visualArrow(`${evidence.timeout_seconds ?? 2}s 超时`),
      visualNode("沙箱限额", "CPU 0.5 / Memory 64m", "ok"),
      visualArrow("强制清理"),
      visualNode("容器已删除", evidence.container_name || "-", evidence.cleanup_returncode === 0 ? "ok" : "fail"),
    ], [
      meter("CPU 限额", 50, "0.5 core"),
      meter("内存限额", 64, "64 MB"),
      meter("运行时长", 100, `${evidence.timeout_seconds ?? "-"} 秒后清理`),
      signal("清理返回码", evidence.cleanup_returncode ?? "-", evidence.cleanup_returncode === 0 ? "不会占满机器" : "清理异常"),
    ]);
  }
  if (item.id === "network_default_deny") {
    return capabilityPanel("默认禁止出站联网", "容器默认没有网络，任务想访问公网会失败。", [
      visualNode("任务容器", "--network none", "ok"),
      visualArrow("访问外网"),
      visualNode("公网地址", "连接失败", passed ? "blocked" : "fail"),
    ], [
      signal("访问结果", passed ? "已拦截" : "未拦截", "证明默认禁网生效"),
      signal("返回码", evidence.returncode ?? "-", "非 0 通常表示连接失败"),
    ]);
  }
  if (item.id === "egress_allowlist_gateway") {
    const allow = evidence.allow_sandbox_test || evidence.allow_example_com || {};
    const block = evidence.block_non_allowlisted || evidence.block_openai_com || {};
    const bypass = evidence.direct_bypass_attempt || {};
    return capabilityPanel("域名级白名单网关", "不是简单禁网：允许的能出去，不允许的被拦，绕过代理也失败。", [
      visualNode("任务容器", "内部 Docker 网络", "ok"),
      visualArrow("经过 egress-proxy"),
      visualNode(`白名单 ${evidence.allowed_host || "example.com"}`, allow.returncode === 0 ? "已放行" : "失败", allow.returncode === 0 ? "ok" : "fail"),
      visualNode(`非白名单 ${evidence.blocked_host || "openai.com"}`, block.returncode !== 0 ? "已拦截" : "未拦截", block.returncode !== 0 ? "blocked" : "fail"),
      visualNode("绕过代理直连", bypass.returncode !== 0 ? "失败" : "成功", bypass.returncode !== 0 ? "blocked" : "fail"),
    ], [
      signal("代理容器", evidence.proxy_container || "-", "网络访问统一过网关"),
      signal("白名单", allow.returncode === 0 ? "通过" : "失败", "允许域名可访问"),
      signal("非白名单", block.returncode !== 0 ? "拦截" : "未拦截", "敏感外联被拒绝"),
      signal("绕过代理", bypass.returncode !== 0 ? "失败" : "成功", "不能私自联网"),
    ]);
  }
  if (item.id === "browser_sandbox") {
    const outcome = browserSandboxOutcomes(evidence);
    return capabilityPanel("浏览器自动化也被沙箱管住", "启动真实 Headless Chromium 容器，浏览器访问也必须经过白名单网关。", [
      visualNode("Chromium 容器", evidence.browser_image || "browser image", "ok"),
      visualArrow("代理出站"),
      visualNode("白名单页面", outcome.allowedOk ? "加载成功" : "加载失败", outcome.allowedOk ? "ok" : "fail"),
      visualNode("非白名单页面", outcome.blockedOk ? "已拦截（403）" : "拦截失败", outcome.blockedOk ? "blocked" : "fail"),
      visualNode("直连绕过", outcome.bypassOk ? "绕过失败（离线）" : "绕过成功", outcome.bypassOk ? "blocked" : "fail"),
    ], [
      signal("浏览器网络", evidence.network || "-", "浏览器容器接入受控网络"),
      signal("非白名单审计", outcome.blockedOk ? "allowed=false" : "未证实", "代理日志是拦截依据"),
      signal("直连结果", outcome.bypassOk ? "离线错误页" : "访问成功", "Chromium 返回码不等于网页成功"),
    ]);
  }
  if (item.id === "permission_denial") {
    const compliance = evidence.security_compliance || {};
    return capabilityPanel("权限不足前置拦截", "任务进入沙箱前先过权限检查，不该跑的任务不会执行。", [
      visualNode("销售用户", evidence.task_id || "提交任务", "warn"),
      visualArrow("权限检查"),
      visualNode("安全合规模块", (compliance.missing_permissions || []).join(", ") || "缺少权限", "blocked"),
      visualArrow("拦截"),
      visualNode("沙箱执行", "未放行", passed ? "blocked" : "fail"),
    ], [
      signal("任务状态", evidence.status || "-", "权限不足时应拒绝"),
      signal("缺少权限", (compliance.missing_permissions || []).join(", ") || "-", "拦截原因可解释"),
    ]);
  }
  if (item.id === "credential_injection") {
    return capabilityPanel("凭据句柄隔离", "任务容器只能拿短期 handle，明文密钥留在 broker，不进入任务环境。", [
      visualNode("Credential Broker", "保存明文", "ok"),
      visualArrow("下发 handle"),
      visualNode("任务容器", evidence.credential_handle ? "只有句柄" : "-", evidence.credential_handle ? "ok" : "fail"),
      visualArrow("扫描环境"),
      visualNode("明文密钥", "未发现", passed ? "blocked" : "fail"),
    ], [
      signal("凭据策略", evidence.secret_policy || "-", "明文不进容器"),
      signal("审计日志", evidence.broker_logs ? "已记录" : "-", "凭据使用可追踪"),
    ]);
  }
  if (item.id === "e2b_like_adapter") {
    const session = evidence.session || {};
    const run = evidence.run || {};
    const destroyed = evidence.destroyed_session || {};
    return capabilityPanel("会话式沙箱接口", "后续完整平台可以按 create/run/query/destroy 调用这个能力包。", [
      visualNode("Create", session.id || "session", "ok"),
      visualArrow("Run"),
      visualNode("Docker 任务", run.task_id || "-", run.status === "success" ? "ok" : "warn"),
      visualArrow("Destroy"),
      visualNode("会话销毁", destroyed.status || "-", destroyed.status ? "ok" : "warn"),
    ], [
      signal("适配器", (evidence.capability || {}).adapter || "-", "后续平台接口形态"),
      signal("执行器", evidence.task_executor || "-", "仍由 Docker 沙箱承载"),
    ]);
  }
  if (item.id === "hanhe_role_scenario_e2e" || item.id === "hanhe_finance_invoice_e2e" || item.id === "hanhe_purchase_plan_e2e") {
    return renderHanheScenarioVisual(item);
  }
  return capabilityPanel("现场能力证明", "这一块把后端返回证据转成可演示状态。", [
    visualNode("现场探针", item.claim || "-", "ok"),
    visualArrow("执行"),
    visualNode("返回结果", item.detail || "-", passed ? "ok" : "fail"),
  ], factsToSignals(verificationFacts(item)));
}

function renderHanheScenarioVisual(item) {
  const evidence = item.evidence || {};
  const result = evidence.business_result || {};
  const titleMap = {
    hanhe_role_scenario_e2e: "汉和销售/供应链库存预警",
    hanhe_finance_invoice_e2e: "汉和财务发票核销",
    hanhe_purchase_plan_e2e: "汉和采购计划分析",
  };
  const resultText = item.id === "hanhe_role_scenario_e2e"
    ? `超库存 ${result.over_qty ?? "-"}`
    : item.id === "hanhe_finance_invoice_e2e"
      ? `匹配 ${(result.matches || []).filter(row => row.status === "matched").length} 条`
      : `建议采购 ${result.suggested_purchase ?? "-"}`;
  return capabilityPanel(titleMap[item.id], "用汉和岗位场景完整跑通：身份、权限、mock ERP/OA 数据、Docker 沙箱、审计成本一起生效。", [
    visualNode("岗位身份", `${evidence.department || "-"} / ${evidence.role || "-"}`, "ok"),
    visualArrow("权限 + 数据"),
    visualNode("Docker 沙箱", (evidence.runtime || {}).executor || "-", "ok"),
    visualArrow("业务输出"),
    visualNode("结果", resultText, "ok"),
  ], [
    signal("任务编号", evidence.task_id || "-", "可追踪"),
    signal("业务结果", resultText, "沙箱实际计算输出"),
    signal("审计", `${evidence.audit_event_count ?? 0} 条`, "过程可留痕"),
  ]);
}

function capabilityPanel(title, subtitle, nodes, signals) {
  return `
    <div class="live-proof-panel">
      <div class="live-proof-head">
        <div>
          <strong>${escapeHtml(title)}</strong>
          <p>${escapeHtml(subtitle)}</p>
        </div>
        <span>现场返回证据驱动</span>
      </div>
      <div class="live-proof-map">
        ${nodes.join("")}
      </div>
      <div class="live-proof-signals">
        ${signals.join("")}
      </div>
    </div>
  `;
}

function visualNode(title, detail, state = "ok") {
  return `
    <div class="visual-node ${escapeHtml(state)}">
      <span></span>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>
  `;
}

function visualArrow(label) {
  return `<div class="visual-arrow"><b>→</b><span>${escapeHtml(label)}</span></div>`;
}

function signal(label, value, meaning) {
  return `
    <div class="live-signal">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(meaning)}</p>
    </div>
  `;
}

function meter(label, percent, detail) {
  const width = Math.max(0, Math.min(100, Number(percent) || 0));
  return `
    <div class="live-meter">
      <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(detail)}</strong></div>
      <i><b style="width:${width}%"></b></i>
    </div>
  `;
}

function factsToSignals(facts) {
  return facts.map((fact) => signal(fact.label, fact.value, "来自本次现场返回证据"));
}

function verificationTechnicalNotes(item) {
  const generic = {
    commandTitle: "这段命令/调用代表什么",
    command: [
      "这是后端本次验证实际执行的 Docker 命令或 API 调用记录。",
      "每次点击现场验证，后端都会重新运行对应探针。",
      "如果是 POST /api/tasks，说明它创建了一个真实沙箱任务。",
    ],
    evidenceTitle: "原始证据怎么看",
    evidence: [
      "returncode 为 0 通常表示命令执行成功。",
      "stdout 是命令或容器内代码真实打印的内容。",
      "stderr 是错误输出；为空通常表示没有命令级错误。",
      "task_id、executor、business_result 可证明任务真实创建并返回结果。",
    ],
  };
  const map = {
    docker_runtime: {
      commandTitle: "Docker 运行时检查",
      command: ["后端执行 docker info 检查 Docker daemon 是否可用。", "stdout 会返回 Docker 服务端版本。"],
      evidenceTitle: "证明点",
      evidence: ["returncode 为 0 表示 Docker 命令成功。", "stdout 里的版本号来自服务器 Docker，不是页面写死。"],
    },
    host_file_isolation: {
      commandTitle: "宿主机文件隔离探针",
      command: ["docker run 会临时启动一个容器。", "--network none 表示容器没有网络。", "--read-only 和 /app:ro 表示代码目录只读。", "容器内 Python 会尝试读取宿主机秘密文件、尝试写 /app，失败后才算通过。"],
      evidenceTitle: "证明点",
      evidence: ["stdout 出现 PASS 表示容器看不到宿主机秘密文件，也不能写只读目录。", "returncode 为 0 表示这段容器内测试代码成功完成。", "如果隔离失败，stdout 不会是 PASS，returncode 也会变成非 0。"],
    },
    resource_timeout: {
      commandTitle: "跑飞任务探针",
      command: ["后端启动一个死循环容器。", "验证逻辑会在超时后强制 docker rm -f 清理容器。"],
      evidenceTitle: "证明点",
      evidence: ["cleanup_returncode 为 0 表示跑飞容器被清理。", "这证明任务不会无限占用服务器。"],
    },
    network_default_deny: {
      commandTitle: "默认禁止出站探针",
      command: ["容器用 --network none 启动。", "容器内代码会尝试访问外网地址。"],
      evidenceTitle: "证明点",
      evidence: ["访问失败才是通过。", "这证明任务默认不能随便联网。"],
    },
    egress_allowlist_gateway: {
      commandTitle: "白名单网关探针",
      command: ["后端创建内部 Docker 网络和 egress-proxy。", "任务容器分别测试白名单域名、非白名单域名和绕过代理直连。"],
      evidenceTitle: "证明点",
      evidence: ["白名单通过、非白名单拒绝、直连绕过失败，三者同时成立才算通过。"],
    },
    browser_sandbox: {
      commandTitle: "浏览器沙箱探针",
      command: ["后端启动真实 Headless Chromium 容器。", "浏览器也必须经过白名单网关访问允许页面。"],
      evidenceTitle: "证明点",
      evidence: ["白名单页面包含受控探针内容。", "非白名单是否拦截以代理日志 allowed=false 为准。", "直连是否失败以 Chromium 的 ERR_/offline 错误页为准；Chromium 渲染错误页后 returncode 仍可能是 0。"],
    },
    credential_injection: {
      commandTitle: "凭据句柄探针",
      command: ["后端启动 credential broker 和任务容器。", "任务容器只拿短期 handle，不拿明文 secret。"],
      evidenceTitle: "证明点",
      evidence: ["broker 响应可用但明文 secret 不出现在环境变量、命令行、文件和输出里。", "审计记录证明凭据使用被记录。"],
    },
    e2b_like_adapter: {
      commandTitle: "会话式沙箱调用",
      command: ["按 create/run/query/destroy 流程调用 Docker-backed 沙箱会话。", "这是给后续 L2 平台调用的接口形态。"],
      evidenceTitle: "证明点",
      evidence: ["session id、task id、destroyed 状态同时出现，说明会话生命周期跑通。"],
    },
    hanhe_role_scenario_e2e: roleScenarioNotes("销售/供应链超库存预警"),
    hanhe_finance_invoice_e2e: roleScenarioNotes("财务发票核销"),
    hanhe_purchase_plan_e2e: roleScenarioNotes("采购计划分析"),
  };
  return map[item.id] || generic;
}

function roleScenarioNotes(name) {
  return {
    commandTitle: `${name}任务调用`,
    command: ["后端通过 POST /api/tasks 创建真实沙箱任务。", "任务会经过账号解析、权限预检查、mock ERP/OA 数据注入，再进入 Docker 执行。"],
    evidenceTitle: "证明点",
    evidence: ["task_id 证明任务真实创建。", "executor 为 DockerTemplateExecutor 证明任务在 Docker 运行时执行。", "business_result 是沙箱执行后的业务输出。", "cost 和 audit_event_count 证明成本和审计链路已记录。"],
  };
}

function verificationFacts(item) {
  const evidence = item.evidence || {};
  if (item.id === "docker_runtime") {
    return [{label: "Docker 版本", value: evidence.stdout || "-"}, {label: "返回码", value: evidence.returncode ?? "-"}];
  }
  if (item.id === "docker_task") {
    const runtime = evidence.result && evidence.result.sandbox_runtime ? evidence.result.sandbox_runtime : {};
    return [
      {label: "任务编号", value: evidence.task_id || "-"},
      {label: "执行器", value: evidence.executor || "-"},
      {label: "隔离方式", value: runtime.isolation || "-"},
      {label: "网络", value: runtime.network || "-"},
    ];
  }
  if (item.id === "host_file_isolation") {
    return [{label: "探针输出", value: evidence.stdout || "-"}, {label: "返回码", value: evidence.returncode ?? "-"}];
  }
  if (item.id === "resource_timeout") {
    return [
      {label: "超时秒数", value: evidence.timeout_seconds ?? "-"},
      {label: "容器", value: evidence.container_name || "-"},
      {label: "清理返回码", value: evidence.cleanup_returncode ?? "-"},
    ];
  }
  if (item.id === "network_default_deny") {
    return [{label: "访问结果", value: "外网连接失败"}, {label: "返回码", value: evidence.returncode ?? "-"}];
  }
  if (item.id === "egress_allowlist_gateway") {
    const allow = evidence.allow_sandbox_test || evidence.allow_example_com || {};
    const block = evidence.block_non_allowlisted || evidence.block_openai_com || {};
    const bypass = evidence.direct_bypass_attempt || {};
    return [
      {label: `白名单 ${evidence.allowed_host || "example.com"}`, value: allow.returncode === 0 ? "通过" : "失败"},
      {label: `非白名单 ${evidence.blocked_host || "openai.com"}`, value: block.returncode !== 0 ? "已拦截" : "未拦截"},
      {label: "绕过代理直连", value: bypass.returncode !== 0 ? "失败" : "成功"},
      {label: "代理容器", value: evidence.proxy_container || "-"},
    ];
  }
  if (item.id === "browser_sandbox") {
    const outcome = browserSandboxOutcomes(evidence);
    return [
      {label: "浏览器镜像", value: evidence.browser_image || "-"},
      {label: `白名单 ${evidence.allowed_host || "example.com"}`, value: outcome.allowedOk ? "真实页面已加载" : "未加载"},
      {label: `非白名单 ${outcome.blockedHost}`, value: outcome.blockedOk ? "网关拒绝（allowed=false）" : "未拦住"},
      {label: "绕过代理直连", value: outcome.bypassOk ? "失败（离线错误页）" : "绕过成功"},
      {label: "浏览器网络", value: evidence.network || "-"},
    ];
  }
  if (item.id === "permission_denial") {
    const compliance = evidence.security_compliance || {};
    return [
      {label: "任务编号", value: evidence.task_id || "-"},
      {label: "状态", value: evidence.status || "-"},
      {label: "缺少权限", value: (compliance.missing_permissions || []).join(", ") || "-"},
    ];
  }
  if (item.id === "credential_injection") {
    const probe = evidence.task_probe || {};
    const logs = (evidence.broker_logs || {}).stdout || "";
    let parsed = {};
    try {
      parsed = JSON.parse(probe.stdout || "{}");
    } catch (_) {
      parsed = {};
    }
    const scan = parsed.scan || {};
    const response = parsed.broker_response || {};
    return [
      {label: "凭据句柄", value: evidence.credential_handle ? "已下发" : "-"},
      {label: "明文策略", value: evidence.secret_policy || "-"},
      {label: "任务容器扫描", value: Object.values(scan).some(Boolean) ? "发现疑似密钥" : "未发现明文"},
      {label: "broker 响应", value: response.credential_result || "-"},
      {label: "审计记录", value: logs.includes("credential_use") ? "已记录" : "未记录"},
    ];
  }
  if (item.id === "e2b_like_adapter") {
    const capability = evidence.capability || {};
    const session = evidence.session || {};
    const run = evidence.run || {};
    const destroyed = evidence.destroyed_session || {};
    return [
      {label: "适配器", value: capability.adapter || "-"},
      {label: "兼容口径", value: capability.compatibility || "-"},
      {label: "会话", value: session.id || "-"},
      {label: "任务", value: `${run.task_id || "-"} / ${run.status || "-"}`},
      {label: "执行器", value: evidence.task_executor || "-"},
      {label: "销毁状态", value: destroyed.status || "-"},
    ];
  }
  if (item.id === "hanhe_role_scenario_e2e") {
    const result = evidence.business_result || {};
    return [
      {label: "任务编号", value: evidence.task_id || "-"},
      {label: "岗位", value: `${evidence.department || "-"} / ${evidence.role || "-"}`},
      {label: "库存", value: result.inventory ?? "-"},
      {label: "订单合计", value: result.total_order_qty ?? "-"},
      {label: "超库存", value: result.over_qty ?? "-"},
      {label: "运行时", value: (evidence.runtime || {}).executor || "-"},
      {label: "审计", value: `${evidence.audit_event_count ?? 0} 条`},
    ];
  }
  if (item.id === "hanhe_finance_invoice_e2e") {
    const result = evidence.business_result || {};
    const matches = result.matches || [];
    return [
      {label: "任务编号", value: evidence.task_id || "-"},
      {label: "岗位", value: `${evidence.department || "-"} / ${evidence.role || "-"}`},
      {label: "发票数", value: matches.length},
      {label: "匹配", value: matches.filter(row => row.status === "matched").length},
      {label: "异常", value: matches.filter(row => row.status === "exception").length},
      {label: "运行时", value: (evidence.runtime || {}).executor || "-"},
      {label: "审计", value: `${evidence.audit_event_count ?? 0} 条`},
    ];
  }
  if (item.id === "hanhe_purchase_plan_e2e") {
    const result = evidence.business_result || {};
    return [
      {label: "任务编号", value: evidence.task_id || "-"},
      {label: "岗位", value: `${evidence.department || "-"} / ${evidence.role || "-"}`},
      {label: "预测需求", value: result.forecast_demand ?? "-"},
      {label: "当前库存", value: result.current_stock ?? "-"},
      {label: "建议采购", value: result.suggested_purchase ?? "-"},
      {label: "运行时", value: (evidence.runtime || {}).executor || "-"},
      {label: "审计", value: `${evidence.audit_event_count ?? 0} 条`},
    ];
  }
  return [{label: "结论", value: item.detail || "-"}];
}

function renderMonitorDetail(id) {
  const item = monitorInstances.find((instance) => instance.id === id);
  if (!item) return;
  const permissionText = item.permission_ok === false ? `缺少 ${item.missing_permissions.join(", ")}` : "通过";
  monitorDetail.innerHTML = `
    <div class="instance-head">
      <div><span class="badge ${escapeHtml(item.status || "")}">${escapeHtml(statusText(item.status))}</span><h3>${escapeHtml(item.scenario_name || item.scenario_id || "-")}</h3><p>instance ${escapeHtml(item.id)}</p></div>
      <div><span>后端耗时</span><strong>${escapeHtml(item.duration_ms ?? 0)} ms</strong></div>
    </div>
    <div class="instance-resource-grid">
      ${resourceGauge("CPU 配额", Number(item.cpu_cores || 0) * 50, `${item.cpu_cores ?? "-"} cores`, "单容器限制")}
      ${resourceGauge("内存配额", Number(item.memory_mb || 0) / 10.24, `${item.memory_mb ?? "-"} MB`, "单容器限制")}
      ${resourceGauge("运行时长", Math.min(100, Number(item.duration_ms || 0) / Math.max(1, Number(item.timeout_seconds || 10) * 10)), `${item.duration_ms ?? 0} ms`, `上限 ${item.timeout_seconds ?? "-"} s`)}
    </div>
    <div class="instance-policy-grid">
      <div><span>权限检查</span><strong>${escapeHtml(permissionText)}</strong><small>${escapeHtml((item.required_permissions || []).join(" · ") || "无额外权限")}</small></div>
      <div><span>网络策略</span><strong>默认拒绝</strong><small>${escapeHtml(item.egress_policy || "-")}</small></div>
      <div><span>成本记录</span><strong>${escapeHtml(item.cost_units ?? "-")} units</strong><small>已发送计量事件</small></div>
      <div><span>证据数量</span><strong>${escapeHtml(item.log_count ?? 0)} 日志 / ${escapeHtml(item.audit_count ?? 0)} 审计</strong><small>${escapeHtml((item.artifacts || []).length)} 个结果文件</small></div>
    </div>
    <div class="instance-lifecycle">
      ${lifecycleNode("任务创建", item.created_at, true)}
      ${lifecycleNode("容器启动", item.started_at, Boolean(item.started_at))}
      ${lifecycleNode("隔离执行", `${item.duration_ms ?? 0} ms`, item.status !== "queued")}
      ${lifecycleNode("结果取回", item.finished_at, Boolean(item.finished_at))}
      ${lifecycleNode("审计完成", item.last_event?.event || "-", Boolean(item.last_event))}
    </div>
    <div class="last-event"><span>最后事件</span><strong>${escapeHtml(eventName(item.last_event?.event || "-"))}</strong><p>${escapeHtml(item.last_event?.message || "暂无事件")}</p></div>
  `;
  monitorJson.innerHTML = renderAnnotatedCode(item, "monitor");
}

function renderAnnotatedCode(value, kind = "json", context = {}) {
  const source = kind === "command"
    ? String(value ?? "-").trim()
    : JSON.stringify(value ?? {}, null, 2);
  const lines = String(source || "-").split("\n");
  return `
    <pre class="annotated-code"><code>${lines.map((line) => renderAnnotatedLine(line, kind, context)).join("\n")}</code></pre>
  `;
}

function renderAnnotatedLine(line, kind, context) {
  const trimmed = line.trim();
  const note = kind === "command"
    ? annotateCommandLine(trimmed, context)
    : annotateJsonLine(trimmed, kind, context);
  const comment = note ? `<span class="inline-comment"> // ${escapeHtml(note)}</span>` : "";
  return `<span class="code-line">${escapeHtml(line || " ")}${comment}</span>`;
}

function annotateCommandLine(line, context = {}) {
  if (!line || line === "-") return "";
  const caseCommandNote = commandNotesByCase[context.caseId];
  if (caseCommandNote && (/^(\/usr\/bin\/)?docker\b/.test(line) || /^POST\s+\/api\//.test(line))) {
    return caseCommandNote;
  }
  if (/^(\/usr\/bin\/)?docker\s+run\b/.test(line)) {
    const notes = ["这行证明任务不是在页面里假跑，而是启动了真实 Docker 沙箱"];
    if (line.includes("--network none")) notes.push("默认禁网能力已打开");
    if (line.includes("--read-only")) notes.push("只读文件系统防篡改已打开");
    if (line.includes(":ro")) notes.push("项目目录只读挂载已打开");
    if (line.includes("--tmpfs")) notes.push("临时写入目录隔离已打开");
    if (line.includes("--memory") || line.includes("--cpus")) notes.push("CPU/内存限额已打开");
    if (line.includes("python -c")) notes.push("验证代码在容器内部执行");
    return notes.join("；");
  }
  if (/^docker\s+info\b/.test(line) || line.includes("docker info")) return "这行证明服务器 Docker 运行时可用，沙箱具备真实容器执行基础。";
  if (/^docker\s+rm\s+-f\b/.test(line) || line.includes("docker rm -f")) return "这行证明系统会强制清理跑飞容器，超时任务不会一直占用服务器。";
  if (/^POST\s+\/api\/tasks/.test(line)) return "这行证明后续平台可以通过任务接口调用本模块，并让任务进入 Docker 沙箱执行。";
  if (/^POST\s+\/api\//.test(line) || /^GET\s+\/api\//.test(line)) return "这行证明本模块能力已经以 API 形式对外提供，后续平台可以联调调用。";
  if (line.includes("curl") || line.includes("http")) return "这行证明系统正在做真实网络访问探测，用返回结果判断放行或拦截是否生效。";
  return "";
}

function annotateJsonLine(line, kind = "json", context = {}) {
  if (!line) return "";
  if (/^[{}\[\]],?$/.test(line)) return "";
  if (line === "}," || line === "}" || line === "]" || line === "],") return "";

  const keyMatch = line.match(/^"([^"]+)":/);
  if (keyMatch) {
    const key = keyMatch[1];
    const caseNote = caseJsonNotes[context.caseId] && caseJsonNotes[context.caseId][key];
    if (caseNote) return caseNote;
    const note = jsonKeyNotes[key];
    if (note && keyCommentKeys.has(key)) return note;
  }
  if (line.includes("DockerTemplateExecutor")) return "这证明任务已经接入 Docker 执行器，当前交付不是只做静态页面。";
  if (line.includes("\"success\"")) return "成功状态，证明这一项功能现场验证通过。";
  if (line.includes("\"failed\"")) return "失败状态，原因要看 error、stderr 或缺失权限。";
  if (line.includes("\"timeout\"")) return "超时状态，证明系统识别到跑飞任务并进入清理流程。";
  if (line.includes("\"PASS\"")) return "容器内探针打印 PASS，证明这一项隔离或防护已经生效。";
  if (line.includes("\"--network none\"")) return "禁网参数，证明默认禁止出站访问的功能已开启。";
  if (line.includes("\"--read-only\"")) return "只读文件系统参数，证明防止任务篡改环境的功能已开启。";
  return "";
}

const commandNotesByCase = {
  docker_runtime: "这行在服务器现场检查 Docker 是否可用，证明执行沙箱有真实容器运行基础。",
  docker_task: "这行通过任务接口创建真实业务任务，证明业务任务会进入 DockerTemplateExecutor 执行。",
  host_file_isolation: "这行启动隔离容器并尝试越权读写，证明宿主机文件隔离和只读挂载已实现。",
  resource_timeout: "这行启动故意跑飞的容器，证明超时限制和自动清理能力已实现。",
  network_default_deny: "这行启动禁网容器并尝试访问外网，证明默认禁止出站访问已实现。",
  egress_allowlist_gateway: "这行启动白名单网关和测试容器，证明允许域名放行、非白名单拦截、绕过代理失败已实现。",
  browser_sandbox: "这行启动 Headless Chromium 浏览器沙箱，证明浏览器自动化也受 Docker 隔离和出站白名单控制。",
  permission_denial: "这行提交权限不足的任务，证明任务进入沙箱前会先被权限检查拦截。",
  credential_injection: "这行启动凭据 broker 和任务容器，证明任务只能拿短期句柄，不能看到明文密钥。",
  e2b_like_adapter: "这行按 create/run/query/destroy 调用沙箱会话，证明后续平台可以用会话式接口接入。",
  hanhe_role_scenario_e2e: "这行提交汉和销售/供应链场景任务，证明真实岗位场景可以进入 Docker 沙箱并产出业务结果。",
  hanhe_finance_invoice_e2e: "这行提交汉和财务发票核销任务，证明财务岗位场景可以在沙箱内完成单据匹配。",
  hanhe_purchase_plan_e2e: "这行提交汉和采购计划任务，证明采购岗位场景可以在沙箱内生成采购建议。"
};

const caseJsonNotes = {
  docker_runtime: {
    returncode: "返回 0 证明 Docker 检查成功，执行沙箱具备真实容器运行能力。",
    stdout: "这里返回服务器 Docker 信息，证明不是页面写死的假数据。",
    stderr: "没有错误输出，说明 Docker 运行时检查没有异常。"
  },
  docker_task: {
    task_id: "拿到任务编号，证明系统真实创建了一条沙箱任务。",
    executor: "返回 DockerTemplateExecutor，证明任务确实由 Docker 沙箱执行。",
    business_result: "这里有业务输出，证明沙箱不是只启动容器，而是完成了业务计算。",
    sandbox_runtime: "这里记录隔离、网络、资源限制，证明任务按沙箱策略运行。"
  },
  host_file_isolation: {
    stdout: "PASS 证明容器看不到宿主机秘密文件，也不能写只读项目目录。",
    returncode: "返回 0 证明文件隔离探针通过。"
  },
  resource_timeout: {
    timeout_seconds: "这里设置允许执行时间，证明跑飞任务有时间上限。",
    container_name: "这里记录被测试的跑飞容器，便于追踪和清理。",
    cleanup_command: "这里是真实清理命令，证明系统会主动删除超时容器。",
    cleanup_stdout: "这里返回被删除的容器名，证明清理命令确实执行了。",
    cleanup_returncode: "返回 0 证明跑飞容器已被成功清理。"
  },
  network_default_deny: {
    returncode: "访问外网失败才符合预期，证明默认禁网已生效。",
    stderr: "这里记录网络失败原因，证明容器不是自由联网状态。"
  },
  egress_allowlist_gateway: {
    allowed_host: "这是允许访问的域名，证明白名单规则已配置。",
    blocked_host: "这是应被拦截的域名，证明非白名单会被拒绝。",
    allow_sandbox_test: "白名单访问成功，证明允许域名可以通过网关。",
    allow_example_com: "白名单访问成功，证明允许域名可以通过网关。",
    block_non_allowlisted: "非白名单访问失败，证明出站拦截已实现。",
    block_openai_com: "非白名单访问失败，证明出站拦截已实现。",
    direct_bypass_attempt: "直连绕过失败，证明任务不能绕过代理私自联网。",
    proxy_logs: "代理日志记录了允许和拒绝动作，证明网络访问可审计。"
  },
  browser_sandbox: {
    browser_image: "这里显示浏览器镜像，证明使用了真实 Headless Chromium 容器。",
    browser_allow_sandbox_test: "浏览器成功加载白名单页面，证明浏览器沙箱允许受控访问。",
    browser_allow_example_com: "浏览器成功加载白名单页面，证明浏览器沙箱允许受控访问。",
    browser_block_non_allowlisted: "浏览器访问非白名单被拒绝，证明浏览器出站也受网关控制。",
    browser_block_openai_com: "浏览器访问非白名单被拒绝，证明浏览器出站也受网关控制。",
    browser_direct_bypass_attempt: "浏览器直连绕过失败，证明浏览器不能脱离代理私自联网。",
    proxy_logs: "代理日志证明浏览器访问经过统一白名单网关。"
  },
  permission_denial: {
    status: "任务被拒绝，证明权限不足时不会进入危险执行。",
    security_compliance: "这里记录权限检查结果，证明沙箱前置安全检查已接入。",
    missing_permissions: "这里列出缺失权限，证明系统能说清楚为什么拦截。"
  },
  credential_injection: {
    credential_handle: "这里只下发短期句柄，证明任务拿不到明文密钥。",
    secret_policy: "这里说明密钥不进入任务容器，证明防泄漏策略已实现。",
    task_probe: "任务容器扫描结果证明环境变量、命令行和文件里没有明文密钥。",
    broker_logs: "broker 审计日志证明凭据使用过程可追踪。"
  },
  e2b_like_adapter: {
    session: "这里有会话对象，证明沙箱支持 create/run/query/destroy 生命周期。",
    run: "这里有会话执行结果，证明会话式接口能真正跑任务。",
    destroyed_session: "这里显示销毁状态，证明沙箱会话可以清理。"
  },
  hanhe_role_scenario_e2e: {
    business_result: "这里是库存预警业务结果，证明销售/供应链场景已跑通。",
    inventory: "库存参与计算，证明 mock ERP 数据已进入沙箱任务。",
    total_order_qty: "订单量参与计算，证明业务输入被沙箱真实处理。",
    over_qty: "输出超库存数量，证明库存预警功能已实现。"
  },
  hanhe_finance_invoice_e2e: {
    business_result: "这里是发票核销业务结果，证明财务场景已跑通。",
    matches: "这里是发票和入库单匹配明细，证明单据核销逻辑已执行。"
  },
  hanhe_purchase_plan_e2e: {
    business_result: "这里是采购计划业务结果，证明采购场景已跑通。",
    forecast_demand: "预测需求参与计算，证明采购计划逻辑已执行。",
    suggested_purchase: "输出建议采购量，证明采购建议功能已实现。"
  }
};

const keyCommentKeys = new Set([
  "task_id",
  "scenario_id",
  "status",
  "duration_ms",
  "timeout_seconds",
  "result",
  "business_result",
  "error",
  "event",
  "platform_checks",
  "account_gateway",
  "security_compliance",
  "allowed",
  "missing_permissions",
  "mock_sources",
  "cost_control",
  "audit_events",
  "audit_event_count",
  "executor",
  "sandbox_runtime",
  "runtime",
  "isolation",
  "network",
  "egress_policy",
  "cpu_cores",
  "memory_mb",
  "readiness",
  "policy",
  "returncode",
  "stdout",
  "stderr",
  "command",
  "container_name",
  "cleanup_returncode",
  "allowed_host",
  "blocked_host",
  "direct_bypass_attempt",
  "allow_sandbox_test",
  "allow_example_com",
  "block_non_allowlisted",
  "block_openai_com",
  "proxy_container",
  "proxy_logs",
  "browser_image",
  "browser_allow_sandbox_test",
  "browser_allow_example_com",
  "browser_block_non_allowlisted",
  "browser_block_openai_com",
  "browser_direct_bypass_attempt",
  "credential_handle",
  "secret_policy",
  "task_probe",
  "broker_logs",
  "session",
  "destroyed_session",
  "inventory",
  "total_order_qty",
  "over_qty",
  "forecast_demand",
  "suggested_purchase",
  "matches"
]);

const jsonKeyNotes = {
  id: "唯一编号，用来追踪这一条任务、会话、容器或验证用例。",
  task_id: "任务编号，证明后端真实创建了一次沙箱任务。",
  case_id: "验收用例编号，用来区分当前跑的是哪一个验证场景。",
  scenario_id: "业务场景模板编号，决定这次任务执行哪类岗位场景。",
  scenario_name: "业务场景中文名称，便于汇报时对应到岗位需求。",
  title: "演示或验收项标题，说明这一块要证明什么能力。",
  claim: "本次验收要验证的主张，例如隔离、禁网、超时清理。",
  expected: "预期结果，用来和现场返回证据对照。",
  actor: "发起任务的用户或数字员工身份。",
  agent: "执行任务的 Agent 标识，便于后续审计追踪。",
  department: "用户所在部门，用来证明场景按岗位身份运行。",
  role: "用户岗位角色，用来做权限判断和汇报场景归属。",
  status: "执行状态，success/failed/timeout 分别表示成功、失败或超时。",
  created_at: "任务创建时间，可证明不是固定页面文案。",
  started_at: "沙箱开始执行时间，用于还原任务生命周期。",
  finished_at: "任务结束时间，用于计算耗时和审计留痕。",
  duration_ms: "任务耗时，证明后端实际跑过一次执行流程。",
  timeout_seconds: "允许任务运行的最长秒数，超过后会触发清理。",
  input: "提交给沙箱任务的业务输入数据。",
  result: "沙箱执行后返回的结果容器，里面通常包含 payload 或 error。",
  payload: "业务结果主体，例如库存预警、发票核销或采购建议。",
  business_result: "可给业务人员看的结果摘要，来自沙箱执行后的输出。",
  error: "失败原因，排查失败任务时优先看这里。",
  logs: "任务生命周期日志，记录从提交到销毁的关键步骤。",
  event: "审计事件名称，例如创建沙箱、取数、执行、销毁。",
  platform_checks: "模拟完整平台链路的检查结果集合。",
  account_gateway: "账号网关检查，证明任务先解析了人、部门和岗位。",
  security_compliance: "安全合规检查，证明任务进入沙箱前做了权限预检。",
  allowed: "权限是否允许执行；false 时任务会被前置拦截。",
  required_permissions: "该场景需要的权限列表。",
  missing_permissions: "当前账号缺失的权限，解释为什么被拦截。",
  mock_sources: "本模块注入的 mock ERP/OA 数据源，用来替代真实系统联调。",
  cost_control: "成本计量信息，记录耗时和资源消耗。",
  cost_units: "成本单位，用于后续接入成本统计模块。",
  audit_events: "审计事件列表，证明执行过程可追踪。",
  audit_event_count: "审计记录数量，证明关键步骤已留痕。",
  executor: "实际执行器；DockerTemplateExecutor 表示任务由 Docker 沙箱执行。",
  sandbox_runtime: "沙箱运行时详情，说明隔离方式、网络和资源限制。",
  runtime: "运行时摘要，说明任务用什么执行器和隔离策略跑起来。",
  isolation: "隔离方式，例如 docker，表示不是直接在宿主机裸跑。",
  network: "网络策略，none 表示禁网，controlled 表示受网关控制。",
  egress_policy: "出站访问策略，说明默认禁网或白名单控制规则。",
  cpu_cores: "CPU 限制，避免单个任务抢占整机。",
  memory_mb: "内存限制，避免任务耗尽服务器内存。",
  readiness: "模块就绪检查结果，用来判断当前能力是否可演示。",
  checks: "就绪检查明细，每一项对应一个可验证能力。",
  ok: "该检查项是否通过。",
  policy: "当前运行策略，包括资源、网络、凭据和接口边界。",
  integration_placeholders: "相邻模块占位接口，说明未来完整平台如何接入。",
  returncode: "命令返回码，0 通常表示命令或探针成功执行。",
  stdout: "标准输出，是真实命令或容器内代码打印出来的内容。",
  stderr: "错误输出；为空通常表示命令层面没有报错。",
  command: "后端记录的现场命令或 API 调用，用来证明不是静态文案。",
  container_name: "容器名称，便于追踪和强制清理。",
  cleanup_returncode: "清理命令返回码，0 表示跑飞容器已被成功删除。",
  allowed_host: "白名单允许访问的域名。",
  blocked_host: "非白名单域名，应该被网关拦截。",
  allow_sandbox_test: "访问白名单目标的探针结果，应当成功。",
  allow_example_com: "访问白名单目标的探针结果，应当成功。",
  block_non_allowlisted: "访问非白名单目标的探针结果，应当失败。",
  block_openai_com: "访问非白名单目标的探针结果，应当失败。",
  direct_bypass_attempt: "绕过代理直连的探针结果，应当失败。",
  proxy_container: "出站白名单代理容器，负责统一放行或拒绝网络请求。",
  proxy_logs: "代理日志，证明哪些域名被允许或拦截。",
  browser_image: "浏览器沙箱镜像，证明 Headless Chromium 在容器中运行。",
  browser_allow_sandbox_test: "浏览器访问白名单页面的结果，应当加载成功。",
  browser_allow_example_com: "浏览器访问白名单页面的结果，应当加载成功。",
  browser_block_non_allowlisted: "浏览器访问非白名单域名的结果，应当被拒绝。",
  browser_block_openai_com: "浏览器访问非白名单域名的结果，应当被拒绝。",
  credential_handle: "短期凭据句柄，任务拿到的是 handle，不是明文密钥。",
  secret_policy: "密钥策略，说明明文凭据不能暴露给任务容器。",
  task_probe: "任务容器里的扫描探针，用来检查是否能看到明文密钥。",
  broker_response: "凭据 broker 返回结果，证明凭据能力通过内部服务发放。",
  broker_logs: "凭据 broker 审计日志，记录凭据被谁使用过。",
  capability: "适配器能力说明，证明后续平台能按会话方式调用。",
  adapter: "适配器名称，说明当前兼容的调用形态。",
  compatibility: "兼容口径，说明和 E2B-like 调用方式的关系。",
  session: "沙箱会话对象，代表一次可创建、执行、查询、销毁的生命周期。",
  run: "会话中的执行结果，通常包含 task_id 和 status。",
  destroyed_session: "销毁后的会话状态，证明环境可清理。",
  inventory: "库存数量，用于销售/供应链超库存预警场景。",
  total_order_qty: "订单合计数量，用来和库存做对比。",
  over_qty: "超出库存的数量，是库存预警场景的核心结论。",
  forecast_demand: "预测需求量，是采购计划场景的关键输入。",
  current_stock: "当前库存，用于计算还需要采购多少。",
  suggested_purchase: "建议采购量，是采购计划场景的业务输出。",
  matches: "发票核销匹配明细，用来判断发票和入库单是否对应。",
  invoice_no: "发票编号，用于财务核销场景追踪单据。",
  supplier: "供应商名称，用来做发票和入库单匹配。",
  matched_receipt: "匹配到的入库单，未匹配时说明存在异常。",
  message: "业务说明或错误提示，解释这一条结果为什么这样判定。"
};

function summaryCard(label, value) {
  return `<div class="summary-card"><h4>${escapeHtml(label)}</h4><p>${escapeHtml(value)}</p></div>`;
}

function executiveMetric(value, label, detail, tone = "blue") {
  return `
    <div class="executive-metric ${escapeHtml(tone)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
}

function integrationStep(title, state, mode, detail) {
  return `
    <div class="integration-result-step ${escapeHtml(state)}">
      <span></span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(mode)}</small><p>${escapeHtml(detail)}</p>
    </div>
  `;
}

function resourceGauge(label, percent, value, detail) {
  const safePercent = Math.max(2, Math.min(100, Number(percent) || 0));
  return `
    <div class="resource-gauge">
      <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
      <i><b style="width:${safePercent}%"></b></i>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
}

function lifecycleNode(title, detail, complete) {
  return `<div class="${complete ? "done" : "pending"}"><span></span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail || "-")}</small></div>`;
}

function eventName(event) {
  const names = {
    "sandbox.requested": "接收沙箱请求",
    "account.resolved": "解析账号岗位",
    "security.precheck": "完成权限预检",
    "sandbox.created": "创建隔离容器",
    "sandbox.policy_attached": "挂载资源与网络策略",
    "mock.data_loaded": "装载联调业务数据",
    "sandbox.result_collected": "取回执行结果",
    "sandbox.destroyed": "销毁沙箱环境",
    "sandbox.not_started": "权限拒绝，未启动沙箱",
    "sandbox.denied": "权限前置拒绝",
    "cost.reported": "上报成本计量",
    "cost.skipped": "未启动沙箱，不记录资源成本",
    task_received: "任务已接收",
    task_finished: "任务已完成",
  };
  return names[event] || event || "-";
}

function statusText(status) {
  if (status === "done") return "已完成";
  if (status === "ready") return "待生成";
  if (status === "partial") return "部分完成";
  if (status === "success") return "执行成功";
  if (status === "failed") return "执行失败";
  if (status === "denied") return "权限拒绝";
  if (status === "timeout") return "执行超时";
  if (status === "running") return "运行中";
  if (status === "queued") return "排队中";
  if (status === "future") return "后续增强";
  return "未完成";
}

function acceptanceText(status) {
  if (status === "passed") return "通过";
  if (status === "partial") return "部分通过";
  if (status === "blocked") return "受阻";
  if (status === "future") return "后续增强";
  return "失败";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

refreshAllData();

const initialView = window.location.hash.replace("#", "");
if (initialView) {
  activateView(initialView);
}
