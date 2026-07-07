import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type {
  StrategyDailyUpdateViewModel,
  StrategyHeroViewModel,
  StrategyScenarioViewModel,
  StrategyViewModel,
  StrategyWeekendContextViewModel,
  StrategyWeekendReportRefViewModel,
} from "@/types/strategy";
import { directionIcon, directionTone, formatConfidence, formatDate, sourceLabel, sourceTone, statusTone, strategySentence, strategyValueLabel } from "./strategyFormat";
import { SourceRefList } from "./StrategySourceRefs";

export function StrategyHeroSection({
  hero,
  scenario,
  dailyUpdate,
  weekendContext,
  asset,
  sampleSize,
  source,
  updatedAt,
}: {
  hero: StrategyHeroViewModel;
  scenario: StrategyScenarioViewModel | null;
  dailyUpdate: StrategyDailyUpdateViewModel | null;
  weekendContext: StrategyWeekendContextViewModel | null;
  asset: string;
  sampleSize: number;
  source: StrategyViewModel["source"];
  updatedAt?: string | null;
}) {
  const DirIcon = directionIcon(hero.direction);
  const tone = directionTone(hero.direction);
  const hasActionableBias = Boolean(hero.bias?.trim()) && hero.status !== "unavailable" && source !== "unavailable";
  const confidenceLabel = formatConfidence(hero.confidence);
  const freshness = getFrameworkFreshness(hero.trade_date ?? updatedAt ?? null);
  const executionState = getExecutionState(hero, freshness.isStale);
  const warningText = freshness.isStale
    ? `最新策略卡日期为 ${formatDate(hero.trade_date)}，距当前已 ${freshness.ageDays} 天；这不是今天的交易策略，只能作为历史框架参考。`
    : executionState.tone === "warn"
      ? executionState.description
      : null;

  return (
    <FACard title="总体分析框架" eyebrow="每日策略" accent="brand" bodyClassName="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={statusTone(hero.status)}>{strategyValueLabel(hero.status)}</FAStatusPill>
        <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
        <FAStatusPill tone="info">{asset}</FAStatusPill>
        <FAStatusPill tone={tone}>
          <DirIcon size={12} />
          {strategyValueLabel(hero.direction)}
        </FAStatusPill>
        <FAStatusPill tone="neutral">置信度 {confidenceLabel}</FAStatusPill>
        <FAStatusPill tone="neutral">{sampleSize} 样本</FAStatusPill>
        {hasActionableBias ? <FAStatusPill tone="dim">总体判断 {strategySentence(hero.bias)}</FAStatusPill> : null}
      </div>

      <TradingFrameworkSummary
        scenario={scenario}
        executionLabel={executionState.label}
        confidenceLabel={confidenceLabel}
        directionLabel={strategyValueLabel(hero.direction)}
        warningTitle={executionState.title}
        warningText={warningText}
        dailyUpdate={dailyUpdate}
        weekendContext={weekendContext}
        formalTradeDate={hero.trade_date}
      />

      <SourceRefList refs={hero.source_refs} />
    </FACard>
  );
}

function TradingFrameworkSummary({
  scenario,
  executionLabel,
  confidenceLabel,
  directionLabel,
  warningTitle,
  warningText,
  dailyUpdate,
  weekendContext,
  formalTradeDate,
}: {
  scenario: StrategyScenarioViewModel | null;
  executionLabel: string;
  confidenceLabel: string;
  directionLabel: string;
  warningTitle: string;
  warningText: string | null;
  dailyUpdate: StrategyDailyUpdateViewModel | null;
  weekendContext: StrategyWeekendContextViewModel | null;
  formalTradeDate: string | null;
}) {
  const mainScenario = strategySentence(scenario?.main_scenario) || "后端未生成主场景，当前不能给出日内交易框架。";
  const triggers = normalizeFrameworkItems([...(scenario?.trigger_conditions ?? []), ...(scenario?.confirmation_conditions ?? [])], 4);
  const invalidations = normalizeFrameworkItems([...(scenario?.invalidation_conditions ?? []), ...(scenario?.risk_points ?? [])], 5);
  const watchlist = normalizeFrameworkItems(scenario?.watchlist ?? [], 6);
  const resistance = scenario?.key_levels.resistance ?? [];
  const support = scenario?.key_levels.support ?? [];

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3.5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">交易框架摘要</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-1)]">{executionLabel}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <FAStatusPill tone="neutral">方向 {directionLabel}</FAStatusPill>
          <FAStatusPill tone="neutral">置信度 {confidenceLabel}</FAStatusPill>
        </div>
      </div>

      {warningText ? (
        <div className="mb-3 rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2">
          <div className="text-[10px] font-semibold text-[var(--warn)]">{warningTitle}</div>
          <div className="mt-0.5 text-[11px] leading-5 text-[var(--fg-3)]">{warningText}</div>
        </div>
      ) : null}

      <DailyUpdateBlock update={dailyUpdate} formalTradeDate={formalTradeDate} />

      <WeekendContextBlock context={weekendContext} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <FrameworkBlock label="主场景" body={mainScenario} />

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">关键价位</div>
          <LevelRow label="阻力" values={resistance} tone="down" />
          <LevelRow label="支撑" values={support} tone="up" />
          {!resistance.length && !support.length ? (
            <div className="mt-2 text-[10px] leading-5 text-[var(--fg-5)]">后端未生成关键价位，通常表示期权/技术输入不足。</div>
          ) : null}
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <FrameworkList label="触发/确认" items={triggers} emptyText="未生成触发或确认条件。" />
        <FrameworkList label="失效/风险" items={invalidations} emptyText="未生成失效条件或风险点。" />
        <FrameworkList label="观察清单" items={watchlist} emptyText="未生成观察清单。" />
      </div>
    </div>
  );
}

function WeekendContextBlock({ context }: { context: StrategyWeekendContextViewModel | null }) {
  if (!context || context.status !== "active") return null;
  const outlook = context.monday_outlook;
  const recent = (context.recent_context ?? []).filter(Boolean).slice(0, 3);
  const qualityText = context.quality_flags.length ? context.quality_flags.join(", ") : "上下文可用";
  return (
    <div className="mb-3 rounded-[var(--radius-md)] border border-[var(--brand-border)] bg-[var(--brand-soft)] px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">周末模式 · 周一开盘预测</div>
          <div className="mt-0.5 text-[12px] font-semibold text-[var(--fg-1)]">{outlook.direction}</div>
          <div className="mt-1 max-w-4xl text-[11px] leading-5 text-[var(--fg-3)]">{outlook.summary || context.message}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <FAStatusPill tone="info">最新 {formatDate(context.latest_report_date)}</FAStatusPill>
          <FAStatusPill tone={context.quality_flags.length ? "warn" : "up"}>{qualityText}</FAStatusPill>
        </div>
      </div>

      <div className="mt-2 grid gap-2 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">最后输入</div>
          <ReportRefLine label="周报" report={context.weekly_report} emptyText="未检测到明确周报，使用最新报告上下文兜底。" />
          {recent.length ? (
            <div className="mt-1.5 space-y-1">
              {recent.map((item, idx) => (
                <ReportRefLine key={`${item.type}-${item.trade_date}-${item.run_id}-${idx}`} label={idx === 0 ? "近两天" : ""} report={item} />
              ))}
            </div>
          ) : (
            <div className="mt-1 text-[10px] leading-5 text-[var(--fg-5)]">近两天暂无可读宏观/金十上下文。</div>
          )}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <CompactList label="开盘观察" items={outlook.watch_points} emptyText="暂无观察点。" />
          <CompactList label="失效条件" items={outlook.invalidation} emptyText="暂无失效条件。" />
        </div>
      </div>
    </div>
  );
}

function ReportRefLine({
  label,
  report,
  emptyText = "暂无",
}: {
  label: string;
  report?: StrategyWeekendReportRefViewModel | null;
  emptyText?: string;
}) {
  const title = report?.title || report?.type || emptyText;
  return (
    <div className="flex gap-2 text-[10px] leading-5 text-[var(--fg-3)]">
      {label ? <span className="w-10 shrink-0 text-[var(--fg-5)]">{label}</span> : <span className="w-10 shrink-0" />}
      <span className="min-w-0 flex-1 truncate">{title}</span>
      {report?.trade_date ? <span className="fa-num shrink-0 text-[var(--fg-5)]">{report.trade_date}</span> : null}
    </div>
  );
}

function CompactList({ label, items, emptyText }: { label: string; items: string[]; emptyText: string }) {
  const normalized = normalizeFrameworkItems(items ?? [], 3);
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      {normalized.length ? (
        <ul className="mt-1 space-y-1">
          {normalized.map((item, idx) => (
            <li key={`${label}-${idx}`} className="text-[10px] leading-5 text-[var(--fg-3)]">
              <span className="mr-1 text-[var(--fg-5)]">•</span>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-1 text-[10px] leading-5 text-[var(--fg-5)]">{emptyText}</div>
      )}
    </div>
  );
}

function DailyUpdateBlock({ update, formalTradeDate }: { update: StrategyDailyUpdateViewModel | null; formalTradeDate: string | null }) {
  const title = update?.date ? `今日更新层 ${update.date}` : "今日更新层";
  const message = update?.message || "今日更新层未接入或暂无可读状态。";
  const tone = update?.queue_count ? "var(--warn)" : "var(--up)";
  const hasFormalGenerationGap = Boolean(update?.date && formalTradeDate && !isSameCalendarDate(update.date, formalTradeDate));
  return (
    <div className="mb-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg)] px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{title}</div>
          <div className="mt-0.5 text-[11px] leading-5 text-[var(--fg-3)]">{message}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <FAStatusPill tone={update?.queue_count ? "warn" : "up"}>
            待加工 {update?.queue_count ?? 0}
          </FAStatusPill>
          <FAStatusPill tone="neutral">高优先 {update?.high_priority_count ?? 0}</FAStatusPill>
        </div>
      </div>
      {hasFormalGenerationGap ? (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2.5 py-2 text-[10px] leading-5 text-[var(--fg-3)]">
          <span className="font-semibold text-[var(--warn)]">正式策略缺口：</span>
          当前只检测到 {update?.date} 的更新层，正式 StrategyCard 仍锚定 {formalTradeDate}。
          缺少 `premarket` 综合分析生成任务，所以没有当天或前几天的正式分析策略。
        </div>
      ) : null}
      {update?.items?.length ? (
        <ul className="mt-2 grid gap-1.5 lg:grid-cols-2">
          {update.items.slice(0, 4).map((item, idx) => (
            <li key={`${item.title}-${idx}`} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5 text-[10px] leading-4 text-[var(--fg-3)]">
              <span className="mr-1 font-semibold" style={{ color: tone }}>{item.priority}</span>
              {item.title}
              {item.gold_impact ? <span className="ml-1 text-[var(--fg-5)]">· {strategyValueLabel(item.gold_impact)}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function isSameCalendarDate(left: string | null, right: string | null): boolean {
  return normalizeDateKey(left) === normalizeDateKey(right);
}

function normalizeDateKey(value: string | null): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text.slice(0, 10).replace(/\//g, "-");
}

function FrameworkBlock({ label, body }: { label: string; body: string }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg)] p-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <p className="mt-1 text-[12px] leading-6 text-[var(--fg-2)]">{body}</p>
    </div>
  );
}

function FrameworkList({ label, items, emptyText }: { label: string; items: string[]; emptyText: string }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg)] p-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      {items.length ? (
        <ul className="mt-1 space-y-1">
          {items.map((item, idx) => (
            <li key={`${label}-${idx}`} className="text-[11px] leading-5 text-[var(--fg-3)]">
              <span className="mr-1 text-[var(--fg-5)]">•</span>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-1 text-[10px] leading-5 text-[var(--fg-5)]">{emptyText}</div>
      )}
    </div>
  );
}

function LevelRow({ label, values, tone }: { label: string; values: number[]; tone: "up" | "down" }) {
  const className = tone === "up"
    ? "border-[var(--up-border)] bg-[var(--up-soft)] text-[var(--up)]"
    : "border-[var(--down-border)] bg-[var(--down-soft)] text-[var(--down)]";
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="w-8 text-[10px] text-[var(--fg-5)]">{label}</span>
      {values.length ? (
        values.slice(0, 5).map((level) => (
          <span key={`${label}-${level}`} className={`fa-num rounded-[var(--radius-sm)] border px-1.5 py-0.5 text-[10px] font-semibold ${className}`}>
            {level}
          </span>
        ))
      ) : (
        <span className="text-[10px] text-[var(--fg-5)]">--</span>
      )}
    </div>
  );
}

function normalizeFrameworkItems(items: string[], maxItems: number): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const text = strategySentence(item);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    result.push(text);
    if (result.length >= maxItems) break;
  }
  return result;
}

function getExecutionState(hero: StrategyHeroViewModel, isStale: boolean): { label: string; title: string; description: string; tone: "neutral" | "warn" } {
  if (isStale) {
    return {
      label: "历史框架，仅供回看",
      title: "策略卡不是今日数据",
      description: "最新策略卡日期滞后，不能作为今日执行依据。",
      tone: "warn",
    };
  }
  if (hero.confidence !== null && hero.confidence < 0.2) {
    return {
      label: "低置信度，等待确认",
      title: "当前框架不支持方向性执行",
      description: "后端给出的置信度低于 20%，应优先等待触发条件或补齐缺失输入。",
      tone: "warn",
    };
  }
  if (hero.direction === "bullish") return { label: "偏多框架，等待触发", title: "", description: "", tone: "neutral" };
  if (hero.direction === "bearish") return { label: "偏空框架，等待触发", title: "", description: "", tone: "neutral" };
  if (hero.direction === "neutral") return { label: "中性框架，等待方向选择", title: "", description: "", tone: "neutral" };
  return { label: "方向未知，等待后端生成", title: "策略方向缺失", description: "后端未返回可读方向。", tone: "warn" };
}

function getFrameworkFreshness(dateStr: string | null): { isStale: boolean; ageDays: number | null } {
  if (!dateStr) return { isStale: false, ageDays: null };
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) return { isStale: false, ageDays: null };
  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const dateStart = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate()).getTime();
  const ageDays = Math.floor((todayStart - dateStart) / 86_400_000);
  return { isStale: ageDays > 1, ageDays };
}
