"use client";

import { useEffect, useRef, useState } from "react";
import { ActivityTable, EMPTY_FILTERS } from "@/components/ActivityTable";
import { EventDrawer } from "@/components/EventDrawer";
import { PolicyPanel } from "@/components/PolicyPanel";
import { useOperatorSession } from "@/components/OperatorSession";
import { ApiError, Approval, controlApi, EventRecord } from "@/lib/api";
import { useDashboard } from "@/lib/useDashboard";

export default function Dashboard() {
  const [draftKey, setDraftKey] = useState("");
  const { key, setKey } = useOperatorSession();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [approvalOffset, setApprovalOffset] = useState(0);
  const [selected, setSelected] = useState<{ event: EventRecord; approval?: Approval } | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [reloadBusy, setReloadBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState<string | null>(null);
  const reviewController = useRef<AbortController | null>(null);
  const live = useDashboard(key, appliedFilters, cursors[cursors.length - 1], approvalOffset);
  const { data } = live;
  useEffect(() => {
    const timer = setTimeout(() => { setAppliedFilters(filters); setCursors([null]); }, 350);
    return () => clearTimeout(timer);
  }, [filters]);
  useEffect(() => () => reviewController.current?.abort(), []);

  function disconnect() {
    reviewController.current?.abort();
    setKey(""); setDraftKey(""); setSelected(null); setActionError(""); setReviewBusy(null);
  }
  async function review(approval: Approval) {
    reviewController.current?.abort();
    const controller = new AbortController();
    reviewController.current = controller;
    setReviewBusy(approval.approval_id); setActionError("");
    try {
      const event = await controlApi.event(key, approval.evaluation_id, controller.signal);
      if (!controller.signal.aborted) setSelected({ event, approval });
    } catch (cause) {
      if (!controller.signal.aborted) setActionError(cause instanceof ApiError ? cause.message : "Unable to load safe approval context.");
    } finally { if (!controller.signal.aborted) setReviewBusy(null); }
  }
  async function resolve(approval: Approval, status: "APPROVED" | "DENIED") {
    if (actionBusy) return;
    setActionBusy(true); setActionError("");
    try {
      await controlApi.resolve(key, approval.approval_id, status);
      live.removeApproval(approval.approval_id);
      setSelected(null);
      setApprovalOffset(0);
    } catch (cause) {
      setActionError(cause instanceof ApiError ? cause.message : "Unable to confirm resolution. Refresh to check its status before retrying.");
      live.refresh();
    } finally { setActionBusy(false); }
  }
  async function reloadPolicy() {
    setReloadBusy(true); setActionError("");
    try { await controlApi.reload(key); live.refresh(); }
    catch (cause) { setActionError(cause instanceof ApiError ? cause.message : "Policy reload failed. The last valid policy remains active."); }
    finally { setReloadBusy(false); }
  }

  const policy = data?.policy;
  const lastSemantic = data?.overview.latest_semantic;
  const recentObservation = lastSemantic && data && data.updatedAt.getTime() - new Date(lastSemantic.created_at).getTime() < 5 * 60_000;
  const posture = !key ? "Not connected" : !data ? (live.failure ? "Connection issue" : "Awaiting connection") : live.failure ? "Degraded" : policy?.semantic_provider === "stub" ? "Demo provider" : recentObservation && lastSemantic.failure ? (lastSemantic.failure === "outage" ? "Provider outage recorded" : "Degraded") : recentObservation ? "Protected" : "Policy active";
  const postureDetail = !data ? live.failure ? "Review the connection message and reconnect or refresh." : "Connect to inspect your security controls." : live.failure ? "Live telemetry is temporarily unavailable." : policy?.semantic_provider === "stub" ? "Offline stub configured; no live semantic protection claim." : recentObservation ? "Based on the latest recorded result, not a provider health probe." : "Provider health unverified: no current-policy result in the last 5 minutes.";
  const budgetTokens = data?.budgets.reduce((sum, b) => sum + b.input_tokens, 0) ?? 0;
  const budgetLimit = data?.budgets.reduce((sum, b) => sum + b.max_input_tokens, 0) ?? 0;
  const activeAgents = [...new Set([...(data?.overview.agents ?? []), ...Object.keys(policy?.agents ?? {})])].sort();
  const pending = data?.overview.pending_approvals ?? 0;

  return <main>
    <header className="topbar"><div><p className="eyebrow">CONTROL, WITH CONFIDENCE</p><h1>Security overview</h1><p className="page-subtitle">A clear view of what your agents are doing—and what needs you.</p></div>
      <div className="connection">{key ? <><span className="connection-label"><span className="status-dot" />Operator session · key kept in memory</span><div className="toolbar"><button onClick={live.refresh} disabled={live.refreshing}>{live.refreshing ? "Syncing…" : "↻ Refresh"}</button><button className="text-button" onClick={disconnect} disabled={actionBusy}>Disconnect</button></div></> : <form onSubmit={(e) => { e.preventDefault(); setKey(draftKey.trim()); setDraftKey(""); setActionError(""); }}><label htmlFor="api-key">Connect to your control layer</label><div className="input-row"><input id="api-key" type="password" autoComplete="off" value={draftKey} onChange={(e) => setDraftKey(e.target.value)} placeholder="Operator API key" /><button disabled={!draftKey.trim()}>Connect</button></div></form>}</div>
    </header>
    {live.failure && !data && <div className="error" role="alert"><strong>Connection needs attention.</strong> {live.failure.message}</div>}
    {actionError && !selected && <div className="error" role="alert">{actionError}<button className="text-button" onClick={() => setActionError("")}>Dismiss</button></div>}
    <section className={`posture panel ${posture === "Connection issue" || posture === "Degraded" || posture === "Provider outage recorded" ? "posture-warning" : ""}`} aria-label="Security posture">
      <div className="posture-state"><span className="posture-icon" aria-hidden="true">◇</span><div><strong>{posture}</strong><p>{postureDetail}</p></div></div>
      <dl className="posture-details"><div><dt>Active policy</dt><dd>{policy?.policy_id ?? "—"}<small><code>{policy?.policy_version.slice(0, 12) ?? "No policy loaded"}</code></small></dd></div><div><dt>Semantic provider / model</dt><dd>{policy?.semantic_provider ?? "—"}<small>{policy?.semantic_model ?? "No external model"}</small></dd></div><div><dt>Policy loaded / last changed</dt><dd>{policy ? new Date(policy.loaded_at).toLocaleTimeString() : "—"}<small>{policy ? new Date(policy.loaded_at).toLocaleDateString() : "Awaiting connection"}</small></dd></div></dl>
    </section>
    <section className={`self-tests panel ${data?.tests?.status === "failed" ? "self-tests-failed" : data?.tests?.status === "incomplete" || data?.testsUnavailable ? "self-tests-incomplete" : ""}`} aria-label="Latest backend self-tests" aria-live="polite">
      <div className="self-tests-heading"><span className="eyebrow">BACKEND SELF-TESTS</span><strong>{!key ? "Connect to see self-tests" : !data ? "Loading latest run…" : data.testsUnavailable ? "Results unavailable" : !data.tests ? "No test results yet" : data.tests.status === "failed" ? "Last run failed" : data.tests.status === "incomplete" ? "Run incomplete" : "Last run passed"}</strong></div>
      {data?.tests && <><dl className="self-tests-counts"><div><dt>Passed</dt><dd>{data.tests.passed}</dd></div><div><dt>Failed</dt><dd>{data.tests.failed}</dd></div><div><dt>Skipped</dt><dd>{data.tests.skipped}</dd></div><div><dt>Total</dt><dd>{data.tests.total}</dd></div><div><dt>Duration</dt><dd>{data.tests.duration_seconds.toFixed(2)}s</dd></div></dl><time dateTime={data.tests.completed_at}>Completed {new Date(data.tests.completed_at).toLocaleString()}</time></>}
    </section>
    <div className="section-heading overview-caption"><span>Decision snapshot <span className="muted">· latest {data?.overview.sample_size ?? "—"} of up to 100 evaluations</span></span><span className={`live-indicator ${live.failure ? "stale" : ""}`} role="status">{!key ? "Live view disconnected" : live.failure && !data ? "Refresh paused · reconnect or try again" : live.paused ? "Auto-refresh paused · tab hidden" : live.failure && data ? `Refresh interrupted · showing last good data${live.failure.count > 1 ? " · retrying" : ""}` : `Auto-refresh: 5s${data ? ` · updated ${data.updatedAt.toLocaleTimeString()}` : ""}`}</span></div>
    <section className="metrics" aria-label="Decision summary">
      {([ ["ALLOW", "Allowed", "quiet"], ["REDACT", "Redacted", "redact"], ["BLOCK", "Blocked", "danger"], ["REQUIRE_APPROVAL", "Needs approval", "attention"] ] as const).map(([decision, name, tone]) => <article className={`metric-${tone}`} key={decision}><span>{name}</span><strong>{data ? data.overview.counts[decision].toLocaleString() : "—"}</strong><small>{decision === "ALLOW" ? "Passed controls" : decision === "BLOCK" ? "Stopped by policy" : decision === "REDACT" ? "Sensitive data removed" : "Human review requested"}</small></article>)}
      <article><span>Average latency</span><strong>{data?.overview.average_latency_ms == null ? "—" : Math.round(data.overview.average_latency_ms).toLocaleString()}<small> ms</small></strong><small>Recent evaluations</small></article>
      <article><span>Budget usage</span><strong>{data && budgetLimit ? Math.round(budgetTokens / budgetLimit * 100) : "—"}<small>{budgetLimit ? "%" : ""}</small></strong><small>{data ? `${budgetTokens.toLocaleString()} / ${budgetLimit.toLocaleString()} tokens · agents with usage` : "Current budget window"}</small></article>
    </section>
    <section className="threat-strip panel" aria-label="Recent security activity"><div><p className="eyebrow">SECURITY ACTIVITY</p><span className="muted">Same recent-event sample</span></div>{([ ["Injection decisions", data?.overview.activity.prompt_injection], ["Exfiltration decisions", data?.overview.activity.data_exfiltration], ["Sensitive-data cases", data?.overview.activity.sensitive_data], ["Provider failures", data?.overview.activity.provider_failures], ["Deterministic blocks", data?.overview.activity.deterministic_blocks] ] as const).map(([name, count]) => <div className="threat-item" key={name}><strong>{count ?? "—"}</strong><span>{name}</span></div>)}</section>
    <p className="data-caveat">Risk counts use recorded decision reasons, not all threshold crossings. Exact tool-denial and budget-violation counts are unavailable in historical records.</p>
    <details className="panel disclosure approval-queue"><summary><span><span className="section-icon attention-text" aria-hidden="true">◎</span><strong>Needs Approval</strong><span className="count-pill">{data ? pending : "—"}</span><small>{pending ? "Decisions waiting for a human" : "Review pending decisions when they arrive"}</small></span><span className="disclosure-hint">Open queue</span></summary>
      {!data ? <p className="empty">Connect to see pending approvals.</p> : !data.overview.can_approve ? <p className="empty">This key has read-only access. Use an approver or admin key to review approvals.</p> : <div className="approval-list">
        {data.approvals.map((approval) => <div className="approval-card" key={approval.approval_id}><div><strong>Human review required</strong><small><code>{approval.evaluation_id}</code></small></div><time>{new Date(approval.created_at).toLocaleString()}</time><button disabled={reviewBusy !== null} onClick={() => review(approval)}>{reviewBusy === approval.approval_id ? "Loading context…" : "Review & resolve →"}</button></div>)}
        {!data.approvals.length && <p className="empty">{pending ? "No approvals on this page. Return to the first page." : "All clear—no pending approvals."}</p>}
        {(pending > 12 || approvalOffset > 0) && <div className="table-footer"><span>Showing up to 12 pending approvals</span><div><button disabled={!approvalOffset} onClick={() => setApprovalOffset(Math.max(0, approvalOffset - 12))}>Previous</button><button disabled={approvalOffset + 12 >= pending} onClick={() => setApprovalOffset(approvalOffset + 12)}>Next</button></div></div>}
      </div>}
    </details>
    <ActivityTable page={data?.events} filters={filters} agents={activeAgents} connected={!!key} ready={live.pageReady && JSON.stringify(filters) === JSON.stringify(appliedFilters)} pageNumber={cursors.length} onFilters={setFilters} onOpen={(event) => { setSelected({ event }); setActionError(""); }} onNext={() => { if (data?.events.next_cursor) setCursors([...cursors, data.events.next_cursor]); }} onPrevious={() => setCursors(cursors.slice(0, -1))} />
    {policy && data && <PolicyPanel policy={policy} budgets={data.budgets} canReload={data.overview.can_reload} busy={reloadBusy} onReload={reloadPolicy} />}
    <footer className="console-footer"><span>Deterministic policy. Human oversight.</span><span>Safe telemetry only · raw prompts are never displayed</span></footer>
    {selected && <EventDrawer event={selected.event} approval={selected.approval} busy={actionBusy} error={actionError} onClose={() => setSelected(null)} onResolve={resolve} />}
  </main>;
}
