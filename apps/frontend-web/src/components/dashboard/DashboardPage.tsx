import { EmptyState as SharedEmptyState } from "@/components/shared/EmptyState";
import { DashboardResearchBrief } from "./DashboardResearchBrief";
import type { AppShellOutletContext } from "@/components/AppShell";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { useEffect, useState } from "react";
import { useLocation, useOutletContext } from "react-router-dom";
import type { DashboardDataResponse } from "@/types/dashboard";
import { GoldWorkspacePanel } from "@/components/gold-workspace/GoldWorkspacePanel";

export function DashboardPage() {
  const location = useLocation();
  const [frozen, setFrozen] = useState<DashboardDataResponse | null>(() => location.state?.dashboardResult ?? null);
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    shell.setHeaderContent(<HeaderBreadcrumb title="黄金工作台" meta={<span className="dashboard-header-summary-item">{frozen ? `研究交易日：${frozen.summary?.integrated_macro?.trade_date || "未提供"}` : "行情 · 短线 · 长线 · 条件策略"}</span>} />);

    return () => shell.setHeaderContent(null);
  }, [frozen, shell]);

  return (
    <div className="finance-page-shell dashboard-page-shell">
      {frozen ? <><div className="fa-muted-text" role="status">
        已返回同一研究结果，当前行情工作台暂停刷新。
        <button type="button" className="ml-2 fa-label text-[var(--brand)]" onClick={() => setFrozen(null)}>返回最新黄金工作台</button>
      </div>{frozen.has_data && frozen.summary ? <DashboardResearchBrief dashboardResult={frozen} />
        : <SharedEmptyState title="所选研究结果不可用" description="可以返回最新黄金工作台，或在报告中心重新选择研究。" />}</>
        : <GoldWorkspacePanel />}
    </div>
  );
}

export default DashboardPage;
