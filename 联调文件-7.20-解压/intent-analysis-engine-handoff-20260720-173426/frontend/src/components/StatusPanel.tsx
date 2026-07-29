import type { HealthResponse } from "../api/client";

type StatusPanelProps = {
  health: HealthResponse | null;
  error: string | null;
};

export function StatusPanel({ health, error }: StatusPanelProps) {
  if (error) {
    return (
      <section className="panel status-panel">
        <span className="status-dot status-dot--error" />
        <div>
          <h2>Backend offline</h2>
          <p>{error}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel status-panel">
      <span className="status-dot" />
      <div>
        <h2>{health ? "Backend online" : "Checking backend"}</h2>
        <p>{health ? `${health.service} ${health.version} (${health.environment})` : "Waiting for response"}</p>
      </div>
    </section>
  );
}
