import { useMemo, useState } from "react";

import { analyzeIntent, getAnalysisLevel, type IntentAnalyzeResponse, type TaskItem } from "../api/intent";

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

const ENGINE_ORDER = [
  "ENG_DOCUMENT_TABLE_PARSING",
  "ENG_EXTERNAL_SYSTEM_CONNECTOR",
  "ENG_DATA_COLLECTION_AGGREGATION",
  "ENG_RULE_CALCULATION",
  "ENG_ANALYTICS_FORECASTING",
  "ENG_KNOWLEDGE_QA",
  "ENG_CONTENT_OUTPUT",
  "ENG_MULTIMEDIA_GENERATION",
  "ENG_WORKFLOW_EXECUTION",
  "ENG_MONITORING_REMINDER",
  "ENG_DIGITAL_ASSET",
];

const ENGINE_NAMES: Record<string, string> = {
  ENG_DOCUMENT_TABLE_PARSING: "文档表格解析",
  ENG_EXTERNAL_SYSTEM_CONNECTOR: "外部系统对接",
  ENG_DATA_COLLECTION_AGGREGATION: "数据归集聚合",
  ENG_RULE_CALCULATION: "规则计算",
  ENG_ANALYTICS_FORECASTING: "分析预测",
  ENG_KNOWLEDGE_QA: "知识库问答",
  ENG_CONTENT_OUTPUT: "内容产出",
  ENG_MULTIMEDIA_GENERATION: "多媒体生成",
  ENG_WORKFLOW_EXECUTION: "流程执行",
  ENG_MONITORING_REMINDER: "监控提醒",
  ENG_DIGITAL_ASSET: "数字资产",
};

export function IntentTestConsole() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IntentAnalyzeResponse | null>(null);
  const [copyState, setCopyState] = useState("复制 JSON");

  const data = result?.data ?? null;
  const tasks = useMemo(() => sortTasks(data?.tasks ?? []), [data?.tasks]);
  const analysisLevel = useMemo(() => getAnalysisLevel(result), [result]);
  const usedEngines = useMemo(() => new Set(tasks.map((task) => task.engine_code)), [tasks]);
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
          <span>业务执行未调用</span>
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
        <EngineCoverage usedEngines={usedEngines} />
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
                <div className="task-route-line">
                  <span>{task.engine_code}</span>
                  <strong>{task.target_engine}</strong>
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

function EngineCoverage({ usedEngines }: { usedEngines: Set<string> }) {
  return (
    <aside className="engine-panel" aria-labelledby="engine-coverage-title">
      <div className="panel-heading">
        <div>
          <p>Function Registry</p>
          <h2 id="engine-coverage-title">目标引擎匹配</h2>
        </div>
      </div>

      <div className="engine-grid">
        {ENGINE_ORDER.map((engineCode, index) => {
          const active = usedEngines.has(engineCode);
          return (
            <div key={engineCode} className={["engine-cell", active ? "engine-cell--active" : ""].join(" ")}>
              <span>{String(index + 2).padStart(2, "0")}</span>
              <strong>{ENGINE_NAMES[engineCode]}</strong>
              <small>{engineCode}</small>
            </div>
          );
        })}
      </div>
    </aside>
  );
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

function sortTasks(tasks: TaskItem[]) {
  return [...tasks].sort((left, right) => left.execution_order - right.execution_order);
}
