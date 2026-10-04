"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, Approval, BudgetUsage, controlApi, EventFilters, EventPage, LiveOverview, PolicyOverview, TestRunSummary } from "./api";

type Snapshot = { key: string; query: string; overview: LiveOverview; events: EventPage; approvals: Approval[]; budgets: BudgetUsage[]; policy: PolicyOverview; tests: TestRunSummary | null; testsUnavailable: boolean; updatedAt: Date };

export function useDashboard(key: string, filters: EventFilters, cursor: string | null, approvalOffset: number) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string; count: number } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [paused, setPaused] = useState(false);
  const policyCache = useRef<{ key: string; policy: PolicyOverview } | null>(null);
  const refreshRef = useRef<() => void>(() => {});
  const query = JSON.stringify({ filters, cursor, approvalOffset });

  useEffect(() => {
    if (!key) return;
    const selected = JSON.parse(query) as { filters: EventFilters; cursor: string | null; approvalOffset: number };
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    let pending = false;
    let failures = 0;
    let unauthorized = false;

    async function run() {
      if (controller.signal.aborted || unauthorized) return;
      if (busy) { pending = true; return; }
      if (document.visibilityState === "hidden") return;
      clearTimeout(timer);
      busy = true;
      setRefreshing(true);
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]);
        const results = await Promise.allSettled([
          controlApi.overview(key, signal),
          controlApi.events(key, selected.filters, selected.cursor, signal),
          controlApi.budgets(key, signal),
          controlApi.tests(key, signal),
        ]);
        const [overviewResult, eventsResult, budgetsResult, testsResult] = results;
        if (overviewResult.status === "rejected") throw overviewResult.reason;
        if (eventsResult.status === "rejected") throw eventsResult.reason;
        if (budgetsResult.status === "rejected") throw budgetsResult.reason;
        const overview = overviewResult.value, events = eventsResult.value, budgets = budgetsResult.value;
        const cached = policyCache.current;
        const [policyResult, approvalsResult] = await Promise.allSettled([
          cached?.key === key && cached.policy.policy_version === overview.policy_version ? cached.policy : controlApi.policyOverview(key, signal),
          overview.can_approve ? controlApi.approvals(key, selected.approvalOffset, signal) : [],
        ]);
        if (policyResult.status === "rejected") throw policyResult.reason;
        if (approvalsResult.status === "rejected") throw approvalsResult.reason;
        const policy = policyResult.value, approvals = approvalsResult.value;
        if (controller.signal.aborted) return;
        policyCache.current = { key, policy };
        failures = 0;
        setFailure(null);
        setSnapshot({ key, query, overview, events, budgets, policy, approvals,
          tests: testsResult.status === "fulfilled" ? testsResult.value : null,
          testsUnavailable: testsResult.status === "rejected", updatedAt: new Date() });
      } catch (cause) {
        if (controller.signal.aborted) return;
        failures += 1;
        unauthorized = cause instanceof ApiError && (cause.status === 401 || cause.status === 403);
        setFailure({ key, count: failures, message: cause instanceof ApiError ? cause.message : "Cannot reach the backend. Check that it is running, then refresh." });
        if (unauthorized) setSnapshot(null);
      } finally {
        busy = false;
        if (!controller.signal.aborted) {
          setRefreshing(false);
          if (pending) { pending = false; void run(); }
          else if (!unauthorized) timer = setTimeout(() => void run(), 5000);
        }
      }
    }
    function onVisibility() {
      setPaused(document.visibilityState === "hidden");
      clearTimeout(timer);
      if (document.visibilityState === "visible") void run();
    }
    refreshRef.current = () => { unauthorized = false; void run(); };
    void run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      controller.abort();
      clearTimeout(timer);
      refreshRef.current = () => {};
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [key, query]);

  const refresh = useCallback(() => refreshRef.current(), []);
  const removeApproval = useCallback((id: string) => {
    setSnapshot((old) => old ? { ...old, approvals: old.approvals.filter((a) => a.approval_id !== id),
      overview: { ...old.overview, pending_approvals: Math.max(0, old.overview.pending_approvals - 1) } } : null);
    refreshRef.current();
  }, []);
  const data = snapshot?.key === key ? snapshot : null;
  return { data, failure: failure?.key === key ? failure : null, refreshing, paused, refresh, removeApproval,
    pageReady: data?.query === query };
}
