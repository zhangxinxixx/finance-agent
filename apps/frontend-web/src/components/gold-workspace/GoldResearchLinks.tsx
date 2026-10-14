import { Link, useNavigate } from "react-router-dom";
import type { MouseEvent } from "react";
import type { GoldWorkspace } from "@/types/gold-workspace";
import { captureGoldReadingContext, goldStrategyNavigation } from "./goldReadingNavigation";

export function GoldResearchLinks({ data }: { data: GoldWorkspace }) {
  const navigate = useNavigate();
  function open(event: MouseEvent<HTMLAnchorElement>, target: string, strategy = false) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const context = captureGoldReadingContext(data, event.currentTarget);
    // Preserve the source entry as well, so browser Back has the same frozen result.
    navigate("/dashboard", { replace: true, state: { goldWorkspaceResult: context } });
    navigate(target, { state: strategy ? goldStrategyNavigation(context) : { goldWorkspaceResult: context } });
  }
  const report = data.research.report_id ? `/reports/${encodeURIComponent(data.research.report_id)}` : null;
  return <div className="gold-decision-links">
    {report && data.research.status !== "unavailable" ? <Link to={report} onClick={event => open(event, report)}>查看同一研究报告 →</Link> : null}
    <Link to="/strategy" onClick={event => open(event, "/strategy", true)}>查看策略条件与执行核验 →</Link>
  </div>;
}
