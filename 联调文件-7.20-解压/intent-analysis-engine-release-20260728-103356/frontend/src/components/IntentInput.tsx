import type { FormEvent } from "react";

type IntentInputProps = {
  value: string;
  loading: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
};

const EXAMPLES = ["帮我整理经营情况", "生成销售报告"];

export function IntentInput({ value, loading, onChange, onSubmit }: IntentInputProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section className="console-section input-section" aria-labelledby="intent-input-title">
      <div className="section-heading">
        <h2 id="intent-input-title">测试语句</h2>
      </div>

      <form className="intent-form" onSubmit={handleSubmit}>
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="例如：帮我整理经营情况"
          rows={5}
          autoFocus
        />

        <div className="input-actions">
          <div className="example-actions" aria-label="测试语句示例">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                className="example-button"
                onClick={() => onChange(example)}
                disabled={loading}
              >
                {example}
              </button>
            ))}
          </div>

          <button type="submit" className="send-button" disabled={loading || !value.trim()}>
            {loading ? "分析中" : "发送"}
          </button>
        </div>
      </form>
    </section>
  );
}
