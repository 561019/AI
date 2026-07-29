import type { IntentAnalyzeResponse } from "../api/intent";

type ResultViewerProps = {
  result: IntentAnalyzeResponse | null;
  error: string | null;
};

export function ResultViewer({ result, error }: ResultViewerProps) {
  const displayValue = result
    ? JSON.stringify(result, null, 2)
    : error
      ? JSON.stringify({ success: false, error }, null, 2)
      : "{\n  \"status\": \"waiting_for_request\"\n}";

  return (
    <section className="console-section result-section" aria-labelledby="result-viewer-title">
      <div className="section-heading">
        <h2 id="result-viewer-title">完整结果</h2>
        {error ? <span className="error-chip">{error}</span> : null}
      </div>

      <pre className="json-viewer">{displayValue}</pre>
    </section>
  );
}
