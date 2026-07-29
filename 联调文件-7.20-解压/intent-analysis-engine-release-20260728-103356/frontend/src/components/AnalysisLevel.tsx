import type { IntentAnalyzeResponse, NormalizedAnalysisLevel } from "../api/intent";

type AnalysisLevelProps = {
  level: NormalizedAnalysisLevel;
  result: IntentAnalyzeResponse | null;
  loading: boolean;
};

export function AnalysisLevel({ level, result, loading }: AnalysisLevelProps) {
  const taskCount = result?.data?.tasks?.length ?? 0;

  return (
    <section className="console-section level-section" aria-labelledby="analysis-level-title">
      <div className="section-heading">
        <h2 id="analysis-level-title">判断等级</h2>
        <span className="level-summary">{loading ? "分析中" : level ? `本次分析：Level ${level}` : "等待分析"}</span>
      </div>

      <div className="level-summary-panel" aria-label="本次判断等级">
        <strong>{level ? `Level ${level}` : "-"}</strong>
        <span>标准任务数量：{taskCount}</span>
      </div>
    </section>
  );
}
