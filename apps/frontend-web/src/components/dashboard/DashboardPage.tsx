import { EmptyState as SharedEmptyState } from "@/components/shared/EmptyState";
import { DashboardResearchBrief } from "./DashboardResearchBrief";
import type { AppShellOutletContext } from "@/components/AppShell";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useOutletContext } from "react-router-dom";
import type { DashboardDataResponse } from "@/types/dashboard";
import { GoldWorkspacePanel } from "@/components/gold-workspace/GoldWorkspacePanel";
import { readGoldReadingContext } from "@/components/gold-workspace/goldReadingNavigation";
import { GoldFrozenReport, readFrozenGoldReport } from "@/components/gold-workspace/GoldFrozenReport";
import "@/styles/gold-workspace.css";

export function DashboardPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const frozenReading = useMemo(() => readGoldReadingContext(location.state?.goldWorkspaceResult), [location.state]);
  const frozenReport = useMemo(() => readFrozenGoldReport(location.state?.frozenGoldReport), [location.state]);
  const [frozen, setFrozen] = useState<DashboardDataResponse | null>(() => location.state?.dashboardResult ?? null);
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    shell.setHeaderContent(<HeaderBreadcrumb title="黄金工作台" meta={<span className="dashboard-header-summary-item">{frozenReading || frozenReport ? `冻结研究 · ${frozenReading?.workspace.research.trade_date ?? frozenReport?.meta.trade_date ?? "日期未提供"}` : frozen ? `研究交易日：${frozen.summary?.integrated_macro?.trade_date || "未提供"}` : "行情 · 短线 · 长线 · 条件策略"}</span>} />);

    return () => shell.setHeaderContent(null);
  }, [frozen, frozenReading, frozenReport, shell]);

  return (
    <div className="finance-page-shell dashboard-page-shell">
      {frozen ? <><div className="fa-muted-text" role="status">
        已返回同一研究结果，当前行情工作台暂停刷新。
        <button type="button" className="ml-2 fa-label text-[var(--brand)]" onClick={() => { setFrozen(null); navigate("/dashboard", { replace: true, state: null }); }}>返回最新黄金工作台</button>
      </div>{frozen.has_data && frozen.summary ? <DashboardResearchBrief dashboardResult={frozen} />
        : <SharedEmptyState title="所选研究结果不可用" description="可以返回最新黄金工作台，或在报告中心重新选择研究。" />}</>
        : frozenReport ? <GoldFrozenReport report={frozenReport} onLatest={() => navigate("/dashboard", { replace: true, state: null })} />
        : <GoldWorkspacePanel key={frozenReading ? "frozen" : "latest"} frozenReading={frozenReading}
          onLatest={() => navigate("/dashboard", { replace: true, state: null })} />}
    </div>
  );
}

export default DashboardPage;
