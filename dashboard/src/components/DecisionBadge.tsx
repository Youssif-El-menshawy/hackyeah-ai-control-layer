import type { Decision } from "@/lib/api";

export function DecisionBadge({ decision }: { decision: Decision }) {
  return <span className={`badge badge-${decision.toLowerCase().replace("_", "-")}`}>{decision.replace("_", " ")}</span>;
}

