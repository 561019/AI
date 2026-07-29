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
  task_name: string;
  task_type: string;
  target_engine: string;
  engine_code: string;
  required_inputs: string[];
  missing_inputs: string[];
  dependencies: string[];
  execution_order: number;
  confidence: number;
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
