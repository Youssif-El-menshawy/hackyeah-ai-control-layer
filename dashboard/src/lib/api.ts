import type { BenchmarkReport } from "./benchmark";

export type Decision = "ALLOW" | "REDACT" | "BLOCK" | "REQUIRE_APPROVAL";

export type EventRecord = {
  evaluation_id: string;
  request_id: string;
  input_sha256: string;
  agent_id: string;
  model: string;
  input_type: "prompt" | "tool_call";
  tool_name?: string | null;
  decision: Decision;
  reason_codes: string[];
  policy_version: string;
  redactions: { kind: string; count: number }[];
  risk_signals: { label: string; score: number }[];
  semantic_failure?: string | null;
  estimated_input_tokens: number;
  latency_ms: number;
  created_at: string;
};

export type PolicyMetadata = {
  policy_id: string;
  schema_version: string;
  policy_version: string;
  loaded_at: string;
};

export type Approval = {
  approval_id: string;
  evaluation_id: string;
  status: "PENDING" | "APPROVED" | "DENIED";
  resolved_by?: string | null;
  resolution_reason?: string | null;
  created_at: string;
};

export type BudgetUsage = {
  agent_id: string;
  requests: number;
  input_tokens: number;
  max_requests: number;
  max_input_tokens: number;
};

export type TestRunSummary = {
  passed: number;
  failed: number;
  skipped: number;
  total: number;
  duration_seconds: number;
  completed_at: string;
  status: "passed" | "failed" | "incomplete";
};

export type PolicyOverview = PolicyMetadata & {
  semantic_provider: string; semantic_model: string | null; allowed_models: string[];
  enabled_detectors: string[];
  thresholds: { fact: string; operator: string; value: number; rule_id: string; action: Decision; priority: number; compound: boolean; mode: string }[];
  agents: Record<string, { allowed_tools: string[]; denied_tools: string[] }>;
  budget_window_seconds: number;
  budget_defaults: { max_requests: number; max_input_tokens: number };
  budget_per_agent: Record<string, { max_requests: number; max_input_tokens: number }>;
  failure_policy: { privileged_action: Decision; prompt_actions: Record<string, Decision> };
};
export type LiveOverview = {
  policy_version: string; sample_size: number; sample_limit: number;
  counts: Record<Decision, number>; average_latency_ms: number | null;
  pending_approvals: number; agents: string[];
  activity: { prompt_injection: number; data_exfiltration: number; sensitive_data: number; provider_failures: number; deterministic_blocks: number; unauthorized_tools: null; budget_violations: null };
  latest_semantic: { failure: string | null; created_at: string } | null;
  can_approve: boolean; can_reload: boolean;
};
export type EventFilters = { decision: string; agent_id: string; input_type: string; search: string };
export type EventPage = { items: EventRecord[]; next_cursor: string | null };

export class ApiError extends Error {
  constructor(public status: number) {
    super(status === 401 ? "API key not recognized. Check your key and reconnect." : status === 403 ? "This key does not have the required permission." : status === 409 ? "This action conflicts with the current state. Refresh and review again." : "The backend is unavailable. Please try again.");
  }
}

async function request<T>(path: string, apiKey: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/control-api/api/v1${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return response.json() as Promise<T>;
}

export const controlApi = {
  tests: (key: string, signal?: AbortSignal) => request<TestRunSummary | null>("/tests/latest", key, { signal }),
  benchmark: (key: string, signal?: AbortSignal) => request<BenchmarkReport | null>("/benchmarks/latest", key, { signal }),
  policy: (key: string, signal?: AbortSignal) => request<PolicyMetadata>("/policies/active", key, { signal }),
  events: (key: string, filters?: EventFilters, cursor?: string | null, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: "12" });
    for (const [name, value] of Object.entries(filters ?? {})) if (value) query.set(name, value);
    if (cursor) query.set("cursor", cursor);
    return request<EventPage>(`/events?${query}`, key, { signal });
  },
  event: (key: string, id: string, signal?: AbortSignal) => request<EventRecord>(`/events/${encodeURIComponent(id)}`, key, { signal }),
  overview: (key: string, signal?: AbortSignal) => request<LiveOverview>("/dashboard/overview", key, { signal }),
  policyOverview: (key: string, signal?: AbortSignal) => request<PolicyOverview>("/policies/overview", key, { signal }),
  approvals: (key: string, offset = 0, signal?: AbortSignal) => request<Approval[]>(`/approvals?limit=12&status=PENDING&offset=${offset}`, key, { signal }),
  budgets: (key: string, signal?: AbortSignal) => request<BudgetUsage[]>("/budgets", key, { signal }),
  reload: (key: string) => request<{ changed: boolean; active: PolicyMetadata }>("/policies/reload", key, { method: "POST" }),
  resolve: (key: string, id: string, status: "APPROVED" | "DENIED") =>
    request<Approval>(`/approvals/${id}/resolution`, key, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
};
