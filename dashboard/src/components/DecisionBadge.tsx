import type { Decision } from "@/lib/api";

export function DecisionBadge({ decision }: { decision: Decision }) {
  const names = { ALLOW: "Allowed", REDACT: "Redacted", BLOCK: "Blocked", REQUIRE_APPROVAL: "Needs approval" };
  return <span className={`badge badge-${decision.toLowerCase().replace("_", "-")}`}><span aria-hidden="true">●</span> {names[decision]}</span>;
}
