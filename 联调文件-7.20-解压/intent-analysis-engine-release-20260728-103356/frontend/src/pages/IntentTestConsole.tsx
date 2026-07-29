import { useMemo, useState } from "react";

import {
  analyzeIntent,
  cancelTasklist,
  confirmTasklist,
  getAnalysisLevel,
  type IntentAnalyzeResponse,
  type TaskItem,
  type TaskListConfirmation,
  type TaskListConfirmationView,
} from "../api/intent";

const EXAMPLES = [
  "解析上传的销售明细Excel表格",
  "从CRM系统获取客户资料",
  "按区域汇总本月销售金额",
  "根据销售提成政策计算上个月销售提成",
  "预测下季度销售额趋势",
  "公司的报销政策是什么？",
  "写一份会议通知",
  "生成一张新品发布海报",
  "发起采购审批流程",
  "库存低于100时提醒我",
  "根据本月提成计算结果生成计提凭证",
  "统计销售金额",
  "整理客户投诉并生成改进方案",
];

export function IntentTestConsole() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IntentAnalyzeResponse | null>(null);
  const [copyState, setCopyState] = useState("复制 JSON");
  const [confirmationLoading, setConfirmationLoading] = useState<"confirm" | "cancel" | null>(null);
  const [confirmationError, setConfirmationError] = useState<string | null>(null);

  const data = result?.data ?? null;
  const tasks = useMemo(() => sortTasks(data?.tasks ?? []), [data?.tasks]);
  const analysisLevel = useMemo(() => getAnalysisLevel(result), [result]);
  const confirmation = result?.confirmation ?? null;
  const confirmationLabel = getConfirmationLabel(confirmation?.confirmation_status ?? null);
  const confidence = Math.round((data?.overall_confidence ?? 0) * 100);

  async function handleAnalyze(nextText = text) {
    const normalizedText = nextText.trim();
    if (!normalizedText) {
      setError("请输入测试语句");
      setResult(null);
      return;
    }

    setText(normalizedText);
    setLoading(true);
    setError(null);
    setConfirmationError(null);
    setConfirmationLoading(null);
    setCopyState("复制 JSON");

    try {
      const response = await analyzeIntent(normalizedText);
      setResult(response);
      if (response.success === false && response.error?.message) {
        setError(response.error.message);
      }
    } catch (requestError) {
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopyJson() {
    const payload = result ?? { status: "waiting_for_request" };
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    setCopyState("已复制");
    window.setTimeout(() => setCopyState("复制 JSON"), 1400);
  }

  async function handleConfirmTasklist() {
    if (!confirmation) {
      return;
    }
    await submitTasklistConfirmation("confirm", confirmation);
  }

  async function handleCancelTasklist() {
    if (!confirmation) {
      return;
    }
    await submitTasklistConfirmation("cancel", confirmation);
  }

  async function submitTasklistConfirmation(action: "confirm" | "cancel", current: TaskListConfirmation) {
    setConfirmationLoading(action);
    setConfirmationError(null);
    try {
      const view = action === "confirm" ? await confirmTasklist(current) : await cancelTasklist(current);
      setResult((previous) => mergeConfirmationView(previous, view));
    } catch (requestError) {
      setConfirmationError(requestError instanceof Error ? requestError.message : "任务清单确认失败");
    } finally {
      setConfirmationLoading(null);
    }
  }

  return (
    <main className="platform-page">
      <header className="platform-topbar">
        <div>
          <p className="eyebrow">Intent Analysis Engine</p>
          <h1>自然语言意图分析平台</h1>
        </div>
        <div className="topbar-status" aria-label="运行状态">
          <span>{loading ? "分析中" : result ? "已完成" : "待分析"}</span>
          <span>{data ? (data.clarification_required ? "需要澄清" : "标准输出") : "待分析"}</span>
          <span>{confirmationLabel}</span>
        </div>
      </header>

      <section className="platform-workbench" aria-label="意图分析工作台">
        <div className="input-panel">
          <div className="panel-heading">
            <div>
              <p>请求输入</p>
              <h2>用户自然语言</h2>
            </div>
            <span className="request-chip">test_session</span>
          </div>

          <form
            className="analysis-form"
            onSubmit={(event) => {
              event.preventDefault();
              void handleAnalyze();
            }}
          >
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="输入用户请求"
              rows={7}
            />

            <div className="analysis-actions">
              <button type="submit" className="primary-action" disabled={loading || !text.trim()}>
                {loading ? "分析中" : "分析"}
              </button>
              <button type="button" className="secondary-action" onClick={handleCopyJson} disabled={!result}>
                {copyState}
              </button>
            </div>
          </form>

          <div className="example-strip" aria-label="示例请求">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" onClick={() => void handleAnalyze(example)} disabled={loading}>
                {example}
              </button>
            ))}
          </div>
        </div>

        <div className="insight-panel">
          <MetricGrid
            level={analysisLevel}
            taskCount={tasks.length}
            confidence={confidence}
            analyzed={Boolean(result)}
            clarificationRequired={Boolean(data?.clarification_required)}
          />
        </div>
      </section>

      <section className="task-layout" aria-label="标准任务清单">
        <TaskRouteBoard tasks={tasks} />
        <TasklistConfirmationPanel
          confirmation={confirmation}
          loadingAction={confirmationLoading}
          error={confirmationError}
          onConfirm={() => void handleConfirmTasklist()}
          onCancel={() => void handleCancelTasklist()}
        />
      </section>

      <section className="detail-layout" aria-label="分析明细">
        <ClarificationPanel result={result} error={error} />
        <JsonPanel result={result} error={error} />
      </section>
    </main>
  );
}

function MetricGrid({
  level,
  taskCount,
  confidence,
  analyzed,
  clarificationRequired,
}: {
  level: 1 | 2 | 3 | null;
  taskCount: number;
  confidence: number;
  analyzed: boolean;
  clarificationRequired: boolean;
}) {
  return (
    <div className="metric-grid" aria-label="分析指标">
      <div className="metric-tile">
        <span>命中层级</span>
        <strong>{level ? `L${level}` : "-"}</strong>
      </div>
      <div className="metric-tile">
        <span>任务数量</span>
        <strong>{taskCount}</strong>
      </div>
      <div className="metric-tile">
        <span>置信度</span>
        <strong>{confidence}%</strong>
      </div>
      <div className={["metric-tile", analyzed && clarificationRequired ? "metric-tile--warning" : ""].filter(Boolean).join(" ")}>
        <span>澄清状态</span>
        <strong>{analyzed ? (clarificationRequired ? "需要" : "无需") : "待分析"}</strong>
      </div>
    </div>
  );
}

function TaskRouteBoard({ tasks }: { tasks: TaskItem[] }) {
  return (
    <section className="route-panel" aria-labelledby="task-route-title">
      <div className="panel-heading">
        <div>
          <p>Intent Analysis Result</p>
          <h2 id="task-route-title">标准任务清单</h2>
        </div>
      </div>

      {tasks.length ? (
        <div className="task-timeline">
          {tasks.map((task) => (
            <article className="task-row" key={task.task_id}>
              <div className="task-order">{task.execution_order}</div>
              <div className="task-main">
                <div className="task-title-line">
                  <h3>{task.task_name}</h3>
                  <span>{task.task_type}</span>
                </div>
                <InputList title="已识别输入" values={task.required_inputs} emptyText="无显式输入" />
                <InputList title="缺失输入" values={task.missing_inputs} emptyText="无缺失" warning />
              </div>
              <div className="confidence-meter" aria-label={`置信度 ${Math.round(task.confidence * 100)}%`}>
                <span style={{ width: `${Math.round(task.confidence * 100)}%` }} />
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">暂无任务</div>
      )}
    </section>
  );
}

function InputList({
  title,
  values,
  emptyText,
  warning = false,
}: {
  title: string;
  values: string[];
  emptyText: string;
  warning?: boolean;
}) {
  return (
    <div className={["input-list", warning ? "input-list--warning" : ""].filter(Boolean).join(" ")}>
      <span>{title}</span>
      <div>
        {values.length ? values.map((value) => <em key={value}>{value}</em>) : <em>{emptyText}</em>}
      </div>
    </div>
  );
}

function TasklistConfirmationPanel({
  confirmation,
  loadingAction,
  error,
  onConfirm,
  onCancel,
}: {
  confirmation: TaskListConfirmation | null;
  loadingAction: "confirm" | "cancel" | null;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const status = confirmation?.confirmation_status ?? null;
  const pending = status === "pending";
  const statusClass = [
    "status-pill",
    status === "waiting_clarification" ? "status-pill--warning" : "",
    status === "confirmed" ? "status-pill--success" : "",
    status === "cancelled" ? "status-pill--danger" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <aside className="confirmation-panel" aria-labelledby="tasklist-confirmation-title">
      <div className="panel-heading">
        <div>
          <p>TaskList Confirmation</p>
          <h2 id="tasklist-confirmation-title">任务清单确认</h2>
        </div>
        <span className={statusClass}>{getConfirmationLabel(status)}</span>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="confirmation-body">
        <p>{getConfirmationDetail(status)}</p>
        {confirmation ? (
          <dl className="confirmation-meta">
            <div>
              <dt>确认编号</dt>
              <dd>{confirmation.confirmation_id}</dd>
            </div>
            <div>
              <dt>清单版本</dt>
              <dd>{confirmation.tasklist_version}</dd>
            </div>
          </dl>
        ) : null}

        {pending ? (
          <div className="confirmation-actions">
            <button type="button" className="primary-action" onClick={onConfirm} disabled={Boolean(loadingAction)}>
              {loadingAction === "confirm" ? "确认中" : "确认任务清单"}
            </button>
            <button type="button" className="secondary-action" onClick={onCancel} disabled={Boolean(loadingAction)}>
              {loadingAction === "cancel" ? "取消中" : "取消"}
            </button>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function getConfirmationLabel(status: TaskListConfirmation["confirmation_status"] | null) {
  switch (status) {
    case "waiting_clarification":
      return "等待澄清";
    case "pending":
      return "待确认";
    case "confirmed":
      return "已确认";
    case "cancelled":
      return "已取消";
    default:
      return "待生成";
  }
}

function getConfirmationDetail(status: TaskListConfirmation["confirmation_status"] | null) {
  switch (status) {
    case "waiting_clarification":
      return "任务清单还有缺失信息，补充澄清后再确认。";
    case "pending":
      return "请检查上方任务清单是否符合用户真实意图。";
    case "confirmed":
      return "任务清单已确认，可以进入后续业务流程。";
    case "cancelled":
      return "任务清单已取消，不会继续流转。";
    default:
      return "分析完成后会生成待确认的任务清单。";
  }
}

function ClarificationPanel({ result, error }: { result: IntentAnalyzeResponse | null; error: string | null }) {
  const questions = result?.data?.clarification_questions ?? [];

  return (
    <section className="clarification-panel" aria-labelledby="clarification-title">
      <div className="panel-heading">
        <div>
          <p>Clarification</p>
          <h2 id="clarification-title">信息完整性</h2>
        </div>
        <span className={questions.length ? "status-pill status-pill--warning" : "status-pill"}>
          {questions.length ? "需要补充" : "完整"}
        </span>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {questions.length ? (
        <ol className="question-list">
          {questions.map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ol>
      ) : (
        <div className="empty-state">当前没有澄清问题</div>
      )}
    </section>
  );
}

function JsonPanel({ result, error }: { result: IntentAnalyzeResponse | null; error: string | null }) {
  const displayValue = result
    ? JSON.stringify(result, null, 2)
    : error
      ? JSON.stringify({ success: false, error }, null, 2)
      : "{\n  \"status\": \"waiting_for_request\"\n}";

  return (
    <section className="json-panel" aria-labelledby="json-title">
      <div className="panel-heading">
        <div>
          <p>Raw Output</p>
          <h2 id="json-title">标准 JSON</h2>
        </div>
      </div>
      <pre className="json-viewer">{displayValue}</pre>
    </section>
  );
}

function mergeConfirmationView(
  previous: IntentAnalyzeResponse | null,
  view: TaskListConfirmationView,
): IntentAnalyzeResponse {
  return {
    ...(previous ?? { success: true }),
    success: true,
    data: view.data,
    confirmation: view.confirmation,
    error: null,
  };
}

function sortTasks(tasks: TaskItem[]) {
  return [...tasks].sort((left, right) => (left.execution_order ?? 0) - (right.execution_order ?? 0));
}
