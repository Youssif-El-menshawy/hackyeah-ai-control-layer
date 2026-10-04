"use client";

import { useEffect, useRef } from "react";
import { Approval, EventRecord } from "@/lib/api";
import { DecisionBadge } from "./DecisionBadge";

export function EventDrawer({ event, approval, busy, error, onClose, onResolve }: {
  event: EventRecord; approval?: Approval; busy: boolean; error: string;
  onClose: () => void; onResolve: (approval: Approval, decision: "APPROVED" | "DENIED") => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { node?.close(); document.body.style.overflow = overflow; };
  }, []);
  const deterministic = event.reason_codes.includes("DETERMINISTIC_CONTROL_FAILED");
  const semantic = event.reason_codes.some((reason) => reason.startsWith("SEMANTIC_") || reason === "PROMPT_INJECTION_REVIEW" || reason === "DATA_EXFILTRATION_HIGH_RISK");
  const redacted = event.reason_codes.includes("CONTACT_DATA_REDACTED");
  const stage = deterministic ? 2 : semantic ? 3 : redacted ? 1 : 4;
  return <dialog ref={dialog} className="event-drawer" aria-labelledby="event-title" onCancel={onClose} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="drawer-content">
      <header className="drawer-heading"><div><p className="eyebrow">SAFE AUDIT RECORD</p><h2 id="event-title">Decision details</h2></div><button className="icon-button" onClick={onClose} aria-label="Close event details">×</button></header>
      <div className="drawer-decision"><DecisionBadge decision={event.decision} /><span>{new Date(event.created_at).toLocaleString()}</span></div>
      <section className="drawer-section"><h3>Decision pipeline</h3>
        <ol className="pipeline">{["Request", "Sanitization", "Deterministic checks", "Semantic analysis", "Policy engine", "Final decision"].map((name, i) => <li key={name} className={i === stage || i === 5 ? "stage-active" : ""}><span>{i + 1}</span>{name}</li>)}</ol>
        <p className="muted">{deterministic ? "A deterministic control failed. The audit record does not identify which model, tool, or budget check failed." : semantic ? "Recorded semantic risk or provider failure contributed to the final policy decision." : redacted ? "Contact-data findings triggered the recorded redaction reason." : "The policy engine produced this decision. Per-stage execution traces are not retained."} Highlights reflect recorded reasons, not a replay.</p>
      </section>
      <section className="drawer-section"><h3>Request & decision</h3><dl className="detail-grid">
        {[ ["Reason codes", event.reason_codes.join(", ")], ["Agent ID", event.agent_id], ["Request type", event.input_type === "prompt" ? "Prompt" : "Tool call"], ["Tool", event.tool_name || "Not applicable"], ["Model", event.model], ["Latency", `${event.latency_ms} ms`], ["Estimated input tokens", String(event.estimated_input_tokens)], ["Timestamp (UTC)", event.created_at] ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl></section>
      <section className="drawer-section"><h3>Detectors & semantic signals</h3>
        <div className="chip-list">{event.redactions.length ? event.redactions.map((r) => <span className="chip" key={r.kind}>{r.kind.replaceAll("_", " ")} · {r.count}</span>) : <span className="muted">No deterministic findings recorded.</span>}</div>
        {event.semantic_failure ? <p className="notice">Provider failure: {event.semantic_failure.replaceAll("_", " ")}. Scores are unavailable—not evidence of low risk.</p> : <div className="signal-list">{event.risk_signals.map((signal) => <div key={signal.label}><span>{signal.label.replaceAll("_", " ")}</span><strong>{Math.round(signal.score * 100)}%</strong><meter min={0} max={1} value={signal.score} /></div>)}</div>}
      </section>
      <section className="drawer-section"><h3>Content & rule trace</h3><p className="empty-inline">Sanitized content is not retained in audit records. Raw prompts are never shown.</p><p className="muted">Matched rule IDs are not retained. The recorded reason codes above are the available explanation; current YAML rules are not substituted for historical rules.</p></section>
      <section className="drawer-section"><h3>Audit identifiers</h3><dl className="detail-grid identifiers">
        {[ ["Evaluation ID", event.evaluation_id], ["Request ID", event.request_id], ["Policy version", event.policy_version], ["Request fingerprint (SHA-256)", event.input_sha256] ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{value}</code></dd></div>)}
      </dl></section>
      {approval && <section className="approval-resolution"><h3>Resolve pending approval</h3><p>Review the safe metadata above. Approval records a human decision; it does not execute the original request.</p>{error && <p role="alert" className="error">{error}</p>}<div className="approval-actions"><button className="approve" disabled={busy} onClick={() => onResolve(approval, "APPROVED")}>{busy ? "Saving…" : "Approve"}</button><button className="deny" disabled={busy} onClick={() => onResolve(approval, "DENIED")}>Deny</button></div></section>}
    </div>
  </dialog>;
}
