"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, controlApi } from "@/lib/api";
import { BenchmarkReport, labelNames, labels, LabelResult, percent } from "@/lib/benchmark";
import { useOperatorSession } from "@/components/OperatorSession";

function resultText(result: LabelResult) {
  const predicted = result.predicted === null ? "unavailable" : result.predicted ? "positive" : "negative";
  return <><strong>{result.expected ? "positive" : "negative"} → {predicted}</strong>
    <small>Score: {result.score === null ? "N/A" : result.score.toFixed(3)}</small></>;
}

export default function BenchmarkPage() {
  const { key: apiKey, setKey: setApiKey } = useOperatorSession();
  const [draftKey, setDraftKey] = useState("");
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [activeVersion, setActiveVersion] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    if (!apiKey.trim()) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError("");
    setReport(null);
    setLoaded(false);
    try {
      const [nextReport, policy] = await Promise.all([controlApi.benchmark(apiKey, request.signal), controlApi.policy(apiKey, request.signal)]);
      if (request.signal.aborted) return;
      setReport(nextReport);
      setActiveVersion(policy.policy_version);
      setLoaded(true);
    } catch (cause) {
      if (!request.signal.aborted) setError(cause instanceof ApiError ? cause.message : "Unable to reach the backend. No benchmark results are being shown.");
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }, [apiKey]);

  useEffect(() => {
    const timer = apiKey ? window.setTimeout(() => void refresh(), 0) : undefined;
    return () => { if (timer !== undefined) clearTimeout(timer); controller.current?.abort(); };
  }, [apiKey, refresh]);

  return <main>
    <header className="topbar">
      <div><p className="eyebrow">HACKYEAH / OFFLINE EVALUATION</p><h1>Benchmark results</h1>
        <p className="page-subtitle">Evidence from real benchmark runs, with every limit in view.</p></div>
      <div className="connection">{apiKey ? <><span className="connection-label"><span className="status-dot" />Operator session · key kept in memory</span><div className="toolbar"><button onClick={refresh} disabled={loading}>{loading ? "Loading…" : "↻ Refresh"}</button><button className="text-button" onClick={() => { controller.current?.abort(); setApiKey(""); setReport(null); setLoaded(false); setError(""); setLoading(false); }}>Disconnect</button></div></> : <form onSubmit={(e) => { e.preventDefault(); setApiKey(draftKey.trim()); setDraftKey(""); }}><label htmlFor="benchmark-api-key">Viewer / admin API key</label><div className="input-row"><input id="benchmark-api-key" type="password" autoComplete="off" value={draftKey} onChange={(e) => setDraftKey(e.target.value)} placeholder="Kept only in page memory" /><button disabled={!draftKey.trim()}>Connect</button></div></form>}</div>
    </header>
    <aside className="benchmark-notice">
      <strong>Smoke-test benchmark — not production-grade validation.</strong>
      <p>The included corpus has only 8 cases. These results are diagnostic evidence, not proof of security, calibration, or production readiness. Benchmark execution is CLI-only and separate from request handling.</p>
    </aside>
    {error && <div className="error" role="alert">{error}</div>}
    {!report && !error && <section className="panel empty" aria-live="polite">
      {loading ? "Loading benchmark results…" : loaded ? "No benchmark results yet" : "Connect to check for benchmark results. No sample results are displayed."}
    </section>}
    {report && <>
      {activeVersion !== report.policy_version && <div className="error" role="status">This benchmark used a different policy version from the currently active backend policy. Metrics below use the recorded benchmark thresholds.</div>}
      <section className="panel benchmark-metadata" aria-label="Benchmark provenance">
        <dl>
          <div><dt>Configured model</dt><dd>{report.configured_model}</dd></div>
          <div><dt>Provider-reported model</dt><dd>{report.reported_models.join(", ") || "Unavailable"}</dd></div>
          <div><dt>Model snapshot</dt><dd>{report.model_snapshot ?? "Unverified — no unique dated snapshot reported"}</dd></div>
          <div><dt>Benchmark started (UTC)</dt><dd><time dateTime={report.started_at}>{report.started_at}</time></dd></div>
          <div><dt>Benchmark completed (UTC)</dt><dd><time dateTime={report.completed_at}>{report.completed_at}</time></dd></div>
          <div><dt>Policy SHA-256</dt><dd><code>{report.policy_version}</code></dd></div>
          <div><dt>Corpus SHA-256</dt><dd><code>{report.corpus_sha256}</code></dd></div>
        </dl>
      </section>
      <section className="metrics" aria-label="Benchmark run summary">
        <article><span>Corpus size</span><strong>{report.corpus_size}<small> cases</small></strong></article>
        <article><span>Coverage</span><strong>{percent(report.coverage)}</strong><small>{report.successful} / {report.corpus_size} scored</small></article>
        <article><span>Failures</span><strong>{report.failed}</strong></article>
        <article><span>Average latency</span><strong>{report.average_latency_ms === null ? "N/A" : report.average_latency_ms.toFixed(0)}<small> ms</small></strong></article>
        <article><span>Total runtime</span><strong>{(report.total_runtime_ms / 1000).toFixed(2)}<small> s</small></strong></article>
        <article><span>Estimated API cost</span><strong className="benchmark-cost">{report.estimated_api_cost_usd === null ? "Unavailable" : `$${report.estimated_api_cost_usd.toFixed(6)}`}</strong><small>USD · explicit pricing + reported usage only</small></article>
      </section>
      <p className="benchmark-explanation">Coverage = successfully classified cases / corpus size. Failed cases are excluded from classification metrics, never counted as safe predictions. Latency includes failed attempts. Undefined metrics display N/A; cost is unavailable if any attempt lacks required usage/pricing.</p>
      <div className="benchmark-labels">
        {labels.map((label) => {
          const metric = report.metrics[label];
          const threshold = report.thresholds[label];
          return <section className="panel" key={label}>
            <div className="panel-title"><div><p className="eyebrow">{metric.evaluated} / {report.corpus_size} CASES SCORED</p><h2>{labelNames[label]}</h2></div></div>
            <p className="benchmark-threshold">Positive when score {threshold.operator === "gte" ? "≥" : ">"} {threshold.value} · {threshold.source === "policy" ? "Policy threshold" : "EXPLICIT OVERRIDE"}</p>
            <dl className="benchmark-stat-list">
              {([ ["Accuracy", metric.accuracy], ["Precision", metric.precision], ["Recall", metric.recall], ["F1", metric.f1], ["False-positive rate", metric.false_positive_rate], ["False-negative rate", metric.false_negative_rate] ] as const).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{percent(value)}</dd></div>)}
            </dl>
            <div className="table-wrap"><table><caption>Confusion counts · positive means risk detected</caption>
              <thead><tr><th scope="col">Actual / predicted</th><th scope="col">Positive</th><th scope="col">Negative</th></tr></thead>
              <tbody><tr><th scope="row">Positive</th><td>TP: {metric.tp}</td><td>FN: {metric.fn}</td></tr>
                <tr><th scope="row">Negative</th><td>FP: {metric.fp}</td><td>TN: {metric.tn}</td></tr></tbody>
            </table></div>
          </section>;
        })}
      </div>
      <section className="panel benchmark-cases">
        <div className="panel-title"><div><p className="eyebrow">NO PROMPT TEXT EXPORTED</p><h2>Per-case results</h2></div><button className="text-button" onClick={refresh} disabled={loading}>Refresh</button></div>
        <div className="table-wrap"><table>
          <caption>Expected → predicted. Case numbers map to nonblank corpus rows; prompts and source IDs are omitted.</caption>
          <thead><tr><th>Case</th><th>Prompt injection</th><th>Data exfiltration</th><th>Status</th><th>Latency</th></tr></thead>
          <tbody>{report.cases.map((item) => <tr key={item.case_id}>
            <td>{item.case_id}</td><td>{resultText(item.labels.prompt_injection)}</td><td>{resultText(item.labels.data_exfiltration)}</td>
            <td>{item.failure ? `Failed: ${item.failure.replaceAll("_", " ")}` : "Scored"}</td><td>{item.latency_ms.toFixed(1)} ms</td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}
  </main>;
}
