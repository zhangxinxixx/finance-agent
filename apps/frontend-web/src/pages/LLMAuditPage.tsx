import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { fetchLLMAuditDetail } from "@/adapters/llmAudit";
import { LLMAuditDetailPanel } from "@/components/llm-audit/LLMAuditDetailPanel";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { useLLMAudits } from "@/hooks/useLLMAudits";
import type { LLMAuditDetail } from "@/types/llm-audit";

export function LLMAuditPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<LLMAuditDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [auditToken, setAuditToken] = useState(() => sessionStorage.getItem("finance_agent_audit_token") ?? "");
  const [tokenDraft, setTokenDraft] = useState(auditToken);
  const [searchParams] = useSearchParams();
  const requestedAuditId = searchParams.get("audit_id");
  const reportIdFilter = searchParams.get("report_id") || undefined;
  const filters = useMemo(() => ({ limit: 100, caller: query.trim() || undefined, status: status || undefined, reportId: reportIdFilter }), [query, reportIdFilter, status]);
  const audits = useLLMAudits(filters, auditToken);

  useEffect(() => {
    const first = requestedAuditId && audits.data?.audits.some((item) => item.audit_id === requestedAuditId)
      ? requestedAuditId
      : audits.data?.audits[0]?.audit_id ?? null;
    setSelectedId((current) => current && audits.data?.audits.some((item) => item.audit_id === current) ? current : first);
  }, [audits.data, requestedAuditId]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedId) {
      setSelected(null);
      setDetailError(null);
      return () => { cancelled = true; };
    }
    setDetailError(null);
    void fetchLLMAuditDetail(selectedId, auditToken, true)
      .then((item) => {
        if (!cancelled) setSelected(item);
      })
      .catch((cause) => {
        if (!cancelled) {
          setSelected(null);
          setDetailError(cause instanceof Error ? cause.message : "审计详情读取失败");
        }
      });
    return () => { cancelled = true; };
  }, [auditToken, selectedId]);

  if (audits.isLoading && !audits.data) return <div className="finance-page-shell"><LoadingSkeleton variant="page" /></div>;
  const rows = audits.data?.audits ?? [];
  return (
    <div className="finance-page-shell">
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div><div className="text-[16px] font-semibold text-[var(--fg-1)]">LLM 调用审计</div><div className="mt-1 text-[11px] text-[var(--fg-4)]">统一记录所有 Gateway LLM/VLM 调用的配置、实际 Prompt、输入、输出和失败重试；历史缺失不回填。{reportIdFilter ? ` 当前报告：${reportIdFilter}` : ""}</div></div>
          <div className="flex flex-wrap items-center gap-2">
            <input type="password" value={tokenDraft} onChange={(event) => setTokenDraft(event.target.value)} placeholder="远程 Audit Token（本地可留空）" className="w-[240px] rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-[11px] text-[var(--fg-2)]" />
            <button type="button" className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-2 text-[11px] text-[var(--fg-3)]" onClick={() => { const value = tokenDraft.trim(); sessionStorage.setItem("finance_agent_audit_token", value); setAuditToken(value); }}>应用 Token</button>
            <button type="button" className="inline-flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-2 text-[11px] text-[var(--fg-3)]" onClick={audits.refetch}><RefreshCw size={13} />刷新</button>
          </div>
        </div>
        {audits.error ? <div className="rounded-[var(--radius-lg)] border border-[var(--down-border)] bg-[var(--down-soft)] p-3 text-[11px] text-[var(--status-down)]">{audits.error.message}；远程访问请确认后端 FINANCE_AGENT_AUDIT_READER_TOKEN 与当前输入一致。</div> : null}
        <div className="flex flex-wrap gap-2">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按调用模块筛选" className="min-w-[220px] rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-[11px] text-[var(--fg-2)]" />
          <select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-[11px] text-[var(--fg-2)]"><option value="">全部状态</option><option value="success">成功</option><option value="failed">失败</option></select>
        </div>
        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.7fr)]">
          <div className="space-y-2">
            <div className="text-[11px] text-[var(--fg-4)]">共 {audits.data?.count ?? 0} 条，当前 {rows.length} 条</div>
            {rows.map((row) => <button key={row.audit_id} type="button" onClick={() => setSelectedId(row.audit_id)} className={`w-full rounded-[var(--radius-lg)] border p-3 text-left ${selectedId === row.audit_id ? "border-[var(--accent)] bg-[var(--bg-hover)]" : "border-[var(--border)] bg-[var(--bg-card)]"}`}><div className="flex items-center justify-between gap-2"><span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{row.caller}</span><FAStatusPill tone={row.status === "success" ? "up" : "down"}>{row.status}</FAStatusPill></div><div className="mt-1 text-[10px] text-[var(--fg-4)]">{row.model_resolved ?? "-"} · {row.provider_resolved ?? "-"}</div><div className="mt-1 text-[10px] text-[var(--fg-5)]">{row.created_at ?? "-"} · Prompt {row.prompt_char_count} 字符 · 输出 {row.response_char_count} 字符</div></button>)}
            {rows.length === 0 ? <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-5 text-[11px] text-[var(--fg-4)]">暂无 Gateway 审计记录。新调用会自动出现在这里。</div> : null}
          </div>
          {detailError ? <div className="rounded-[var(--radius-lg)] border border-[var(--down-border)] bg-[var(--down-soft)] p-6 text-[12px] text-[var(--status-down)]">{detailError}</div> : <LLMAuditDetailPanel audit={selected} />}
        </div>
      </div>
    </div>
  );
}

export default LLMAuditPage;
