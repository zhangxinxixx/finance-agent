import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { ErrorState } from "@/components/shared/ErrorState";
import { MarketMonitorLoadingPanel, MarketMonitorWeekendBanner } from "@/components/market-monitor/MarketMonitorSections";

export function MarketMonitorPageLoadingState() {
  return <MarketMonitorLoadingPanel />;
}

export function MarketMonitorPageErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <ErrorState
      title="Market Monitor 加载失败"
      message={message}
      onRetry={onRetry}
      retryLabel="重试"
    />
  );
}

export function MarketMonitorPageEmptyState() {
  return (
    <FAEmptyState
      title="暂无可展示的市场监控数据"
      description="当前返回结果缺少 has_data 或 metrics 内容，页面保留新设计骨架并显式标记 unavailable。"
    />
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
      <MarketMonitorWeekendBanner />
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
