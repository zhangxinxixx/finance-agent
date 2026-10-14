import { readingErrorMessage } from "@/components/reading/readingFormat";

interface ReportsReadStatusProps {
  kind: "index" | "dates";
  loading: boolean;
  error: Error | null;
  hasLoaded: boolean;
  readAt: string | null;
  latestDate?: string;
}

/** Transport status only. Report qualification and research times stay in the DTO. */
export function ReportsReadStatus({ kind, loading, error, hasLoaded, readAt, latestDate }: ReportsReadStatusProps) {
  const label = kind === "index" ? "报告索引" : "报告日期";
  const previous = kind === "index" ? "上次报告索引" : "上次日期结果";
  const message = error
    ? `${kind === "dates" ? "报告日期暂不可用" : "报告索引刷新失败"}。${hasLoaded ? `保留${previous}。` : "尚无成功读取结果。"} ${readingErrorMessage(error, `${label}读取失败，请重试。`)}`
    : loading
      ? `正在${hasLoaded ? "刷新" : "读取"}${label}…${hasLoaded ? `暂用${previous}。` : ""}`
      : `${label}读取完成。`;

  return (
    <p role={error ? "alert" : "status"} className="fa-muted-text" data-report-read-status={kind}>
      {message}
      {kind === "dates" && latestDate ? ` ${loading || error ? "上次日期" : "最新报告日期"}：${latestDate}。` : null}
      {readAt ? <> {loading || error ? "上次成功读取" : "读取完成于"} <time dateTime={readAt}>{new Date(readAt).toLocaleString("zh-CN", { hour12: false })}</time>。</> : null}
      {readAt ? " 接口读取时间，非研究数据时点。" : null}
    </p>
  );
}
