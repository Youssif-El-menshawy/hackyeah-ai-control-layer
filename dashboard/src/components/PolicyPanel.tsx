import { BudgetUsage, PolicyOverview } from "@/lib/api";

const operators: Record<string, string> = { gte: "≥", gt: ">", lte: "≤", lt: "<", eq: "=", neq: "≠" };
export function PolicyPanel({ policy, budgets, canReload, busy, onReload }: {
  policy: PolicyOverview; budgets: BudgetUsage[]; canReload: boolean; busy: boolean; onReload: () => void;
}) {
  return <details className="panel disclosure policy-panel"><summary><span><span className="section-icon" aria-hidden="true">◇</span><strong>Policy overview</strong><small>Configuration, permissions & budgets</small></span><span className="disclosure-hint">View policy</span></summary>
    <div className="policy-content">
      <div className="section-heading"><p className="muted">Live, validated YAML is the source of truth. Changes take effect through the existing reload action.</p><button onClick={onReload} disabled={!canReload || busy}>{busy ? "Reloading…" : "Reload YAML"}</button></div>
      {!canReload && <p className="muted">Reload requires an admin key.</p>}
      <div className="policy-grid">
        <section><h3>Allowed request models</h3><div className="chip-list">{policy.allowed_models.map((model) => <code className="chip" key={model}>{model}</code>)}</div><h3>Enabled detectors</h3><div className="chip-list">{policy.enabled_detectors.map((name) => <span className="chip" key={name}>{name.replaceAll("_", " ")}</span>)}</div></section>
        <section><h3>Semantic policy conditions</h3>{policy.thresholds.length ? policy.thresholds.map((t, index) => <div className="policy-rule" key={`${t.rule_id}-${index}`}><strong>{t.fact.replace("semantic.", "").replaceAll("_", " ")} {operators[t.operator] || t.operator} {t.value}</strong><small><code>{t.rule_id}</code> · {t.action.replaceAll("_", " ")}{t.compound ? ` · part of ${t.mode} conditions` : ""}</small></div>) : <p className="muted">No semantic threshold rules configured.</p>}</section>
        <section><h3>Provider failure behavior</h3><p>Tool calls: <strong>{policy.failure_policy.privileged_action}</strong></p>{Object.entries(policy.failure_policy.prompt_actions).map(([kind, decision]) => <p className="policy-pair" key={kind}><span>Prompt · {kind.replaceAll("_", " ")}</span><strong>{decision.replaceAll("_", " ")}</strong></p>)}</section>
      </div>
      <div className="table-wrap"><table><caption>Agent permissions & current budget window · {policy.budget_window_seconds / 60} minutes</caption><thead><tr><th>Agent</th><th>Allowed tools</th><th>Denied tools</th><th>Requests</th><th>Input tokens</th></tr></thead><tbody>{Object.entries(policy.agents).map(([agent, tools]) => {
        const usage = budgets.find((b) => b.agent_id === agent);
        const limits = policy.budget_per_agent[agent] ?? policy.budget_defaults;
        return <tr key={agent}><td>{agent}</td><td>{tools.allowed_tools.join(", ") || "None"}</td><td>{tools.denied_tools.join(", ") || "None"}</td><td>{usage?.requests ?? 0} / {limits.max_requests}</td><td>{(usage?.input_tokens ?? 0).toLocaleString()} / {limits.max_input_tokens.toLocaleString()}</td></tr>;
      })}</tbody></table></div>
      <p className="muted policy-footnote">Default per-agent limits: {policy.budget_defaults.max_requests} requests / {policy.budget_defaults.max_input_tokens.toLocaleString()} input tokens per window. Tools not explicitly allowed remain disallowed.</p>
    </div>
  </details>;
}
