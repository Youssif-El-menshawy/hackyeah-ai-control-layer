import { DecisionBadge } from "./DecisionBadge";
import { EventFilters, EventPage, EventRecord } from "@/lib/api";

export const EMPTY_FILTERS: EventFilters = { decision: "", agent_id: "", input_type: "", search: "" };
const choices = [["", "All decisions"], ["ALLOW", "Allowed"], ["REDACT", "Redacted"], ["BLOCK", "Blocked"], ["REQUIRE_APPROVAL", "Needs approval"]];
export function ActivityTable({ page, filters, agents, connected, ready, pageNumber, onFilters, onOpen, onNext, onPrevious }: {
  page?: EventPage; filters: EventFilters; agents: string[]; connected: boolean; ready: boolean; pageNumber: number;
  onFilters: (filters: EventFilters) => void; onOpen: (event: EventRecord) => void; onNext: () => void; onPrevious: () => void;
}) {
  return <section className="panel activity-panel">
    <div className="panel-title"><div><p className="eyebrow">AUDIT STREAM</p><h2>Recent activity</h2></div><span className="muted">Newest first · 12 per page</span></div>
    <div className="activity-filters">
      <label className="search-field"><span>Search request ID or reason</span><input type="search" placeholder="Search request ID or reason…" value={filters.search} maxLength={200} onChange={(e) => onFilters({ ...filters, search: e.target.value })} /></label>
      <label><span>Agent</span><input list="agents" placeholder="All agents" value={filters.agent_id} maxLength={128} onChange={(e) => onFilters({ ...filters, agent_id: e.target.value })} /><datalist id="agents">{agents.map((agent) => <option key={agent} value={agent} />)}</datalist></label>
      <label><span>Request type</span><select value={filters.input_type} onChange={(e) => onFilters({ ...filters, input_type: e.target.value })}><option value="">All types</option><option value="prompt">Prompt</option><option value="tool_call">Tool call</option></select></label>
      <button className="text-button clear-filter" onClick={() => onFilters(EMPTY_FILTERS)}>Reset</button>
    </div>
    <div className="filter-tabs" aria-label="Decision filter">{choices.map(([value, name]) => <button key={value} aria-pressed={filters.decision === value} onClick={() => onFilters({ ...filters, decision: value })}>{name}</button>)}</div>
    <div className="table-wrap"><table className="activity-table"><thead><tr><th>Time</th><th>Agent</th><th>Request type</th><th>Decision</th><th>Reason</th><th>Risk</th><th>Latency</th></tr></thead><tbody>
      {ready && page?.items.map((event) => {
        const pi = event.risk_signals.find((s) => s.label === "prompt_injection")?.score;
        const ex = event.risk_signals.find((s) => s.label === "data_exfiltration")?.score;
        return <tr key={event.evaluation_id} className={`event-row event-${event.decision.toLowerCase()}`} onClick={() => onOpen(event)}>
          <td><button className="event-open" onClick={(e) => { e.stopPropagation(); onOpen(event); }} aria-label={`Open event ${event.request_id}`}><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time><small>{new Date(event.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}</small></button></td>
          <td><span className="cell-clip" title={event.agent_id}>{event.agent_id}</span></td>
          <td>{event.input_type === "prompt" ? "Prompt" : "Tool call"}{event.tool_name && <small className="cell-clip" title={event.tool_name}>{event.tool_name}</small>}</td>
          <td><DecisionBadge decision={event.decision} /></td>
          <td><span className="reason cell-clip" title={event.reason_codes.join(", ")}>{event.reason_codes.map((r) => r.toLowerCase().replaceAll("_", " ")).join(" · ")}</span></td>
          <td className="risk-cell">{event.semantic_failure ? <span className="risk-unavailable" title={event.semantic_failure}>Unavailable</span> : <>PI {pi === undefined ? "—" : `${Math.round(pi * 100)}%`} <span>·</span> EX {ex === undefined ? "—" : `${Math.round(ex * 100)}%`}</>}</td>
          <td className="numeric">{event.latency_ms.toLocaleString()} <span className="muted">ms</span></td>
        </tr>;
      })}
      {(!ready || !page?.items.length) && <tr><td colSpan={7} className="empty"><strong>{!connected ? "Your audit stream starts here" : !ready ? "Loading activity…" : "No matching events"}</strong><p>{!connected ? "Connect with an operator key to see real decisions. No demo data is preloaded." : !ready ? "Fetching safe audit records." : "Try clearing filters, or evaluate a request to see it here."}</p></td></tr>}
    </tbody></table></div>
    <footer className="table-footer"><span>Page {pageNumber} · {ready ? page?.items.length ?? 0 : "—"} records<span className="footer-tip"> · Select an event for safe details</span></span><div><button onClick={onPrevious} disabled={pageNumber === 1 || !ready}>← Previous</button><button onClick={onNext} disabled={!page?.next_cursor || !ready}>Next →</button></div></footer>
  </section>;
}
