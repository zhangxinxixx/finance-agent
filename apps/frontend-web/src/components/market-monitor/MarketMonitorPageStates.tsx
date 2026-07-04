import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { ErrorState } from "@/components/shared/ErrorState";
import { MarketMonitorLoadingPanel } from "@/components/market-monitor/MarketMonitorSections";

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
        message={message}
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
}: {
  errorReason: string | null | undefined;
  source: string | null | undefined;
}) {
  return (
    <>
      {errorReason ? (
        <FAWarningBanner
          tone={source === "unavailable" ? "down" : "info"}
          title={source === "api" ? "当前为 API 归一化结果" : "页面已降级到 mock / unavailable"}
          description={errorReason}
        />
      ) : null}
    </>
  );
}
