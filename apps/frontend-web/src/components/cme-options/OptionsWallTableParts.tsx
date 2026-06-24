import { FACard } from "../shared/FACard";
import { FAStatusPill, type FAStatusTone } from "../shared/FAStatusPill";
import type { CMEOptionsWallScore } from "../../types/cme-options";

export type OptionsWallSortKey =
  | "strike"
  | "wall_type"
  | "oi"
  | "delta_oi"
  | "wall_score"
  | "pnt";
export type OptionsWallSortDirection = "asc" | "desc";

const MONO_CELL = "font-mono tabular-nums";
const HEADER_CLASS_NAME =
  "px-3 py-2 text-left text-[11px] font-semibold tracking-[0.1em] text-[var(--fg-4)]";
const CELL_CLASS_NAME = "px-3 py-2 align-middle text-[12px] text-[var(--fg-3)]";
const NUMERIC_CLASS_NAME = `${CELL_CLASS_NAME} ${MONO_CELL}`;
const HEADER_BUTTON_CLASS_NAME =
  "inline-flex w-full items-center justify-between gap-2 rounded px-1 py-0.5 transition-colors hover:bg-[var(--bg-hover)]";

const WALL_COLUMNS: Array<{ key: OptionsWallSortKey; label: string }> = [
  { key: "strike", label: "行权价" },
  { key: "wall_type", label: "墙型" },
  { key: "oi", label: "持仓" },
  { key: "delta_oi", label: "持仓变化" },
  { key: "wall_score", label: "评分" },
  { key: "pnt", label: "吸附值" },
];

function formatInteger(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatScore(value: number) {
  return value.toFixed(2);
}

function formatDelta(value: number | null) {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatInteger(value)}`;
}

function compareValues(
  a: CMEOptionsWallScore,
  b: CMEOptionsWallScore,
  sortKey: OptionsWallSortKey,
) {
  switch (sortKey) {
    case "strike":
      return a.strike - b.strike;
    case "oi":
      return a.oi - b.oi;
    case "delta_oi": {
      const aValue = a.delta_oi ?? Number.NEGATIVE_INFINITY;
      const bValue = b.delta_oi ?? Number.NEGATIVE_INFINITY;
      return aValue - bValue;
    }
    case "wall_score":
      return a.wall_score - b.wall_score;
    case "pnt":
      return a.pnt - b.pnt;
    case "wall_type":
      return a.wall_type.localeCompare(b.wall_type);
    default:
      return 0;
  }
}

export function sortWallRows(
  rows: CMEOptionsWallScore[],
  sortKey: OptionsWallSortKey,
  direction: OptionsWallSortDirection,
) {
  const sorted = [...rows].sort((a, b) => {
    const result = compareValues(a, b, sortKey);
    if (result !== 0) return direction === "asc" ? result : -result;

    const wallScoreResult = b.wall_score - a.wall_score;
    if (wallScoreResult !== 0) return wallScoreResult;

    return b.strike - a.strike;
  });

  return sorted;
}

function wallStatus(wallType: CMEOptionsWallScore["wall_type"]): FAStatusTone {
  if (wallType === "Call Wall") return "up";
  if (wallType === "Put Wall") return "down";
  if (wallType === "Pin Wall") return "warn";
  return "info";
}

function wallAccentClassName(wallType: CMEOptionsWallScore["wall_type"]) {
  if (wallType === "Call Wall") return "border-l-2 border-l-[var(--up)]";
  if (wallType === "Put Wall") return "border-l-2 border-l-[var(--down)]";
  if (wallType === "Pin Wall") return "border-l-2 border-l-[var(--warn)]";
  return "border-l-2 border-l-[var(--brand-hover)]";
}

function deltaClassName(deltaOi: CMEOptionsWallScore["delta_oi"]) {
  if (deltaOi === null) return "text-[var(--fg-4)]";
  if (deltaOi > 0) return "text-[var(--up)]";
  if (deltaOi < 0) return "text-[var(--down)]";
  return "text-[var(--fg-3)]";
}

function wallTypeLabel(wallType: CMEOptionsWallScore["wall_type"]) {
  const labels: Record<CMEOptionsWallScore["wall_type"], string> = {
    "Call Wall": "看涨压力墙",
    "Put Wall": "看跌支撑墙",
    "Balanced Wall": "均衡墙",
    "Active Wall": "活跃墙",
    "Pin Wall": "吸附墙",
    "Static Wall": "静态墙",
    "Turnover Wall": "换手墙",
    "New Wall": "新增墙",
    "Resistance Wall": "阻力墙",
    "Support Wall": "支撑墙",
  };
  return labels[wallType] ?? wallType;
}

interface OptionsWallTableHeaderProps {
  sortKey: OptionsWallSortKey;
  sortDirection: OptionsWallSortDirection;
  onHeaderClick: (key: OptionsWallSortKey) => void;
  getAriaSort: (key: OptionsWallSortKey) => "none" | "ascending" | "descending";
}

export function OptionsWallTableHeader({
  sortKey,
  sortDirection,
  onHeaderClick,
  getAriaSort,
}: OptionsWallTableHeaderProps) {
  return (
    <thead className="bg-[var(--bg-panel)]">
      <tr>
        {WALL_COLUMNS.map((column) => (
          <th
            key={column.key}
            className={HEADER_CLASS_NAME}
            scope="col"
            aria-sort={getAriaSort(column.key)}
          >
            <button
              type="button"
              className={HEADER_BUTTON_CLASS_NAME}
              onClick={() => onHeaderClick(column.key)}
            >
              <span>{column.label}</span>
              <span className="text-[10px] text-[var(--fg-5)]">
                {sortKey === column.key ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}
              </span>
            </button>
          </th>
        ))}
      </tr>
    </thead>
  );
}

interface OptionsWallTableRowProps {
  row: CMEOptionsWallScore;
  index: number;
}

function OptionsWallTableRow({ row, index }: OptionsWallTableRowProps) {
  const rowClassName = index % 2 === 0 ? "bg-[var(--bg-card)]" : "bg-[var(--bg-panel)]";

  return (
    <tr
      className={`group border-b border-[var(--border)] transition-colors hover:bg-[var(--bg-hover)] ${rowClassName}`}
    >
      <td className={`${CELL_CLASS_NAME} ${wallAccentClassName(row.wall_type)} whitespace-nowrap`}>
        <span className={MONO_CELL}>{formatInteger(row.strike)}</span>
      </td>
      <td className={CELL_CLASS_NAME}>
        <FAStatusPill tone={wallStatus(row.wall_type)}>{wallTypeLabel(row.wall_type)}</FAStatusPill>
      </td>
      <td className={`${NUMERIC_CLASS_NAME} whitespace-nowrap`}>{formatInteger(row.oi)}</td>
      <td className={`${NUMERIC_CLASS_NAME} whitespace-nowrap ${deltaClassName(row.delta_oi)}`}>
        {formatDelta(row.delta_oi)}
      </td>
      <td className={`${NUMERIC_CLASS_NAME} whitespace-nowrap`}>{formatScore(row.wall_score)}</td>
      <td className={`${NUMERIC_CLASS_NAME} whitespace-nowrap`}>{formatScore(row.pnt)}</td>
    </tr>
  );
}

interface OptionsWallTableRowsProps {
  rows: CMEOptionsWallScore[];
}

export function OptionsWallTableRows({ rows }: OptionsWallTableRowsProps) {
  return (
    <tbody>
      {rows.map((row, index) => (
        <OptionsWallTableRow
          key={`${row.wall_type}-${row.strike}-${index}`}
          row={row}
          index={index}
        />
      ))}
    </tbody>
  );
}

export function OptionsWallEmptyState() {
  return (
    <FACard title="墙位明细" eyebrow="墙位评分" accent="warn">
      <div className="flex min-h-32 items-center justify-center rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] bg-[var(--bg-card-inner)] px-4 py-8 text-sm text-[var(--fg-4)]">
        该日期无期权数据
      </div>
    </FACard>
  );
}
