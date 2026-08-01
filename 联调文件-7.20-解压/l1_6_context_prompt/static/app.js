const STORAGE_KEY = "l1_6_cockpit_state_v2";

const state = {
  projects: [],
  activeProjectId: "demo_project",
  activeDialogId: "control_center",
  session: null,
  closeResult: null,
  syncPackage: null,
  artifacts: [],
  reports: [],
  handoffs: [],
  crossReferences: [],
  autoHandoffInProgress: false,
  deletedProjectIds: [],
};

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  activeScope: document.querySelector("#activeScope"),
  projectList: document.querySelector("#projectList"),
  dialogList: document.querySelector("#dialogList"),
  projectSelect: document.querySelector("#projectSelect"),
  platformControlCenterBtn: document.querySelector("#platformControlCenterBtn"),
  historyPageBtn: document.querySelector("#historyPageBtn"),
  promptCenterBtn: document.querySelector("#promptCenterBtn"),
  newProjectBtn: document.querySelector("#newProjectBtn"),
  newDialogBtn: document.querySelector("#newDialogBtn"),
  quickNewDialogBtn: document.querySelector("#quickNewDialogBtn"),
  controlCenterBtn: document.querySelector("#controlCenterBtn"),
  workbenchTitle: document.querySelector("#workbenchTitle"),
  workbenchSubtitle: document.querySelector("#workbenchSubtitle"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  sendBtn: document.querySelector("#sendBtn"),
  projectId: document.querySelector("#projectId"),
  actorId: document.querySelector("#actorId"),
  projectState: document.querySelector("#projectState"),
  dialogState: document.querySelector("#dialogState"),
  capacityState: document.querySelector("#capacityState"),
  syncState: document.querySelector("#syncState"),
  resultOutput: document.querySelector("#resultOutput"),
  artifactList: document.querySelector("#artifactList"),
  reportList: document.querySelector("#reportList"),
  startupList: document.querySelector("#startupList"),
  capacityCircle: document.querySelector("#capacityCircle"),
  lockBanner: document.querySelector("#lockBanner"),
  fileModalBackdrop: document.querySelector("#fileModalBackdrop"),
  fileModalTitle: document.querySelector("#fileModalTitle"),
  fileModalContent: document.querySelector("#fileModalContent"),
  fileModalClose: document.querySelector("#fileModalClose"),
};

const CONTEXT_PROMPT_DEFS = [
  {
    code: "work_report",
    name: "工作汇报生成提示词",
    purpose: "生成给项目控制中心读取的工作汇报文件。",
  },
  {
    code: "handoff_file",
    name: "工作交接生成提示词",
    purpose: "生成给下一个普通对话框接续使用的工作交接文件。",
  },
  {
    code: "sync_package_compress",
    name: "传承包压缩/升级提示词",
    purpose: "根据旧传承包和工作汇报升级项目级长期上下文。",
  },
];

function projectId() {
  return state.activeProjectId;
}

function actorId() {
  return els.actorId.value.trim() || "u_demo";
}

function loadState() {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  state.projects = saved.projects || [
    { id: "demo_project", name: "默认项目", dialogs: [] },
  ];
  state.deletedProjectIds = saved.deletedProjectIds || [];
  state.projects = state.projects.filter((project) => !isDeletedProject(project.id));
  if (!state.projects.length) {
    state.projects = [{ id: "demo_project", name: "默认项目", dialogs: [] }];
  }
  state.activeProjectId = saved.activeProjectId || state.projects[0].id;
  if (isDeletedProject(state.activeProjectId) || !state.projects.some((project) => project.id === state.activeProjectId)) {
    state.activeProjectId = state.projects[0].id;
  }
  state.activeDialogId = saved.activeDialogId || "control_center";
}

function saveState() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      projects: state.projects,
      deletedProjectIds: state.deletedProjectIds,
      activeProjectId: state.activeProjectId,
      activeDialogId: state.activeDialogId,
    })
  );
}

function activeProject() {
  return state.projects.find((project) => project.id === state.activeProjectId) || state.projects[0];
}

function isDeletedProject(projectIdValue) {
  return state.deletedProjectIds.includes(projectIdValue);
}

function rememberDeletedProject(projectIdValue) {
  if (projectIdValue && !state.deletedProjectIds.includes(projectIdValue)) {
    state.deletedProjectIds.push(projectIdValue);
  }
}

function visibleDialogs(project = activeProject()) {
  return (project.dialogs || []).filter((dialog) => dialog.status !== "deleted" && dialog.session?.status !== "deleted");
}

function visibleProjectIds() {
  return state.projects.filter((project) => !isDeletedProject(project.id)).map((project) => project.id);
}

function activeDialog() {
  if (isAnyControlCenter()) return null;
  return visibleDialogs(activeProject()).find((dialog) => dialog.id === state.activeDialogId) || null;
}

function isAnyControlCenter() {
  return state.activeDialogId === "control_center" || state.activeDialogId === "platform_control_center";
}

function isPlatformControlCenter() {
  return state.activeDialogId === "platform_control_center";
}

function syncActiveSessionFromDialog() {
  state.session = activeDialog()?.session || null;
  return state.session;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      "X-Actor-Id": actorId(),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

function post(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function del(path) {
  return request(path, { method: "DELETE" });
}

function addMessage(role, text, meta = "") {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  item.innerHTML = `<div>${escapeHtml(text).replace(/\n/g, "<br>")}</div>${meta ? `<small>${escapeHtml(meta)}</small>` : ""}`;
  els.messages.append(item);
  els.messages.scrollTop = els.messages.scrollHeight;
}

function clearMessages() {
  els.messages.innerHTML = "";
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setBusy(isBusy) {
  els.sendBtn.disabled = isBusy;
  els.chatInput.disabled = isBusy;
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
}

function showResult(data) {
  els.resultOutput.textContent = JSON.stringify(data, null, 2);
}

function renderShell() {
  const project = activeProject();
  if (isAnyControlCenter()) {
    state.session = null;
  } else {
    syncActiveSessionFromDialog();
  }
  els.projectId.value = project.id;
  els.projectState.textContent = project.name;
  els.dialogState.textContent = isPlatformControlCenter()
    ? "平台总控制中心"
    : state.activeDialogId === "control_center"
      ? "项目控制中心"
      : dialogName(state.activeDialogId);
  els.activeScope.textContent = isPlatformControlCenter()
    ? "Platform / 平台总控制中心"
    : `Project：${project.name} / ${els.dialogState.textContent}`;

  els.projectList.innerHTML = "";
  for (const item of state.projects.filter((project) => !isDeletedProject(project.id))) {
    const row = document.createElement("div");
    row.className = "nav-row";
    const button = document.createElement("button");
    button.className = `history-item ${item.id === state.activeProjectId ? "selected" : ""}`;
    button.type = "button";
    button.textContent = item.name;
    button.addEventListener("click", () => switchProject(item.id));
    const deleteButton = document.createElement("button");
    deleteButton.className = "delete-mini";
    deleteButton.type = "button";
    deleteButton.title = "删除项目";
    deleteButton.textContent = "删";
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteProject(item.id);
    });
    row.append(button, deleteButton);
    els.projectList.append(row);
  }

  els.projectSelect.innerHTML = "";
  for (const item of state.projects.filter((project) => !isDeletedProject(project.id))) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    option.selected = item.id === state.activeProjectId;
    els.projectSelect.append(option);
  }

  if (els.platformControlCenterBtn) {
    els.platformControlCenterBtn.className = `history-item ${isPlatformControlCenter() ? "selected" : ""}`;
  }
  els.controlCenterBtn.className = `history-item ${state.activeDialogId === "control_center" ? "selected" : ""}`;
  els.dialogList.innerHTML = "";
  for (const dialog of visibleDialogs(project)) {
    const row = document.createElement("div");
    row.className = "nav-row";
    const button = document.createElement("button");
    const isDialogLocked = dialog.session?.locked || (dialog.session?.capacity_ratio || 0) >= 1.0;
    const isDialogHandoffDone = dialog.session?.auto_handoff_done;
    button.className = `history-item ${dialog.id === state.activeDialogId ? "selected" : ""}`;
    button.type = "button";
    let label = dialog.name;
    if (isDialogLocked) label += " 🔒";
    button.textContent = label;
    if (isDialogLocked) {
      const badge = document.createElement("span");
      badge.className = "lock-badge";
      badge.textContent = "已锁定";
      button.append(badge);
    } else if (isDialogHandoffDone) {
      const badge = document.createElement("span");
      badge.className = "handoff-badge";
      badge.textContent = "已传承";
      button.append(badge);
      button.title = `已自动传承至下一个对话框：${dialog.session?.next_session_id || ""}`;
    }
    button.addEventListener("click", () => openDialog(dialog.id));
    const deleteButton = document.createElement("button");
    deleteButton.className = "delete-mini";
    deleteButton.type = "button";
    deleteButton.title = "删除对话框";
    deleteButton.textContent = "删";
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteDialog(dialog.id);
    });
    row.append(button, deleteButton);
    els.dialogList.append(row);
  }

  if (isAnyControlCenter()) {
    els.workbenchTitle.textContent = isPlatformControlCenter() ? "平台总控制中心" : "项目控制中心";
    els.workbenchSubtitle.textContent = isPlatformControlCenter()
      ? "跨项目只读检索平台历史，可用 AI 解读结果，不执行业务、收口或传承。"
      : "只读检索当前项目历史；跨项目检索请前往平台总控制中心。";
    els.chatInput.placeholder = isPlatformControlCenter()
      ? "跨项目检索：输入项目名、关键词、session_id 或 record_id"
      : "检索本项目历史：输入关键词、对话框名、session_id 或 record_id";
    els.lockBanner.hidden = true;
    els.chatInput.disabled = false;
    els.sendBtn.disabled = false;
  } else {
    els.workbenchTitle.textContent = dialogName(state.activeDialogId);
    els.workbenchSubtitle.textContent = "普通对话框独立工作；新建时读取本项目传承包和上一轮交接文件。";
    const isLocked = state.session?.locked || (state.session?.capacity_ratio || 0) >= 1.0;
    if (isLocked) {
      els.chatInput.placeholder = "此对话框已达容量上限，已锁定";
      els.chatInput.disabled = true;
      els.sendBtn.disabled = true;
      els.lockBanner.hidden = false;
    } else {
      els.chatInput.placeholder = "直接和 AI 对话；输入 /收口 可触发自动传承演示";
      els.chatInput.disabled = false;
      els.sendBtn.disabled = false;
      els.lockBanner.hidden = true;
    }
  }
  updateStatePanel();
}

function updateStatePanel() {
  const ratio = state.session?.capacity_ratio ? `${Math.round(state.session.capacity_ratio * 100)}%` : "0%";
  els.capacityState.textContent = ratio;
  els.syncState.textContent = state.syncPackage?.version_no ? `v${state.syncPackage.version_no}` : "无";
  updateCapacityCircle();
}

function updateCapacityCircle() {
  const circle = els.capacityCircle;
  const fill = circle?.querySelector(".capacity-fill");
  const text = circle?.querySelector(".capacity-text");
  if (!circle || !fill || !text) return;

  const CIRCUMFERENCE = 87.96; // 2 * π * 14
  const hasSession = !isAnyControlCenter() && state.session;
  const ratio = hasSession ? Math.min(state.session.capacity_ratio, 1) : 0;

  // update ring
  fill.style.strokeDashoffset = CIRCUMFERENCE * (1 - ratio);

  // update text
  text.textContent = hasSession ? `${Math.round(ratio * 100)}%` : "--";

  // color level
  let level;
  if (!hasSession) {
    level = "off";
  } else if (state.session.locked || ratio >= 1.0) {
    level = "locked";
  } else if (ratio < 0.5) {
    level = "low";
  } else if (ratio < 0.8) {
    level = "mid";
  } else if (ratio < 0.85) {
    level = "warn";
  } else {
    level = "full";
  }
  circle.setAttribute("data-level", level);

  // tooltip
  if (hasSession && state.session) {
    const used = state.session.used_units ?? 0;
    const limit = state.session.capacity_limit ?? 0;
    let tip = `容量：${used} / ${limit}（${Math.round(ratio * 100)}%）`;
    if (state.session.locked) {
      tip += "\n🔒 已锁定（超过100%）";
    } else if (state.session.auto_handoff_done) {
      tip += "\n✓ 已自动收口传承";
      if (state.session.next_session_id) {
        tip += `\n→ 下一个对话框：${state.session.next_session_id}`;
      }
    }
    circle.setAttribute("title", tip);
  } else {
    circle.setAttribute("title", "上下文容量使用率（控制中心无会话）");
  }
}

function updateLastAssistantMessage(text) {
  const messages = els.messages.querySelectorAll(".message.assistant");
  if (messages.length > 0) {
    const last = messages[messages.length - 1];
    const div = last.querySelector("div");
    if (div) div.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function deleteProject(projectIdValue) {
  const project = state.projects.find((item) => item.id === projectIdValue);
  if (!project) return;
  if (state.projects.length <= 1) {
    addMessage("assistant", "至少保留一个项目，当前项目不能删除。");
    return;
  }
  if (!confirm(`确认删除项目「${project.name}」吗？\n这个操作会移除本地演示台里的项目和对话框。`)) return;
  rememberDeletedProject(projectIdValue);
  state.projects = state.projects.filter((item) => item.id !== projectIdValue);
  if (state.activeProjectId === projectIdValue) {
    state.activeProjectId = state.projects[0].id;
    state.activeDialogId = "control_center";
    state.session = null;
    state.closeResult = null;
    state.syncPackage = null;
  }
  saveState();
  renderShell();
  clearMessages();
  addMessage("assistant", `已删除项目：${project.name}`);
  refreshProjectData();
}

async function deleteDialog(dialogId) {
  const project = activeProject();
  const dialog = project.dialogs.find((item) => item.id === dialogId);
  if (!dialog) return;
  if (!confirm(`确认删除对话框「${dialog.name}」吗？\n这个操作会从侧栏隐藏该对话框；已经生成的历史文件不会被硬删除。`)) return;
  if (dialog.session?.id) {
    await del(`/api/sessions/${encodeURIComponent(dialog.session.id)}`);
  }
  project.dialogs = project.dialogs.filter((item) => item.id !== dialogId);
  if (state.activeDialogId === dialogId) {
    state.activeDialogId = "control_center";
    state.session = null;
    state.closeResult = null;
  }
  saveState();
  renderShell();
  clearMessages();
  addMessage("assistant", `已删除对话框：${dialog.name}`);
  refreshProjectData();
}

async function switchProject(projectIdValue) {
  state.activeProjectId = projectIdValue;
  state.activeDialogId = "control_center";
  state.session = null;
  state.closeResult = null;
  state.syncPackage = null;
  saveState();
  renderShell();
  clearMessages();
  addMessage("assistant", `已切换到项目：${activeProject().name}\n项目之间的数据用 project_id 隔离。`);
  await refreshProjectData();
}

async function openDialog(dialogId) {
  state.activeDialogId = dialogId;
  const dialog = activeProject().dialogs.find((item) => item.id === dialogId);
  state.session = dialog?.session || null;
  saveState();
  renderShell();
  clearMessages();

  // Check if session is locked
  if (state.session && (state.session.locked || (state.session.capacity_ratio || 0) >= 1.0)) {
    els.lockBanner.hidden = false;
    els.chatInput.disabled = true;
    els.sendBtn.disabled = true;
    els.chatInput.placeholder = "此对话框已达容量上限，已锁定";
    addMessage(
      "assistant",
      "🔒 这个对话框已达到 100% 容量上限，已被锁定。\n\n你只能浏览历史对话，不能发送新消息。\n\n如需继续工作，请新建对话框，或输入「/收口」手动触发收口。"
    );
    if (state.session) {
      await loadSessionMessages(state.session.id);
    }
    return;
  }

  // Normal dialog
  els.lockBanner.hidden = true;
  els.chatInput.disabled = false;
  els.sendBtn.disabled = false;

  if (state.session) {
    await loadSessionMessages(state.session.id);
  }
  if (!els.messages.children.length) {
    addMessage("assistant", `${dialogName(dialogId)} 已打开。\n这个对话框与本项目其他对话框隔离，可以直接输入内容和 AI 对话。`);
  }
}

function dialogName(dialogId) {
  if (dialogId === "platform_control_center") return "平台总控制中心";
  if (dialogId === "control_center") return "项目控制中心";
  const dialog = activeProject().dialogs.find((item) => item.id === dialogId);
  return dialog?.name || "普通对话框";
}

async function createProject() {
  const no = state.projects.filter((project) => !isDeletedProject(project.id)).length + 1;
  const defaultName = `项目 ${no}`;
  const name = prompt("请输入项目名称", defaultName)?.trim();
  if (!name) {
    addMessage("assistant", "已取消新建项目：项目名称不能为空。");
    return;
  }
  const exists = state.projects.some((item) => !isDeletedProject(item.id) && item.name === name);
  if (exists) {
    addMessage("assistant", `已取消新建项目：项目名称「${name}」已存在，请换一个名称。`);
    return;
  }
  const project = {
    id: `project_${Date.now()}`,
    name,
    dialogs: [],
  };
  state.projects.push(project);
  state.activeProjectId = project.id;
  state.activeDialogId = "control_center";
  saveState();
  renderShell();
  clearMessages();
  addMessage("assistant", `已新建项目：${project.name}\n这个项目会使用独立 project_id：${project.id}`);
  await refreshProjectData();
}

async function createDialog() {
  const project = activeProject();
  const no = visibleDialogs(project).length + 1;
  const payload = {
    project_id: project.id,
    title: `${project.name} - 对话框 ${no}`,
    capacity_limit: 1000,
    used_units: 120,
    summary: "新建对话框，启动时读取本项目最新传承包和上一轮工作交接文件。",
    open_todos: ["继续上一轮未完成事项"],
    decisions: [],
    risks: [],
    created_by: actorId(),
  };
  const session = await post("/api/sessions", payload);
  const dialog = {
    id: `dialog_${Date.now()}`,
    name: `对话框 ${no}`,
    session,
  };
  project.dialogs.push(dialog);
  state.activeDialogId = dialog.id;
  state.session = session;
  state.closeResult = null;
  saveState();
  renderShell();
  clearMessages();
  addMessage("assistant", `已新建 ${dialog.name}。\n正在读取本项目最新工作交接文件和传承包...`);
  await loadStartupPackage();
}

async function loadStartupPackage() {
  const parts = [];
  try {
    const latestSync = await request(`/api/projects/${encodeURIComponent(projectId())}/sync-packages/latest`);
    state.syncPackage = latestSync;
    parts.push(`【传承包】已读取 v${latestSync.version_no}\n${firstLines(latestSync.content, 10)}`);
  } catch {
    parts.push("【传承包】当前项目还没有传承包。");
  }
  try {
    const handoffs = await request(`/api/handoff-files?project_id=${encodeURIComponent(projectId())}`);
    const latest = handoffs.items?.[0];
    if (latest) parts.push(`【工作交接文件】已读取\n${firstLines(latest.package_json || "", 12)}`);
    else parts.push("【工作交接文件】当前项目还没有上一轮交接文件。");
  } catch {
    parts.push("【工作交接文件】读取失败或暂无记录。");
  }
  openFileModal("新对话启动包", parts.join("\n\n"));
  addMessage("assistant", "新对话框启动包已加载：\n" + parts.map((p) => p.split("\n")[0]).join("\n"));
  updateStatePanel();
}

async function checkHealth() {
  try {
    await request("/health");
    els.apiStatus.textContent = "本地服务已连接";
    els.apiStatus.className = "role-pill ok";
  } catch (error) {
    els.apiStatus.textContent = "服务不可用";
    els.apiStatus.className = "role-pill bad";
    addMessage("assistant", `本地服务连接失败：${error.message}`);
  }
}

async function handleUserMessage(text) {
  const normalized = text.trim().toLowerCase();
  if (!normalized) return;

  addMessage("user", text);
  setBusy(true);
  try {
    let result;

    // Guard: locked session only allows /收口 command
    const isLocked = state.session && (state.session.locked || (state.session.capacity_ratio || 0) >= 1.0);
    if (isLocked && !isAnyControlCenter()) {
      const isHandoffCmd = isCommand(normalized, ["模拟当前对话框超过85%并收口", "超过85%收口", "/收口", "帮我总结传承包", "总结传承包", "手动收口"]);
      if (!isHandoffCmd) {
        addMessage("assistant", "🔒 此对话框已锁定（容量已达100%）。\n\n你可以浏览历史记录，或输入「/收口」手动触发收口，或新建对话框继续工作。");
        setBusy(false);
        return;
      }
    }

    if (isPlatformControlCenter()) {
      result = await searchPlatformControlCenterHistory(text);
      if (result?.data) showResult(result.data);
      if (result?.message) addMessage("assistant", result.message, result.meta);
      await refreshProjectData();
      return;
    }
    if (state.activeDialogId === "control_center") {
      result = await searchControlCenterHistory(text);
      if (result?.data) showResult(result.data);
      if (result?.message) addMessage("assistant", result.message, result.meta);
      await refreshProjectData();
      return;
    }
    if (isCommand(normalized, ["模拟当前对话框超过85%并收口", "超过85%收口", "/收口"])) {
      result = await triggerAutoHandoffDemo();
    } else if (isCommand(normalized, ["新建项目", "/新建项目"])) {
      await createProject();
      result = { message: "项目已创建。", data: activeProject() };
    } else if (isCommand(normalized, ["新建对话", "新建对话框", "/新建对话"])) {
      await createDialog();
      result = { message: "对话框已创建。", data: state.session };
    } else if (isCommand(normalized, ["查看控制中心工作汇报", "控制中心", "/控制中心"])) {
      result = await showControlCenterReports();
    } else if (isCommand(normalized, ["查看最新交接和传承包", "查看启动包", "/启动包"])) {
      result = await showStartupPackage();
    } else if (isCommand(normalized, ["查看工作区文件", "/文件"])) {
      result = await refreshArtifacts();
    } else if (isCommand(normalized, ["查看 prompt trace", "查看prompt trace", "/trace"])) {
      result = await refreshTraces();
    } else {
      result = await chatWithCurrentDialog(text);
    }
    if (result?.data) showResult(result.data);
    if (result?.message) addMessage("assistant", result.message, result.meta);
    await refreshProjectData();
  } catch (error) {
    addMessage("assistant", `执行失败：${error.message}`);
  } finally {
    updateStatePanel();
    setBusy(false);
    els.chatInput.focus();
  }
}

function hasAny(text, words) {
  return words.some((word) => text.includes(word));
}

function isCommand(text, commands) {
  return commands.some((command) => text === command.toLowerCase());
}

async function chatWithCurrentDialog(text) {
  if (isPlatformControlCenter()) {
    return searchPlatformControlCenterHistory(text);
  }
  if (state.activeDialogId === "control_center") {
    return searchControlCenterHistory(text);
  }
  if (!state.session) {
    const dialog = activeProject().dialogs.find((item) => item.id === state.activeDialogId);
    state.session = dialog?.session || null;
  }
  if (!state.session) {
    throw new Error("当前没有普通对话框 session。请先新建普通对话框。");
  }
  const data = await post(`/api/sessions/${state.session.id}/chat`, {
    message: text,
    actor_id: actorId(),
  });

  // Auto-handoff path
  if (data.auto_handoff) {
    return await handleAutoHandoffResult(data);
  }

  // Normal path
  state.session = data.session;
  const dialog = activeProject().dialogs.find((item) => item.id === state.activeDialogId);
  if (dialog) dialog.session = state.session;
  saveState();
  const usedReferences = data.used_cross_project_references || [];
  const referenceMeta = usedReferences.length
    ? `\n已参考当前项目跨项目引用：${usedReferences
        .map((item) => `${item.source_project_id}/${item.source_record_type}/${item.source_record_id}`)
        .join("；")}`
    : "";
  return {
    message: data.reply,
    meta: `${data.llm?.provider || "llm"} / ${data.llm?.model || ""}${referenceMeta}`,
    data,
  };
}

async function triggerAutoHandoffDemo() {
  if (state.activeDialogId === "control_center") {
    throw new Error("控制中心不直接自动传承。请先新建或打开一个普通对话框。");
  }
  if (!state.session) {
    const dialog = activeProject().dialogs.find((item) => item.id === state.activeDialogId);
    state.session = dialog?.session || null;
  }
  if (!state.session) {
    throw new Error("当前没有普通对话框 session。请先新建对话框。");
  }
  if (state.session.auto_handoff_done) {
    throw new Error("这个对话框已经自动传承过，不能重复触发自动传承。旧对话框未满 100% 时仍可直接发送普通消息。");
  }
  if (state.session.locked || (state.session.capacity_ratio || 0) >= 1.0) {
    throw new Error("这个对话框已经达到 100% 并锁定，不能自动传承。");
  }

  const ratio = state.session.capacity_ratio || 0;
  if (ratio < 0.8 || ratio >= 0.85) {
    const targetUsed = Math.floor((state.session.capacity_limit || 1000) * 0.84);
    state.session = await request(`/api/sessions/${state.session.id}/capacity`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ used_units: targetUsed, actor_id: actorId() }),
    });
    const dialog = activeProject().dialogs.find((item) => item.id === state.activeDialogId);
    if (dialog) dialog.session = state.session;
    saveState();
    renderShell();
  }

  const demoText = "请继续当前工作，并在容量即将超过 85% 时自动传承到新对话框。";
  addMessage("assistant", "已把当前对话框调整到 85% 前一刻，下面走真实自动传承分步流程。");
  return await chatWithCurrentDialog(demoText);
}

async function handleAutoHandoffResult(data) {
  state.autoHandoffInProgress = true;
  const project = activeProject();
  const runId = data.handoff_run_id || data.handoff_run?.id;
  if (!runId) {
    throw new Error("后端没有返回 handoff_run_id，无法继续自动传承。");
  }

  // Show the progress card
  const progressCard = document.createElement("article");
  progressCard.className = "auto-handoff-progress";
  progressCard.innerHTML = `
    <div class="auto-handoff-step">
      <span class="step-icon done">✓</span>
      <span>检测到容量即将超过 85%，已创建下一个对话框</span>
    </div>
    <div class="auto-handoff-step" id="step1">
      <span class="step-icon">○</span>
      <span>正在迁移本轮 AI 回复...</span>
    </div>
    <div class="auto-handoff-step" id="step2">
      <span class="step-icon">○</span>
      <span>正在生成工作汇报文件...</span>
    </div>
    <div class="auto-handoff-step" id="step3">
      <span class="step-icon">○</span>
      <span>正在生成工作交接文件...</span>
    </div>
    <div class="auto-handoff-step" id="step4">
      <span class="step-icon">○</span>
      <span>正在升级传承包...</span>
    </div>
    <div class="auto-handoff-step" id="step5">
      <span class="step-icon">○</span>
      <span>正在完成标记并切换...</span>
    </div>
  `;
  els.messages.append(progressCard);
  els.messages.scrollTop = els.messages.scrollHeight;
  setBusy(true);

  _markStep("step1", "active", "…", "正在迁移本轮 AI 回复...");
  data = await post(`/api/handoff-runs/${encodeURIComponent(runId)}/reply`, { actor_id: actorId() });
  _markStep("step1", "done", "✓", "本轮 AI 回复已写入新对话框");

  _markStep("step2", "active", "…", "正在生成工作汇报文件...");
  data = await post(`/api/handoff-runs/${encodeURIComponent(runId)}/work-report`, { actor_id: actorId() });
  _markStep("step2", "done", "✓", "工作汇报文件已生成");

  _markStep("step3", "active", "…", "正在生成工作交接文件...");
  data = await post(`/api/handoff-runs/${encodeURIComponent(runId)}/handoff-file`, { actor_id: actorId() });
  _markStep("step3", "done", "✓", "工作交接文件已生成");

  _markStep("step4", "active", "…", "正在升级传承包...");
  data = await post(`/api/handoff-runs/${encodeURIComponent(runId)}/sync-package`, { actor_id: actorId() });
  _markStep("step4", "done", "✓", "传承包已升级");

  _markStep("step5", "active", "…", "正在完成标记并切换...");
  data = await post(`/api/handoff-runs/${encodeURIComponent(runId)}/complete`, { actor_id: actorId() });
  _markStep("step5", "done", "✓", "自动传承完成，已切换到新对话框");

  // Update old dialog state
  const oldDialog = project.dialogs.find((item) => item.session?.id === data.old_session?.id);
  if (oldDialog) {
    oldDialog.session = data.old_session;
  }

  // Create new dialog entry
  const no = project.dialogs.length + 1;
  const newDialogName = `${dialogNameForSession(data.old_session?.id) || "对话框"} (续${no})`;
  const newDialog = {
    id: `dialog_${Date.now()}`,
    name: newDialogName,
    session: data.new_session,
  };
  project.dialogs.push(newDialog);

  // Switch to new dialog
  state.activeDialogId = newDialog.id;
  state.session = data.new_session;
  state.syncPackage = data.sync_package;
  state.closeResult = {
    work_report: data.work_report,
    handoff_file: data.handoff_file,
  };
  state.autoHandoffInProgress = false;
  saveState();
  renderShell();

  // Show the LLM reply in the new dialog
  addMessage("assistant", data.reply, `${data.llm?.provider || "llm"} / ${data.llm?.model || ""}`);

  // Show generated files summary
  addMessage(
    "assistant",
    [
      "📋 自动收口已生成以下文件：",
      `1. 工作汇报文件.md — 已归档到控制中心（容量：${Math.round((data.old_session?.capacity_ratio || 0) * 100)}%）`,
      "2. 工作交接文件.json — 供后续对话框读取",
      `3. 传承包_v${data.sync_package?.version_no || "?"}.md — 项目知识已升级`,
      "",
      `当前在新对话框「${newDialogName}」中，已自动加载 AI 的回复。`,
    ].join("\n")
  );

  setBusy(false);
  await refreshProjectData();

  return {
    message: null,
    data,
  };
}

function _markStep(stepId, cls, icon, text) {
  const step = document.querySelector(`#${stepId}`);
  if (!step) return;
  const iconEl = step.querySelector(".step-icon");
  if (iconEl) {
    iconEl.className = `step-icon ${cls}`;
    iconEl.textContent = icon;
  }
  const span = step.querySelector("span:last-child");
  if (span) span.textContent = text;
}

async function loadSessionMessages(sessionId) {
  try {
    const data = await request(`/api/sessions/${sessionId}/messages`);
    for (const message of data.items || []) {
      addMessage(message.role === "assistant" ? "assistant" : "user", message.content);
    }
  } catch (error) {
    addMessage("assistant", `历史消息读取失败：${error.message}`);
  }
}

async function searchControlCenterHistory(rawQuery) {
  const q = rawQuery.trim();
  await syncProjectDialogsFromServer();
  const answerData = await post(`/api/projects/${encodeURIComponent(projectId())}/control-center/answer`, {
    question: q,
    actor_id: actorId(),
  });
  const data = answerData.history || {};
  const records = data.records || [];
  if (answerData.redirect_to === "platform_control_center" || data.redirect_to === "platform_control_center") {
    renderCrossProjectRedirect(q, answerData.answer);
    return {
      message: null,
      meta: "项目控制中心只检索当前项目；跨项目检索请使用总控制中心。",
      data: answerData,
    };
  }
  if (!records.length) {
    return {
      message: answerData.answer || `控制中心没有找到「${rawQuery}」相关历史。`,
      meta: "控制中心 AI 只解释检索结果，不执行任务、不触发传承。",
      data: answerData,
    };
  }
  addMessage(
    "assistant",
    answerData.answer || "已找到相关历史。下面是可打开的对话框入口。",
    `${answerData.llm?.provider || "control-center"} / ${answerData.llm?.model || "readonly"}`
  );
  renderControlCenterSearchResults(q, data);
  return {
    message: null,
    meta: "控制中心 AI 只解释检索结果，不执行任务、不触发传承。",
    data: answerData,
  };
}

async function searchPlatformControlCenterHistory(rawQuery) {
  const q = rawQuery.trim();
  const answerData = await post("/api/platform/control-center/answer", {
    question: q,
    actor_id: actorId(),
    include_project_ids: visibleProjectIds(),
    exclude_project_ids: state.deletedProjectIds,
  });
  const data = answerData.history || {};
  const records = data.records || [];
  if (!records.length) {
    return {
      message: answerData.answer || `平台总控制中心没有找到「${rawQuery}」相关历史。`,
      meta: "平台控制中心 AI 只解释检索结果，不执行任务、不触发传承。",
      data: answerData,
    };
  }
  addMessage(
    "assistant",
    answerData.answer || "已找到相关平台历史。下面是可打开的项目/对话框入口。",
    `${answerData.llm?.provider || "platform-control-center"} / ${answerData.llm?.model || "readonly"}`
  );
  renderPlatformControlCenterSearchResults(q, data);
  return {
    message: null,
    meta: "平台控制中心 AI 只解释检索结果，不执行任务、不触发传承。",
    data: answerData,
  };
}

function renderCrossProjectRedirect(query, answer) {
  addMessage("assistant", answer || "跨项目检索请前往账号级总控制中心。", "项目控制中心 / 边界规则");
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>跨项目检索</strong>
      <span>${escapeHtml(query || "跨项目需求")}</span>
    </div>
    <div class="history-group">
      <h3>边界提示</h3>
      <article class="history-card">
        <div>
          <strong>请使用账号级总控制中心</strong>
          <span>项目控制中心只检索当前项目。</span>
          <span>总控制中心可以跨项目查找传承包、工作汇报、工作交接文件和对话框来源。</span>
        </div>
      </article>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "前往总控制中心";
  button.addEventListener("click", showPlatformControlCenter);
  actions.append(button);
  page.querySelector(".history-card").append(actions);
  els.messages.append(page);
  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderControlCenterSearchResults(query, data) {
  const records = data.records || [];
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>检索结果</strong>
      <span>${escapeHtml(query || "全部历史")} / 命中 ${data.summary?.matched_count || records.length} 条</span>
    </div>
  `;
  const group = document.createElement("section");
  group.className = "history-group";
  group.innerHTML = "<h3>对应对话框</h3>";
  const dialogMatches = controlCenterDialogMatches(records);
  if (!dialogMatches.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "命中了项目文件，但没有关联到具体对话框。请换一个关键词或打开历史文件中心。";
    group.append(empty);
  } else {
    for (const item of dialogMatches) {
      group.append(renderControlCenterDialogCard(item));
    }
  }
  page.append(group);
  els.messages.append(page);
  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderPlatformControlCenterSearchResults(query, data) {
  const records = data.records || [];
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>跨项目来源结果</strong>
      <span>${escapeHtml(query || "全部历史")} / 命中 ${data.summary?.matched_count || records.length} 条</span>
    </div>
  `;
  const group = document.createElement("section");
  group.className = "history-group";
  group.innerHTML = "<h3>来源记录</h3>";
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "没有可展示的跨项目来源。";
    group.append(empty);
  } else {
    for (const item of records.slice(0, 12)) {
      group.append(renderPlatformSourceCard(item));
    }
  }
  page.append(group);
  els.messages.append(page);
  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderPlatformSourceCard(item) {
  const card = document.createElement("article");
  card.className = "history-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(item.name || item.kind || "历史记录")}</strong>
      <span>来源项目：${escapeHtml(item.project_id || "")}</span>
      <span>来源类型：${escapeHtml(item.kind || "")}</span>
      <span>session_id：${escapeHtml(item.session_id || "未绑定 session")}</span>
      <span>record_id：${escapeHtml(item.record_id || "")}</span>
      <span>${escapeHtml(firstLines(item.content || "", 2) || "无摘要")}</span>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";
  if (item.project_id) {
    const projectButton = document.createElement("button");
    projectButton.type = "button";
    projectButton.textContent = "切到项目";
    projectButton.addEventListener("click", () => switchToProjectFromSearch(item.project_id));
    actions.append(projectButton);
  }
  if (item.project_id && item.project_id !== projectId()) {
    const referenceButton = document.createElement("button");
    referenceButton.type = "button";
    referenceButton.textContent = "引用";
    referenceButton.addEventListener("click", () => openProjectReferencePicker(item));
    actions.append(referenceButton);
  }
  if (item.session_id) {
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.textContent = "打开对话框";
    openButton.addEventListener("click", () => openDialogBySession(item.session_id));
    actions.append(openButton);
  }
  card.append(actions);
  return card;
}

function controlCenterDialogMatches(records) {
  const bySession = new Map();
  for (const item of records) {
    if (!item.session_id) continue;
    const existing = bySession.get(item.session_id);
    if (!existing) {
      bySession.set(item.session_id, {
        project_id: item.project_id,
        session_id: item.session_id,
        name: dialogNameForSession(item.session_id),
        kinds: new Set([item.kind]),
        record_count: 1,
      });
    } else {
      existing.kinds.add(item.kind);
      existing.record_count += 1;
    }
  }
  return Array.from(bySession.values()).map((item) => ({
    ...item,
    kinds: Array.from(item.kinds),
  }));
}

async function openProjectReferencePicker(item) {
  setBusy(true);
  try {
    // 查询哪些项目已经引用过这条来源
    const checkData = await request(
      `/api/references/check?source_project_id=${encodeURIComponent(item.project_id)}&source_record_type=${encodeURIComponent(item.kind)}&source_record_id=${encodeURIComponent(item.record_id)}`
    );
    const referencedIds = new Set(checkData.referenced_project_ids || []);

    // 筛选可选项目：排除来源项目 + 已引用的项目 + 已删除的项目
    const candidates = state.projects.filter(
      (project) =>
        project.id !== item.project_id &&
        !referencedIds.has(project.id) &&
        !isDeletedProject(project.id)
    );

    if (!candidates.length) {
      addMessage("assistant", "没有可引用的项目：所有项目都已引用过此内容，或当前只有来源项目。");
      return;
    }

    renderProjectReferencePicker(item, candidates);
  } catch (error) {
    addMessage("assistant", `加载可选项目失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function renderProjectReferencePicker(item, candidates) {
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>选择要引用到的目标项目</strong>
      <span>来源：${escapeHtml(item.project_id)} / ${escapeHtml(item.kind)} / ${escapeHtml(item.record_id)}</span>
    </div>
    <div class="history-group">
      <h3>可选项目（${candidates.length} 个）</h3>
    </div>
  `;
  const group = page.querySelector(".history-group");
  for (const project of candidates) {
    const card = document.createElement("article");
    card.className = "history-card";
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(project.name)}</strong>
        <span>project_id：${escapeHtml(project.id)}</span>
      </div>
    `;
    const actions = document.createElement("div");
    actions.className = "history-actions";
    const refButton = document.createElement("button");
    refButton.type = "button";
    refButton.textContent = "引用到此项目";
    refButton.addEventListener("click", async () => {
      refButton.disabled = true;
      refButton.textContent = "引用中...";
      try {
        await createCrossProjectReferenceToTarget(item, project);
        refButton.textContent = "✓ 已引用";
        refButton.style.background = "#e8f5e0";
        refButton.style.color = "#2f7d22";
      } catch (error) {
        refButton.disabled = false;
        refButton.textContent = "引用失败，重试";
        addMessage("assistant", `引用失败：${error.message}`);
      }
    });
    actions.append(refButton);
    card.append(actions);
    group.append(card);
  }
  clearMessages();
  els.messages.append(page);
  els.messages.scrollTop = 0;
}

async function createCrossProjectReferenceToTarget(item, targetProject) {
  const result = await post(`/api/projects/${encodeURIComponent(targetProject.id)}/cross-project-references`, {
    actor_id: actorId(),
    source_project_id: item.project_id,
    source_session_id: item.session_id,
    source_record_type: item.kind,
    source_record_id: item.record_id,
    source_name: item.name || item.kind || "跨项目来源",
    source_excerpt: item.content || "",
    note: `由总控制中心引用到 ${targetProject.name}`,
  });
  return result;
}

function controlCenterRecord(name, kind, projectIdValue, sessionId, recordId, content) {
  const dialogName = dialogNameForSession(sessionId);
  const text = [name, kind, projectIdValue, sessionId, recordId, dialogName, content || ""].join("\n").toLowerCase();
  return {
    name,
    kind,
    projectId: projectIdValue,
    sessionId: sessionId || "未绑定 session",
    dialogName,
    recordId,
    content: content || "",
    searchText: text,
  };
}

function controlCenterSummary(item) {
  return {
    name: item.name,
    kind: item.kind,
    project_id: item.projectId,
    session_id: item.sessionId,
    dialog_name: item.dialogName,
    record_id: item.recordId,
  };
}

async function closeCurrentDialogAtLimit() {
  if (state.activeDialogId === "control_center") {
    throw new Error("控制中心不直接收口。请先新建或打开一个普通对话框。");
  }
  if (!state.session) {
    throw new Error("当前没有普通对话框 session。请先新建对话框。");
  }
  state.session = await post(`/api/sessions/${state.session.id}/context-usage`, {
    text: "模拟对话内容增长，超过 85% 后触发收口。" + "上下文 ".repeat(760),
    actor_id: actorId(),
  });
  const dialog = activeProject().dialogs.find((item) => item.id === state.activeDialogId);
  if (dialog) dialog.session = state.session;
  state.closeResult = await post(`/api/sessions/${state.session.id}/close`, { actor_id: actorId() });
  state.syncPackage = await post(`/api/projects/${encodeURIComponent(projectId())}/sync-packages/upgrade`, {
    work_report_id: state.closeResult.work_report.id,
    actor_id: actorId(),
  });
  saveState();
  openFileModal("超过85%收口生成文件", [
    "【工作汇报文件：交给控制中心】",
    state.closeResult.work_report.content,
    "",
    "【工作交接文件：交给下一个新对话框】",
    state.closeResult.handoff_file.package_json,
    "",
    `【传承包：交给下一个新对话框】v${state.syncPackage.version_no}`,
    state.syncPackage.content,
  ].join("\n"));
  return {
    message: [
      `${dialogName(state.activeDialogId)} 已超过 85% 并完成收口。`,
      "已生成：",
      "1. 工作汇报文件.md：交给控制中心，方便用户查询。",
      "2. 工作交接文件.json：交给本项目下一个新建对话框。",
      `3. 传承包_v${state.syncPackage.version_no}.md：压缩以前对话框内容，也交给新对话框。`,
    ].join("\n"),
    meta: "真实调用 context-usage + close + sync-packages/upgrade",
    data: { closeResult: state.closeResult, syncPackage: state.syncPackage },
  };
}

async function showControlCenterReports() {
  state.activeDialogId = "control_center";
  state.session = null;
  saveState();
  renderShell();
  await refreshProjectData();
  clearMessages();
  await loadControlCenterMessages("project");
  const [data, refData] = await Promise.all([
    request(`/api/projects/${encodeURIComponent(projectId())}/control-center/history`),
    request(`/api/projects/${encodeURIComponent(projectId())}/cross-project-references`).catch(() => ({ items: [] })),
  ]);
  state.crossReferences = refData.items || [];
  renderControlCenterDashboard(data);
  return {
    meta: "输入关键词进行检索；不会执行新建、收口、升级或删除。",
    data,
  };
}

async function showPlatformControlCenter() {
  state.activeDialogId = "platform_control_center";
  state.session = null;
  saveState();
  renderShell();
  clearMessages();
  await loadControlCenterMessages("platform");
  const include = encodeURIComponent(visibleProjectIds().join(","));
  const exclude = encodeURIComponent(state.deletedProjectIds.join(","));
  const data = await request(`/api/platform/control-center/history?include_project_ids=${include}&exclude_project_ids=${exclude}`);
  renderPlatformControlCenterDashboard(data);
  return {
    meta: "跨项目输入关键词进行检索；不会执行新建、收口、升级或传承。",
    data,
  };
}

async function loadControlCenterMessages(scope) {
  const path = scope === "platform"
    ? "/api/platform/control-center/messages"
    : `/api/projects/${encodeURIComponent(projectId())}/control-center/messages`;
  try {
    const data = await request(path);
    for (const message of data.items || []) {
      addMessage(message.role === "assistant" ? "assistant" : "user", message.content, message.meta || "");
    }
  } catch (error) {
    addMessage("assistant", `控制中心历史读取失败：${error.message}`);
  }
}

function renderControlCenterDashboard(data) {
  const summary = data.summary || {};
  const records = data.records || [];
  const visibleDialogCount = visibleDialogs(activeProject()).length;
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>项目控制中心</strong>
      <span>project_id：${escapeHtml(data.project_id || projectId())}</span>
    </div>
    <div class="history-group">
      <h3>项目历史总览</h3>
      <article class="history-card">
        <div>
          <strong>${escapeHtml(activeProject().name)}</strong>
          <span>对话框：${visibleDialogCount}</span>
          <span>对话消息：${summary.message_count || 0}</span>
          <span>工作汇报：${summary.work_report_count || 0}</span>
          <span>工作交接：${summary.handoff_file_count || 0}</span>
          <span>传承包：${summary.sync_package_count || 0}</span>
          <span>跨项目引用：${summary.cross_project_reference_count || 0}</span>
        </div>
      </article>
    </div>
  `;
  const group = document.createElement("section");
  group.className = "history-group";
  group.innerHTML = "<h3>最近历史记录</h3>";
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "当前项目还没有可检索历史。";
    group.append(empty);
  } else {
    for (const item of controlCenterDialogMatches(records).slice(0, 10)) {
      group.append(renderControlCenterDialogCard(item));
    }
  }
  page.append(group);
  // 跨项目引用内容区域
  const refs = state.crossReferences || [];
  if (refs.length) {
    const refGroup = document.createElement("section");
    refGroup.className = "history-group";
    refGroup.innerHTML = `<h3>跨项目引用内容（${refs.length} 条）</h3>`;
    for (const ref of refs) {
      refGroup.append(renderCrossReferenceCard(ref));
    }
    page.append(refGroup);
  }
  els.messages.append(page);
  els.messages.scrollTop = 0;
}

function renderCrossReferenceCard(ref) {
  const kindLabel = { work_report: "工作汇报", handoff_file: "工作交接文件", sync_package: "传承包" }[ref.source_record_type] || ref.source_record_type || "未知类型";
  const card = document.createElement("article");
  card.className = "history-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(ref.source_name || kindLabel)}</strong>
      <span>来源项目：${escapeHtml(ref.source_project_id || "")}</span>
      <span>类型：${escapeHtml(kindLabel)}</span>
      <span>record_id：${escapeHtml(ref.source_record_id || "")}</span>
      <span>${escapeHtml(firstLines(ref.source_excerpt || "", 2))}</span>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";
  if (ref.source_excerpt) {
    const viewBtn = document.createElement("button");
    viewBtn.type = "button";
    viewBtn.textContent = "查看详情";
    viewBtn.addEventListener("click", () => showContent(ref.source_name || "引用内容", ref.source_excerpt));
    actions.append(viewBtn);
  }
  if (ref.id) {
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "danger-btn";
    delBtn.textContent = "取消引用";
    delBtn.addEventListener("click", async () => {
      if (!confirm(`确认取消这条跨项目引用吗？\n来源：${ref.source_project_id} / ${ref.source_name}`)) return;
      try {
        await del(`/api/projects/${encodeURIComponent(projectId())}/cross-project-references/${encodeURIComponent(ref.id)}`);
        state.crossReferences = state.crossReferences.filter((item) => item.id !== ref.id);
        showControlCenterReports();
      } catch (error) {
        addMessage("assistant", `取消引用失败：${error.message}`);
      }
    });
    actions.append(delBtn);
  }
  card.append(actions);
  return card;
}

function renderPlatformControlCenterDashboard(data) {
  const summary = data.summary || {};
  const visibleProjectCount = visibleProjectIds().length;
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>账号级总控制中心</strong>
      <span>跨项目历史总览</span>
    </div>
    <div class="history-group">
      <h3>平台历史总览</h3>
      <article class="history-card">
        <div>
          <strong>全部项目</strong>
          <span>项目数：${visibleProjectCount}</span>
          <span>历史记录：${summary.record_count || 0}</span>
        </div>
      </article>
    </div>
    <div class="history-group">
      <h3>检索模式</h3>
      <article class="history-card">
        <div>
          <strong>跨项目 AI 检索</strong>
          <span>输入项目名、关键词、session_id 或 record_id</span>
          <span>总控制中心返回跨项目来源结果和打开入口。</span>
        </div>
      </article>
    </div>
  `;
  els.messages.append(page);
  els.messages.scrollTop = 0;
}

function renderControlCenterDialogCard(item) {
  const card = document.createElement("article");
  card.className = "history-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(item.name || dialogNameForSession(item.session_id))}</strong>
      <span>项目：${escapeHtml(item.project_id || "")}</span>
      <span>session_id：${escapeHtml(item.session_id || "未绑定 session")}</span>
      <span>命中来源：${escapeHtml((item.kinds || []).join("、"))}</span>
      <span>命中记录：${item.record_count || 1} 条</span>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";
  if (item.session_id) {
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.textContent = "打开对话框";
    openButton.addEventListener("click", () => openDialogBySession(item.session_id));
    actions.append(openButton);
  }
  card.append(actions);
  return card;
}

async function openDialogBySession(sessionId) {
  let dialog = activeProject().dialogs.find((item) => item.session?.id === sessionId);
  if (!dialog) {
    const session = await request(`/api/sessions/${encodeURIComponent(sessionId)}`);
    if (session.status === "deleted" || isDeletedProject(session.project_id)) {
      addMessage("assistant", "这个对话框或所属项目已删除，不再打开或参与统计。");
      return;
    }
    ensureProjectForId(session.project_id);
    state.activeProjectId = session.project_id;
    dialog = {
      id: `dialog_${session.id}`,
      name: session.title || "历史对话框",
      session,
    };
    activeProject().dialogs.push(dialog);
    saveState();
  }
  await openDialog(dialog.id);
}

function ensureProjectForId(projectIdValue) {
  if (!projectIdValue) return activeProject();
  if (isDeletedProject(projectIdValue)) return activeProject();
  let project = state.projects.find((item) => item.id === projectIdValue);
  if (!project) {
    project = { id: projectIdValue, name: projectIdValue, dialogs: [] };
    state.projects.push(project);
  }
  return project;
}

async function switchToProjectFromSearch(projectIdValue) {
  if (isDeletedProject(projectIdValue)) {
    addMessage("assistant", "这个项目已删除，不再打开或参与统计。");
    return;
  }
  ensureProjectForId(projectIdValue);
  state.activeProjectId = projectIdValue;
  state.activeDialogId = "control_center";
  state.session = null;
  saveState();
  renderShell();
  await showControlCenterReports();
}

async function showStartupPackage() {
  await loadStartupPackage();
  return {
    message: "已展示新对话框启动时会读取的工作交接文件和传承包。",
    data: { syncPackage: state.syncPackage },
  };
}

async function refreshProjectData() {
  await Promise.allSettled([
    syncProjectDialogsFromServer(),
    refreshArtifacts(false),
    refreshReports(false),
    refreshHandoffs(false),
  ]);
  renderShell();
}

async function syncProjectDialogsFromServer() {
  const data = await request(`/api/sessions?project_id=${encodeURIComponent(projectId())}`);
  const project = activeProject();
  project.dialogs = visibleDialogs(project);
  for (const session of data.items || []) {
    if (session.status === "deleted") continue;
    if (project.dialogs.some((dialog) => dialog.session?.id === session.id)) continue;
    project.dialogs.push({
      id: `dialog_${session.id}`,
      name: session.title || "历史对话框",
      session,
    });
  }
  saveState();
  return data;
}

async function refreshReports(showMessage = true) {
  const data = await request(`/api/work-reports?project_id=${encodeURIComponent(projectId())}`);
  state.reports = data.items || [];
  renderReports();
  return showMessage ? { message: `控制中心有 ${state.reports.length} 份工作汇报。`, data } : null;
}

async function refreshHandoffs() {
  const data = await request(`/api/handoff-files?project_id=${encodeURIComponent(projectId())}`);
  state.handoffs = data.items || [];
  renderStartupList();
  return { message: `本项目有 ${state.handoffs.length} 份工作交接文件。`, data };
}

async function refreshArtifacts(showMessage = true) {
  const data = await request(`/api/artifacts/files?project_id=${encodeURIComponent(projectId())}`);
  state.artifacts = data.items || [];
  renderArtifacts();
  return showMessage ? { message: `当前项目有 ${state.artifacts.length} 个工作区文件。`, data } : null;
}

async function refreshTraces() {
  const data = await request(`/api/langfuse/traces?project_id=${encodeURIComponent(projectId())}`);
  return {
    message: `当前项目有 ${data.items?.length || 0} 条 Prompt Trace。`,
    meta: "真实调用 GET /api/langfuse/traces",
    data,
  };
}

async function openPromptGovernancePage() {
  setBusy(true);
  try {
    // 第一步：先从本地数据库加载，立即渲染页面（快）
    const data = await request(`/api/projects/${encodeURIComponent(projectId())}/prompt-governance/overview`);
    data.langfusePrompts = {};  // 先占位，稍后异步填充
    renderPromptGovernancePage(data);

    // 第二步：异步从 Langfuse 云端拉取提示词（慢），拉取后自动更新编辑器
    setBusy(false);
    loadContextLangfusePrompts().then((langfusePrompts) => {
      data.langfusePrompts = langfusePrompts;
      updateContextPromptEditorCards(data);
    });

    return {
      message: null,
      meta: "提示词管理中心展示上下文处理类提示词、版本、平台绑定和调用 trace。",
      data,
    };
  } catch (error) {
    setBusy(false);
    throw error;
  }
}

async function loadContextLangfusePrompts() {
  const results = {};
  const settled = await Promise.allSettled(
    CONTEXT_PROMPT_DEFS.map((promptDef) =>
      request(`/api/langfuse/prompts/${encodeURIComponent(promptDef.code)}?label=production`)
    )
  );
  settled.forEach((result, index) => {
    const code = CONTEXT_PROMPT_DEFS[index].code;
    if (result.status === "fulfilled") {
      results[code] = result.value;
    } else {
      results[code] = { error: result.reason?.message || "读取失败" };
    }
  });
  return results;
}

function renderPromptGovernancePage(data) {
  clearMessages();
  els.workbenchTitle.textContent = "提示词管理中心";
  els.workbenchSubtitle.textContent = "只管理上下文总结、交接和传承包压缩相关提示词。";
  const summary = data.summary || {};
  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>${escapeHtml(activeProject().name)} / 提示词管理中心</strong>
      <span>project_id：${escapeHtml(data.project_id || projectId())}</span>
    </div>
    <div class="history-group">
      <h3>治理总览</h3>
      <article class="history-card">
        <div>
          <strong>Context Prompt Assets</strong>
          <span>模板：${summary.template_count || 0}</span>
          <span>版本：${summary.version_count || 0}</span>
          <span>平台绑定：${summary.binding_count || 0}</span>
          <span>调用 Trace：${summary.trace_count || 0}</span>
          <span>已发布模板：${summary.active_template_count || 0}</span>
        </div>
      </article>
    </div>
  `;
  const contextPromptGroup = document.createElement("section");
  contextPromptGroup.className = "history-group";
  contextPromptGroup.innerHTML = "<h3>上下文处理类提示词</h3>";
  for (const promptDef of CONTEXT_PROMPT_DEFS) {
    contextPromptGroup.append(renderContextPromptEditorCard(promptDef, data));
  }
  page.append(contextPromptGroup);

  const templateGroup = document.createElement("section");
  templateGroup.className = "history-group";
  templateGroup.innerHTML = "<h3>本地版本记录</h3>";
  if (!(data.templates || []).length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "当前项目还没有提示词模板。";
    templateGroup.append(empty);
  } else {
    for (const item of data.templates || []) {
      templateGroup.append(renderPromptTemplateCard(item, data));
    }
  }
  page.append(templateGroup);

  const traceGroup = document.createElement("section");
  traceGroup.className = "history-group";
  traceGroup.innerHTML = "<h3>最近提示词调用</h3>";
  if (!(data.traces || []).length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "当前项目还没有 prompt trace。";
    traceGroup.append(empty);
  } else {
    for (const trace of (data.traces || []).slice(0, 12)) {
      traceGroup.append(renderPromptTraceCard(trace));
    }
  }
  page.append(traceGroup);
  els.messages.append(page);
  els.messages.scrollTop = 0;
}

function renderPromptTemplateCard(item, data) {
  const versions = (data.versions || []).filter((version) => version.template_id === item.id);
  const active = versions.find((version) => version.id === item.active_version_id);
  const bindings = (data.bindings || []).filter((binding) => binding.template_id === item.id);
  const card = document.createElement("article");
  card.className = "history-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(item.prompt_code)}</strong>
      <span>${escapeHtml(item.name || "")}</span>
      <span>状态：${escapeHtml(item.status || "")}</span>
      <span>当前版本：${active ? `v${active.version_no}` : "未发布"}</span>
      <span>版本数：${versions.length}</span>
      <span>平台绑定：${bindings.map((binding) => `${binding.platform}:${binding.sync_status}`).join("，") || "无"}</span>
    </div>
  `;
  return card;
}

function renderContextPromptEditorCard(promptDef, data) {
  const template = (data.templates || []).find((item) => item.prompt_code === promptDef.code);
  const versions = template ? (data.versions || []).filter((version) => version.template_id === template.id) : [];
  const active = template ? versions.find((version) => version.id === template.active_version_id) : null;
  const langfuseData = data.langfusePrompts?.[promptDef.code];
  const langfuseContent = langfuseData?.prompt ? promptContentFromLangfuse(langfuseData.prompt) : "";
  const editorContent = active?.content || langfuseContent || "";
  const sourceLabel = active
    ? `本地 active v${active.version_no}`
    : langfuseContent
      ? "Langfuse production"
      : `未读取到提示词${langfuseData?.error ? `：${langfuseData.error}` : ""}`;
  const editorId = `prompt_editor_${promptDef.code}`;
  const card = document.createElement("article");
  card.className = "history-card prompt-editor-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(promptDef.name)}</strong>
      <span>prompt_code：${escapeHtml(promptDef.code)}</span>
      <span>${escapeHtml(promptDef.purpose)}</span>
      <span>本地状态：${template ? escapeHtml(template.status || "draft") : "未创建"}</span>
      <span>当前本地版本：${active ? `v${active.version_no}` : "无"}</span>
      <span id="source_label_${escapeHtml(promptDef.code)}">当前显示来源：${escapeHtml(sourceLabel)}</span>
      <textarea id="${editorId}" rows="10" spellcheck="false">${escapeHtml(editorContent)}</textarea>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";

  const fetchButton = document.createElement("button");
  fetchButton.type = "button";
  fetchButton.textContent = "读取 Langfuse production";
  fetchButton.addEventListener("click", () => loadLangfusePromptIntoEditor(promptDef.code, editorId));
  actions.append(fetchButton);

  const saveButton = document.createElement("button");
  saveButton.type = "button";
  saveButton.textContent = "保存并发布本地版本";
  saveButton.addEventListener("click", () => saveContextPromptVersion(promptDef, template, editorId));
  actions.append(saveButton);

  card.append(actions);
  return card;
}

function promptContentFromLangfuse(prompt) {
  if (Array.isArray(prompt.prompt)) return prompt.prompt.join("\n");
  return prompt.prompt || prompt.content || "";
}

function updateContextPromptEditorCards(data) {
  // Langfuse 数据异步返回后，更新编辑器卡片的内容和来源标签
  for (const promptDef of CONTEXT_PROMPT_DEFS) {
    const langfuseData = data.langfusePrompts?.[promptDef.code];
    if (!langfuseData || langfuseData.error) continue;
    const langfuseContent = promptContentFromLangfuse(langfuseData.prompt || {});
    if (!langfuseContent) continue;

    const editorId = `prompt_editor_${promptDef.code}`;
    const editor = document.querySelector(`#${CSS.escape(editorId)}`);
    const template = (data.templates || []).find((item) => item.prompt_code === promptDef.code);
    const versions = template ? (data.versions || []).filter((version) => version.template_id === template.id) : [];
    const active = template ? versions.find((version) => version.id === template.active_version_id) : null;

    // 如果本地没有 active 版本，就用 Langfuse 的内容填充编辑器
    if (!active && editor && !editor.value.trim()) {
      editor.value = langfuseContent;
    }

    // 更新来源标签
    const sourceSpan = document.querySelector(`#source_label_${CSS.escape(promptDef.code)}`);
    if (sourceSpan && langfuseContent && !active) {
      sourceSpan.textContent = "当前显示来源：Langfuse production（已缓存）";
    }
  }
}

async function loadLangfusePromptIntoEditor(promptCode, editorId) {
  setBusy(true);
  try {
    const data = await request(`/api/langfuse/prompts/${encodeURIComponent(promptCode)}?label=production`);
    const prompt = data.prompt || {};
    const content = promptContentFromLangfuse(prompt);
    const editor = document.querySelector(`#${CSS.escape(editorId)}`);
    if (editor) editor.value = content;
    addMessage("assistant", `已读取 Langfuse production：${promptCode}`);
  } catch (error) {
    addMessage("assistant", `读取 Langfuse production 失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function saveContextPromptVersion(promptDef, existingTemplate, editorId) {
  const editor = document.querySelector(`#${CSS.escape(editorId)}`);
  const content = editor?.value?.trim() || "";
  if (!content) {
    addMessage("assistant", "提示词内容不能为空。");
    return;
  }
  setBusy(true);
  try {
    let template = existingTemplate;
    if (!template) {
      template = await post("/api/prompts/templates", {
        prompt_code: promptDef.code,
        scope_level: "project",
        scope_id: projectId(),
        name: promptDef.name,
        description: promptDef.purpose,
        owner_id: actorId(),
      });
    }
    const version = await post(`/api/prompts/templates/${encodeURIComponent(template.id)}/versions`, {
      content,
      created_by: actorId(),
      change_note: "前端编辑上下文处理提示词",
      env: "test",
      variables_schema: {},
    });
    const published = await post(`/api/prompts/versions/${encodeURIComponent(version.id)}/publish`, {
      actor_id: actorId(),
    });
    addMessage("assistant", `已保存并发布：${promptDef.code} v${published.version_no}`);
    await openPromptGovernancePage();
  } catch (error) {
    addMessage("assistant", `保存提示词失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function renderPromptTraceCard(trace) {
  const card = document.createElement("article");
  card.className = "history-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(trace.operation || "prompt trace")}</strong>
      <span>prompt：${escapeHtml(trace.prompt_code || "builtin/langfuse")}${trace.version_no ? ` v${trace.version_no}` : ""}</span>
      <span>session_id：${escapeHtml(trace.session_id || "未绑定 session")}</span>
      <span>trace_id：${escapeHtml(trace.id || "")}</span>
      <span>tokens：${trace.total_tokens || 0}</span>
      <span>score：${trace.score ?? "未评分"}</span>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "查看输出";
  button.addEventListener("click", () => showContent(trace.operation || "Prompt Trace", trace.output_text || "暂无输出"));
  actions.append(button);
  card.append(actions);
  return card;
}

async function openHistoryPage() {
  setBusy(true);
  try {
    const [reportsResult, handoffsResult, syncResult] = await Promise.allSettled([
      request(`/api/work-reports?project_id=${encodeURIComponent(projectId())}`),
      request(`/api/handoff-files?project_id=${encodeURIComponent(projectId())}`),
      request(`/api/projects/${encodeURIComponent(projectId())}/sync-packages?package_type=project_master`),
    ]);
    const reports = reportsResult.status === "fulfilled" ? reportsResult.value.items || [] : [];
    const handoffs = handoffsResult.status === "fulfilled" ? handoffsResult.value.items || [] : [];
    const syncPackages = syncResult.status === "fulfilled" ? syncResult.value.items || [] : [];
    renderHistoryPage({ reports, handoffs, syncPackages });
  } catch (error) {
    addMessage("assistant", `历史文件中心打开失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function renderHistoryPage({ reports, handoffs, syncPackages }) {
  clearMessages();
  els.workbenchTitle.textContent = "历史文件中心";
  els.workbenchSubtitle.textContent = "按当前 Project 查看历史工作汇报、工作交接文件和传承包。";

  const page = document.createElement("section");
  page.className = "history-page";
  page.innerHTML = `
    <div class="history-page-head">
      <strong>${escapeHtml(activeProject().name)}</strong>
      <span>project_id：${escapeHtml(projectId())}</span>
    </div>
  `;

  const groups = [
    {
      title: "工作汇报文件",
      empty: "当前项目还没有工作汇报文件。",
      items: reports.map((item) =>
        historyItem("工作汇报文件.md", item.project_id, item.session_id, item.id, item.content, `/api/work-reports/${encodeURIComponent(item.id)}`)
      ),
    },
    {
      title: "工作交接文件",
      empty: "当前项目还没有工作交接文件。",
      items: handoffs.map((item) =>
        historyItem("工作交接文件.json", item.project_id, item.session_id, item.id, item.package_json, `/api/handoff-files/${encodeURIComponent(item.id)}`)
      ),
    },
    {
      title: "传承包",
      empty: "当前项目还没有传承包。",
      items: syncPackages.map((item) =>
        historyItem(
          `传承包_v${item.version_no}.md`,
          item.project_id,
          item.source_session_id,
          item.id,
          item.content,
          `/api/projects/${encodeURIComponent(item.project_id)}/sync-packages/${encodeURIComponent(item.id)}`
        )
      ),
    },
  ];

  for (const group of groups) {
    const block = document.createElement("section");
    block.className = "history-group";
    block.innerHTML = `<h3>${escapeHtml(group.title)}</h3>`;
    if (!group.items.length) {
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = group.empty;
      block.append(empty);
    } else {
      for (const item of group.items) block.append(renderHistoryCard(item));
    }
    page.append(block);
  }
  els.messages.append(page);
  els.messages.scrollTop = 0;
}

function historyItem(name, projectIdValue, sessionId, recordId, content, deletePath) {
  return {
    name,
    projectId: projectIdValue || projectId(),
    sessionId: sessionId || "未绑定 session",
    dialogName: dialogNameForSession(sessionId),
    recordId,
    content: content || "暂无内容",
    deletePath,
  };
}

function renderHistoryCard(item) {
  const card = document.createElement("article");
  card.className = "history-card";
  card.innerHTML = `
    <div>
      <strong>${escapeHtml(item.name)}</strong>
      <span>record_id：${escapeHtml(item.recordId || "")}</span>
      <span>project_id：${escapeHtml(item.projectId)}</span>
      <span>对话框：${escapeHtml(item.dialogName)}</span>
      <span>session_id：${escapeHtml(item.sessionId)}</span>
    </div>
  `;
  const actions = document.createElement("div");
  actions.className = "history-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "查看内容";
  button.addEventListener("click", () => showContent(item.name, item.content));
  actions.append(button);
  if (item.deletePath) {
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger-btn";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteHistoryItem(item));
    actions.append(deleteButton);
  }
  card.append(actions);
  return card;
}

async function deleteHistoryItem(item) {
  if (!confirm(`确认删除「${item.name}」吗？\nrecord_id：${item.recordId}`)) return;
  setBusy(true);
  try {
    await del(item.deletePath);
    closeFileModal();
    addMessage("assistant", `已删除：${item.name}`);
    await refreshProjectData();
    await openHistoryPage();
  } catch (error) {
    addMessage("assistant", `删除失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function dialogNameForSession(sessionId) {
  if (!sessionId) return "未绑定对话框";
  const found = activeProject().dialogs.find((dialog) => dialog.session?.id === sessionId);
  return found ? found.name : "历史对话框";
}

function renderReports() {
  els.reportList.innerHTML = "";
  if (!state.reports.length) {
    els.reportList.innerHTML = '<div class="empty">还没有工作汇报</div>';
    return;
  }
  for (const item of state.reports.slice(0, 6)) {
    const button = document.createElement("button");
    button.className = "list-item file-item";
    button.type = "button";
    button.textContent = `工作汇报文件.md`;
    button.addEventListener("click", () => showContent("工作汇报文件.md", item.content));
    els.reportList.append(button);
  }
}

function renderStartupList() {
  els.startupList.innerHTML = "";
  const nodes = [];
  if (state.handoffs[0]) {
    nodes.push({ name: "工作交接文件.json", content: state.handoffs[0].package_json });
  }
  if (state.syncPackage) {
    nodes.push({ name: `传承包_v${state.syncPackage.version_no}.md`, content: state.syncPackage.content });
  }
  if (!nodes.length) {
    els.startupList.innerHTML = '<div class="empty">还没有交接文件和传承包</div>';
    return;
  }
  for (const item of nodes) {
    const button = document.createElement("button");
    button.className = "list-item file-item";
    button.type = "button";
    button.textContent = item.name;
    button.addEventListener("click", () => showContent(item.name, item.content));
    els.startupList.append(button);
  }
}

function renderArtifacts() {
  els.artifactList.innerHTML = "";
  if (!state.artifacts.length) {
    els.artifactList.innerHTML = '<div class="empty">还没有文件</div>';
    return;
  }
  for (const item of state.artifacts.slice(0, 8)) {
    const button = document.createElement("button");
    button.className = "list-item file-item";
    button.type = "button";
    button.textContent = artifactName(item);
    button.addEventListener("click", () => showContent(artifactName(item), item.content || "这个文件暂无预览内容。"));
    els.artifactList.append(button);
  }
}

function showContent(name, content) {
  openFileModal(name, content || "暂无内容");
  addMessage("assistant", `已打开 ${name}。`);
}

function openFileModal(title, content) {
  els.fileModalTitle.textContent = title || "文件内容";
  els.fileModalContent.textContent = content || "暂无内容";
  els.fileModalBackdrop.hidden = false;
}

function closeFileModal() {
  els.fileModalBackdrop.hidden = true;
}

function artifactName(item) {
  if (item.artifact_type === "work_report") return "工作汇报文件.md";
  if (item.artifact_type === "handoff_file" || item.artifact_type === "handoff_package") return "工作交接文件.json";
  if (item.artifact_type === "sync_package") return `传承包${extractVersionFromTitle(item.title) ? `_${extractVersionFromTitle(item.title)}` : ""}.md`;
  return item.title || item.id || "工作区文件";
}

function extractVersionFromTitle(title = "") {
  const match = String(title).match(/v\d+/i);
  return match ? match[0] : "";
}

function firstLines(text, count) {
  return String(text || "").split("\n").slice(0, count).join("\n");
}

function help() {
  return {
    message: [
      "当前结构：",
      "1. 左侧选择或新建 Project，项目之间用 project_id 隔离。",
      "2. 每个 Project 下有一个控制中心和多个普通对话框。",
      "3. 普通对话框可以直接和 AI 对话；输入 /收口 可模拟超过 85% 后生成工作汇报、工作交接文件、传承包。",
      "4. 工作汇报交给控制中心查询。",
      "5. 工作交接文件和传承包交给同项目下新建对话框启动读取。",
    ].join("\n"),
    data: {},
  };
}

els.newProjectBtn.addEventListener("click", createProject);
els.newDialogBtn.addEventListener("click", createDialog);
els.quickNewDialogBtn.addEventListener("click", createDialog);
if (els.platformControlCenterBtn) {
  els.platformControlCenterBtn.addEventListener("click", showPlatformControlCenter);
}
els.controlCenterBtn.addEventListener("click", showControlCenterReports);
els.historyPageBtn.addEventListener("click", openHistoryPage);
els.promptCenterBtn.addEventListener("click", openPromptGovernancePage);
els.projectSelect.addEventListener("change", (event) => switchProject(event.target.value));
els.fileModalClose.addEventListener("click", closeFileModal);
els.fileModalBackdrop.addEventListener("click", (event) => {
  if (event.target === els.fileModalBackdrop) closeFileModal();
});

els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.chatInput.value;
  els.chatInput.value = "";
  handleUserMessage(text);
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    els.chatInput.value = button.dataset.prompt;
    els.chatForm.requestSubmit();
  });
});

els.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

loadState();
renderShell();
checkHealth();
refreshProjectData();
addMessage("assistant", help().message);
