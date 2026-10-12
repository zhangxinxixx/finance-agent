import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { ErrorState } from "@/components/shared/ErrorState";
import { MarketMonitorLoadingPanel } from "@/components/market-monitor/MarketMonitorSections";
import { readableWarning } from "@/lib/researchReading";

export function MarketMonitorPageLoadingState() {
  return (
    <FAPageScaffold className="market-monitor-page-shell">
      <MarketMonitorLoadingPanel />
    </FAPageScaffold>
  );
}

export function MarketMonitorPageErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <FAPageScaffold className="market-monitor-page-shell">
      <ErrorState
        title="市场监控加载失败"
        message={readableWarning(message)}
        onRetry={onRetry}
        retryLabel="重试"
      />
    </FAPageScaffold>
  );
}

export function MarketMonitorPageEmptyState() {
  return (
    <FAPageScaffold className="market-monitor-page-shell">
      <FAEmptyState
        title="暂无可展示的市场监控数据"
        description="当前返回结果没有任何可展示的市场、事件或溯源面板数据。"
      />
    </FAPageScaffold>
  );
}

export function MarketMonitorPageChrome({
  errorReason,
  source,
  requestError,
  historyError,
  isRefreshing,
}: {
  errorReason: string | null | undefined;
  source: string | null | undefined;
  requestError?: string | null;
  historyError?: string | null;
  isRefreshing?: boolean;
}) {
  return (
    <>
      {isRefreshing ? (
        <FAWarningBanner
          tone="info"
          title="正在更新市场监控"
          description="保留上次成功结果；当前刷新完成前，不把旧观测当作最新判断。"
        />
      ) : null}
      {requestError ? (
        <FAWarningBanner
          tone="down"
          title="本次市场监控刷新失败"
          description={`以下内容仍是上次成功读取，当前条件无法核验：${readableWarning(requestError)}`}
        />
      ) : null}
      {historyError ? (
        <FAWarningBanner
          tone="warn"
          title="历史窗口读取失败"
          description={`当前指标仍可查看，但历史曲线未完成本次更新：${readableWarning(historyError)}`}
        />
      ) : null}
      {errorReason || source === "mock" ? (
        <FAWarningBanner
          tone={source === "unavailable" ? "down" : source === "mock" ? "warn" : "info"}
          title={source === "api" ? "当前为接口归一化结果" : source === "mock" ? "当前结果为模拟数据" : "当前数据不可用"}
          description={errorReason || "结果已明确标记为模拟数据，不能当作实时市场判断。"}
        />
      ) : null}
    </>
  );
}
