export type Decision = "ALLOW" | "REDACT" | "BLOCK" | "REQUIRE_APPROVAL";

export type EventRecord = {
  evaluation_id: string;
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
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export const controlApi = {
  policy: (key: string) => request<PolicyMetadata>("/policies/active", key),
  events: (key: string) => request<{ items: EventRecord[] }>("/events?limit=100", key),
  approvals: (key: string) => request<Approval[]>("/approvals?limit=100", key),
  budgets: (key: string) => request<BudgetUsage[]>("/budgets", key),
  reload: (key: string) => request<{ changed: boolean; active: PolicyMetadata }>("/policies/reload", key, { method: "POST" }),
  resolve: (key: string, id: string, status: "APPROVED" | "DENIED") =>
    request<Approval>(`/approvals/${id}/resolution`, key, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
};
