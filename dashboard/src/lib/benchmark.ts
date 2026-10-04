export const labels = ["prompt_injection", "data_exfiltration"] as const;
export type Label = (typeof labels)[number];
export const labelNames: Record<Label, string> = {
  prompt_injection: "Prompt injection",
  data_exfiltration: "Data exfiltration",
};
export type LabelResult = { expected: boolean; predicted: boolean | null; score: number | null };
export type LabelMetrics = {
  evaluated: number; tp: number; tn: number; fp: number; fn: number;
  accuracy: number | null; precision: number | null; recall: number | null;
  f1: number | null; false_positive_rate: number | null; false_negative_rate: number | null;
};
export type BenchmarkReport = {
  schema_version: "1.0";
  benchmark_kind: "smoke-test";
  started_at: string; completed_at: string;
  configured_model: string; reported_models: string[]; model_snapshot: string | null;
  policy_version: string; corpus_sha256: string;
  corpus_size: number; successful: number; failed: number; coverage: number | null;
  thresholds: Record<Label, { value: number; operator: "gte" | "gt"; source: "policy" | "override" }>;
  metrics: Record<Label, LabelMetrics>;
  average_latency_ms: number | null; total_runtime_ms: number;
  estimated_api_cost_usd: number | null;
  cases: {
    case_id: string; labels: Record<Label, LabelResult>; latency_ms: number;
    failure: "timeout" | "rate_limit" | "malformed_output" | "outage" | null;
  }[];
};

export const percent = (value: number | null) => value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;
