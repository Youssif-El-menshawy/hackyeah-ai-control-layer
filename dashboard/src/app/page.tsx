"use client";

import { useCallback, useMemo, useState } from "react";

import { DecisionBadge } from "@/components/DecisionBadge";
import { Approval, BudgetUsage, controlApi, EventRecord, PolicyMetadata } from "@/lib/api";

export default function Dashboard() {
  const [apiKey, setApiKey] = useState("");
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [policy, setPolicy] = useState<PolicyMetadata | null>(null);
  const [budgets, setBudgets] = useState<BudgetUsage[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    setLoading(true);
    setError("");
    try {
      const [nextPolicy, nextEvents, nextApprovals, nextBudgets] = await Promise.all([
        controlApi.policy(apiKey),
        controlApi.events(apiKey),
        controlApi.approvals(apiKey),
        controlApi.budgets(apiKey),
      ]);
      setPolicy(nextPolicy);
      setEvents(nextEvents.items);
      setApprovals(nextApprovals);
      setBudgets(nextBudgets);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load control data");
    } finally {
      setLoading(false);
    }
  }, [apiKey]);

  const counts = useMemo(() => {
    const base = { ALLOW: 0, REDACT: 0, BLOCK: 0, REQUIRE_APPROVAL: 0 };
    for (const event of events) base[event.decision] += 1;
    return base;
  }, [events]);

  const averageLatency = events.length
    ? Math.round(events.reduce((total, event) => total + event.latency_ms, 0) / events.length)
    : 0;
  const tokenTotal = budgets.reduce((total, budget) => total + budget.input_tokens, 0);
  const tokenLimit = budgets.reduce((total, budget) => total + budget.max_input_tokens, 0);

  async function reloadPolicy() {
    try {
      const result = await controlApi.reload(apiKey);
      setPolicy(result.active);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Policy reload failed");
    }
  }

  async function resolve(id: string, status: "APPROVED" | "DENIED") {
    try {
      await controlApi.resolve(apiKey, id, status);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Approval update failed");
    }
  }

  return (
    <main>
      <header className="topbar">
        <div>
          <p className="eyebrow">HACKYEAH / SECURITY OPERATIONS</p>
          <h1>AI Control Layer</h1>
        </div>
        <div className="connection">
          <label htmlFor="api-key">Operator API key</label>
          <div className="input-row">
            <input id="api-key" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Kept only in this tab" />
            <button onClick={refresh} disabled={!apiKey || loading}>{loading ? "Loading…" : "Connect"}</button>
          </div>
        </div>
      </header>

      {error && <div className="error" role="alert">{error}</div>}

      <section className="policy-strip">
        <div><span>Active policy</span><strong>{policy?.policy_id ?? "Not connected"}</strong></div>
        <div><span>Version</span><code>{policy?.policy_version.slice(0, 12) ?? "—"}</code></div>
        <div><span>Loaded</span><strong>{policy ? new Date(policy.loaded_at).toLocaleString() : "—"}</strong></div>
        <button className="secondary" onClick={reloadPolicy} disabled={!policy}>Reload YAML</button>
      </section>

      <section className="metrics" aria-label="Decision telemetry">
        <article><span>Allowed</span><strong>{counts.ALLOW}</strong><i className="allow" /></article>
        <article><span>Redacted</span><strong>{counts.REDACT}</strong><i className="redact" /></article>
        <article><span>Blocked</span><strong>{counts.BLOCK}</strong><i className="block" /></article>
        <article><span>Needs approval</span><strong>{counts.REQUIRE_APPROVAL}</strong><i className="approval" /></article>
        <article><span>Avg. latency</span><strong>{averageLatency}<small> ms</small></strong></article>
        <article><span>Budget tokens</span><strong>{tokenTotal.toLocaleString()}<small> / {tokenLimit.toLocaleString()}</small></strong></article>
      </section>

      <section className="grid">
        <article className="panel events-panel">
          <div className="panel-title"><div><p className="eyebrow">AUDIT STREAM</p><h2>Recent decisions</h2></div><button className="text-button" onClick={refresh}>Refresh</button></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Agent / request</th><th>Decision</th><th>Reason</th><th>Signals</th><th>Latency</th></tr></thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.evaluation_id}>
                    <td>{new Date(event.created_at).toLocaleTimeString()}</td>
                    <td><strong>{event.agent_id}</strong><small>{event.input_type}{event.tool_name ? ` · ${event.tool_name}` : ""}</small></td>
                    <td><DecisionBadge decision={event.decision} /></td>
                    <td>{event.reason_codes.join(", ")}</td>
                    <td>{event.risk_signals.map((signal) => `${signal.label.replace("_", " ")} ${Math.round(signal.score * 100)}%`).join(" · ")}</td>
                    <td>{event.latency_ms} ms</td>
                  </tr>
                ))}
                {!events.length && <tr><td colSpan={6} className="empty">Connect to view safe audit telemetry.</td></tr>}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel approvals-panel">
          <div className="panel-title"><div><p className="eyebrow">HUMAN GATE</p><h2>Approval queue</h2></div></div>
          <div className="approval-list">
            {approvals.filter((item) => item.status === "PENDING").map((approval) => (
              <div className="approval-card" key={approval.approval_id}>
                <div><span>Evaluation</span><code>{approval.evaluation_id.slice(0, 8)}</code></div>
                <time>{new Date(approval.created_at).toLocaleString()}</time>
                <div className="approval-actions">
                  <button className="approve" onClick={() => resolve(approval.approval_id, "APPROVED")}>Approve</button>
                  <button className="deny" onClick={() => resolve(approval.approval_id, "DENIED")}>Deny</button>
                </div>
              </div>
            ))}
            {!approvals.some((item) => item.status === "PENDING") && <p className="empty">No pending approvals.</p>}
          </div>
        </article>
      </section>
    </main>
  );
}
