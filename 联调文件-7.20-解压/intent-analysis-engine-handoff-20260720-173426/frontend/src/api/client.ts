const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
  environment: string;
};

export type IntentAnalyzeRequest = {
  text: string;
  user_id: string;
  conversation_id: string;
};

export type TaskItem = {
  task_id: string;
  function_code: string;
  function_name: string;
  intent_category: string;
  target_engine: string;
  parameters: Record<string, unknown>;
  dependency: string[];
  priority: number;
  confidence: number;
};

export type TaskList = {
  request_id: string;
  user_id: string;
  tasks: TaskItem[];
  analysis_level: number;
  overall_confidence: number;
  created_at: string;
};

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown> | null;
};

export type ApiResponse<T> = {
  success: boolean;
  data: T | null;
  error: ApiError | null;
};

export type IntentAnalyzeResponse = ApiResponse<TaskList>;

export type IntentRecordItem = {
  id: string;
  request_text: string;
  user_id: string;
  conversation_id: string;
  analysis_level: string;
  matched_function: string | null;
  confidence: number | null;
  result: string;
  cost_time: number | null;
  created_at: string;
};

export type IntentHistoryData = {
  records: IntentRecordItem[];
  count: number;
  limit: number;
  offset: number;
};

export type IntentHistoryResponse = ApiResponse<IntentHistoryData>;

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  const payload = (await response.json().catch(() => null)) as T | null;

  if (!response.ok) {
    if (payload && typeof payload === "object" && "success" in payload) {
      return payload;
    }
    throw new Error(`Request failed with status ${response.status}`);
  }

  return payload as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export function analyzeIntent(payload: IntentAnalyzeRequest): Promise<IntentAnalyzeResponse> {
  return requestJson<IntentAnalyzeResponse>("/v1/intent/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getIntentHistory(params?: {
  user_id?: string;
  analysis_level?: string;
  limit?: number;
  offset?: number;
}): Promise<IntentHistoryResponse> {
  const searchParams = new URLSearchParams();
  if (params?.user_id) {
    searchParams.set("user_id", params.user_id);
  }
  if (params?.analysis_level) {
    searchParams.set("analysis_level", params.analysis_level);
  }
  if (params?.limit) {
    searchParams.set("limit", String(params.limit));
  }
  if (params?.offset) {
    searchParams.set("offset", String(params.offset));
  }

  const query = searchParams.toString();
  return requestJson<IntentHistoryResponse>(`/v1/intent/history${query ? `?${query}` : ""}`);
}
