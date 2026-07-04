import type { CMEOptionsCalibration, CMEOptionsDataSource, CMEOptionsNetGEXAggregate, CMEOptionsWallScore } from "@/types/cme-options";
import { FACard } from "../shared/FACard";
import { FAMetricCard } from "../shared/FAMetricCard";
import { FAStatusPill, type FAStatusTone } from "../shared/FAStatusPill";

interface OptionsMarketReadoutProps {
  dataSource: CMEOptionsDataSource;
  netGexAggregate: CMEOptionsNetGEXAggregate;
  wallScores: CMEOptionsWallScore[];
  intent: {
    type: string;
    confidence: number;
    score?: number;
    evidence?: string[];
  };
  calibration: CMEOptionsCalibration;
}

function formatPrice(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

function sourceStatusTone(status: CMEOptionsDataSource["status"] | null | undefined): FAStatusTone {
  if (status === "FINAL") return "up";
  if (status === "PRELIM") return "warn";
  return "dim";
}

function sourceStatusLabel(status: CMEOptionsDataSource["status"] | null | undefined) {
  if (status === "FINAL") return "终版";
  if (status === "PRELIM") return "预览";
  return "未知";
}

function strongestBySide(wallScores: CMEOptionsWallScore[], side: "CALL" | "PUT") {
  return [...wallScores]
    .filter((wall) => wall.side === side)
    .sort((left, right) => right.wall_score - left.wall_score)[0] ?? null;
}

function topPinWall(wallScores: CMEOptionsWallScore[]) {
  return [...wallScores]
    .sort((left, right) => {
      if (right.wall_score !== left.wall_score) return right.wall_score - left.wall_score;
      return right.oi - left.oi;
    })
    .find((wall) => wall.wall_type === "Pin Wall") ?? null;
}

export function OptionsMarketReadout({ dataSource, netGexAggregate, wallScores, calibration }: OptionsMarketReadoutProps) {
  const gammaZero = netGexAggregate.gamma_zero?.price;
  const callWall = strongestBySide(wallScores, "CALL");
  const putWall = strongestBySide(wallScores, "PUT");
  const pinWall = topPinWall(wallScores);

  return (
    <FACard
      title="结构摘要"
      accent="brand"
      action={<FAStatusPill tone={sourceStatusTone(dataSource.status)}>{sourceStatusLabel(dataSource.status)}</FAStatusPill>}
      bodyClassName="space-y-2"
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <FAMetricCard label="伽马零点" value={formatPrice(gammaZero, 1)} hint="价格围绕该线切换伽马环境" />
        <FAMetricCard label="吸附墙" value={formatPrice(pinWall?.strike)} hint={`持仓 ${formatPrice(pinWall?.oi)} · 评分 ${formatScore(pinWall?.wall_score)}`} />
        <FAMetricCard label="看涨压制" value={formatPrice(callWall?.strike)} hint={`评分 ${formatScore(callWall?.wall_score)} · 持仓 ${formatPrice(callWall?.oi)}`} trend="down" delta="上方压制" />
        <FAMetricCard label="看跌支撑" value={formatPrice(putWall?.strike)} hint={`评分 ${formatScore(putWall?.wall_score)} · 持仓 ${formatPrice(putWall?.oi)}`} trend="up" delta="下方支撑" />
      </div>

      {calibration.calibration_warnings?.[0] ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
          <div className="text-[length:var(--text-10)] leading-4 text-[var(--fg-4)]">{calibration.calibration_warnings[0]}</div>
        </div>
      ) : null}
    </FACard>
  );
}
