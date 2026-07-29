const API_BASE_URL = normalizeApiBase(import.meta.env.VITE_API_BASE_URL ?? "");

export type AnalyzeIntentRequest = {
  text: string;
  user_id?: string;
  conversation_id?: string;
  history?: ConversationHistoryItem[];
};

export type ConversationHistoryItem = {
  role: "user" | "assistant";
  text: string;
};

export type IntentApiError = {
  code?: string;
  message?: string;
  details?: Record<string, unknown> | null;
};

export type IntentAnalyzeResponse = {
  success?: boolean;
  data?: IntentAnalysisResult | null;
  confirmation?: TaskListConfirmation | null;
  error?: IntentApiError | null;
  debug?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type NormalizedAnalysisLevel = 1 | 2 | 3 | null;

export type IntentAnalysisResult = {
  request_id: string;
  original_text: string;
  intent_category: string;
  tasks: TaskItem[];
  clarification_required: boolean;
  clarification_questions: string[];
  analysis_level: number;
  overall_confidence: number;
  created_at: string;
};

export type TaskItem = {
  task_id: string;
  task_type: string;
  task_name?: string;
  task_description?: string;
  action?: string;
  object?: string;
  target_engine?: string;
  engine_code?: string;
  required_inputs: string[];
  missing_inputs: string[];
  dependencies: string[];
  execution_order?: number;
  confidence: number;
};

export type TaskListConfirmationStatus = "waiting_clarification" | "pending" | "confirmed" | "cancelled";

export type TaskListConfirmation = {
  confirmation_id: string;
  tasklist_version: string;
  confirmation_required: boolean;
  confirmation_status: TaskListConfirmationStatus;
  modification_count: number;
  created_at: string;
  updated_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  cancelled_by: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
};

export type TaskListConfirmationView = {
  confirmation: TaskListConfirmation;
  data: IntentAnalysisResult;
};

function buildApiUrl(path: string) {
  if (API_BASE_URL.endsWith("/api") && path.startsWith("/api/")) {
    return `${API_BASE_URL}${path.slice(4)}`;
  }
  return `${API_BASE_URL}${path}`;
}

function normalizeApiBase(baseUrl: string) {
  return baseUrl.trim().replace(/\/$/, "");
}

export async function analyzeIntent(
  text: string,
  conversation: Omit<AnalyzeIntentRequest, "text"> = {},
): Promise<IntentAnalyzeResponse> {
  const response = await fetch(buildApiUrl("/api/v1/intent/analyze"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text,
      user_id: "test_user",
      conversation_id: "test_session",
      ...conversation,
    } satisfies AnalyzeIntentRequest),
  });

  const payload = (await response.json().catch(() => null)) as IntentAnalyzeResponse | null;

  if (!response.ok && !payload) {
    throw new Error(`HTTP ${response.status}: ${response.statusText || "request failed"}`);
  }

  if (!payload) {
    throw new Error("API did not return JSON");
  }

  if (!response.ok) {
    return payload;
  }

  return payload;
}

export async function confirmTasklist(
  confirmation: TaskListConfirmation,
  confirmedBy = "test_user",
): Promise<TaskListConfirmationView> {
  return requestTasklistConfirmation(
    `/api/v1/intent/tasklist-confirmations/${confirmation.confirmation_id}/confirm`,
    {
      tasklist_version: confirmation.tasklist_version,
      confirmed_by: confirmedBy,
    },
  );
}

export async function cancelTasklist(
  confirmation: TaskListConfirmation,
  cancelledBy = "test_user",
): Promise<TaskListConfirmationView> {
  return requestTasklistConfirmation(
    `/api/v1/intent/tasklist-confirmations/${confirmation.confirmation_id}/cancel`,
    {
      tasklist_version: confirmation.tasklist_version,
      cancelled_by: cancelledBy,
    },
  );
}

async function requestTasklistConfirmation(
  path: string,
  body: Record<string, string>,
): Promise<TaskListConfirmationView> {
  const response = await fetch(buildApiUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => null)) as
    | TaskListConfirmationView
    | IntentApiError
    | null;

  if (!response.ok) {
    const message = payload && "message" in payload ? payload.message : null;
    throw new Error(message || "Task list confirmation failed");
  }
  if (!payload || !("confirmation" in payload) || !("data" in payload)) {
    throw new Error("Task list confirmation API did not return JSON");
  }
  return payload;
}

export function getAnalysisLevel(result: IntentAnalyzeResponse | null): NormalizedAnalysisLevel {
  if (!result) {
    return null;
  }

  return (
    normalizeLevel(readPath(result, ["data", "analysis_level"])) ??
    normalizeLevel(readPath(result, ["data", "level"])) ??
    normalizeLevel(readPath(result, ["data", "intent_level"])) ??
    normalizeLevel(readPath(result, ["debug", "final_tasklist", "analysis_level"])) ??
    normalizeLevel(readPath(result, ["debug", "final_tasklist", "level"])) ??
    normalizeLevel(readPath(result, ["debug", "final_tasklist", "intent_level"])) ??
    normalizeLevel(readPath(result, ["error", "details", "analysis_level"])) ??
    normalizeLevel(readPath(result, ["error", "details", "level"])) ??
    normalizeLevel(readPath(result, ["error", "details", "intent_level"])) ??
    inferLevelFromDebug(result.debug ?? null)
  );
}

function inferLevelFromDebug(debug: Record<string, unknown> | null): NormalizedAnalysisLevel {
  if (!debug) {
    return null;
  }

  if (debug.level3_result) {
    return 3;
  }
  if (debug.level2_result) {
    return 2;
  }
  if (debug.level1_result) {
    return 1;
  }
  return null;
}

function normalizeLevel(value: unknown): NormalizedAnalysisLevel {
  if (value === null || value === undefined) {
    return null;
  }

  const numericValue = typeof value === "number" ? value : Number(String(value).replace(/level/i, "").trim());
  if (numericValue === 1 || numericValue === 2 || numericValue === 3) {
    return numericValue;
  }
  return null;
}

function readPath(source: unknown, path: string[]): unknown {
  let current = source;
  for (const key of path) {
    if (!current || typeof current !== "object" || !(key in current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}
