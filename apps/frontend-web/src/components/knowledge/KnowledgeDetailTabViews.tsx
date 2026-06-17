import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { KnowledgeItem } from "@/types/knowledge";

const METRIC_TREND: Record<string, "up" | "down" | "flat"> = {
  positive: "up",
  negative: "down",
  neutral: "flat",
};

export function OverviewTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="space-y-3">
      <FACard title="基础信息" eyebrow="概览" accent="info" bodyClassName="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <FAMetricCard label="类型 / 主题" value={`${item.typeLabel} / ${item.topic}`} />
          <FAMetricCard label="版本 / 有效性" value={`${item.version} / ${item.status}`} />
          <FAMetricCard
            label="智能体 / 引用"
            value={`${item.agentReady ? "可调用" : "未接入"} / ${item.citations}`}
          />
          <FAMetricCard label="最近验证" value={item.verifiedAt} />
        </div>
      </FACard>

      <div className="grid gap-3 lg:grid-cols-2">
        <FACard title="核心摘要" eyebrow="摘要" accent="brand" bodyClassName="space-y-3">
          <p className="text-[12px] leading-relaxed text-[var(--fg-3)]">{item.summary}</p>
          <div className="h-px bg-[var(--border-faint)]" />
          <p className="text-[11px] font-semibold text-[var(--fg-2)]">这条知识解决什么问题</p>
          <p className="text-[12px] leading-relaxed text-[var(--fg-3)]">{item.thesis}</p>
        </FACard>

        <FACard title="核心规则预览" eyebrow="规则预览" accent="warn" bodyClassName="space-y-2">
          {item.rules.slice(0, 4).map((rule, index) => (
            <div key={index} className="flex gap-2 rounded-[var(--radius-md)] bg-[var(--bg-card-inner)] p-2">
              <span className="fa-num shrink-0 text-[10px] font-bold text-[var(--chart-1)]">
                R{String(index + 1).padStart(2, "0")}
              </span>
              <p className="text-[11px] leading-relaxed text-[var(--fg-3)]">{rule}</p>
            </div>
          ))}
          <p className="mt-1 text-[10px] text-[var(--fg-5)]">完整规则已放入「规则」标签页。</p>
        </FACard>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <FACard title="应用工作台" eyebrow="使用场景" accent="info" bodyClassName="space-y-2">
          {item.scenes.map((scene, index) => (
            <div key={index} className="flex gap-2 text-[11px] text-[var(--fg-3)]">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--chart-1)]" />
              <span className="leading-relaxed">{scene}</span>
            </div>
          ))}
        </FACard>

        <FACard title="触发 / 失效条件" eyebrow="条件说明" accent="warn" bodyClassName="space-y-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              触发条件
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--fg-3)]">
              {item.monitorMetrics.slice(0, 2).map((m) => `${m.label} ${m.change}`).join("；")}
            </p>
          </div>
          <div className="h-px bg-[var(--border-faint)]" />
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              失效条件
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--fg-3)]">
              {item.evidence[0]?.body ?? "暂无明确失效条件"}
            </p>
          </div>
        </FACard>
      </div>
    </div>
  );
}

export function RulesTab({ item }: { item: KnowledgeItem }) {
  return (
    <FACard title="核心规则" eyebrow="规则详情" accent="brand" bodyClassName="space-y-3">
      <p className="text-[11px] text-[var(--fg-4)]">
        用规则块替代长段正文，方便后续复用到 Prompt、Agent 和盘前会议。
      </p>
      <div className="max-h-[420px] overflow-y-auto pr-1">
        <div className="grid gap-2 lg:grid-cols-2">
          {item.rules.map((rule, index) => (
            <div
              key={index}
              className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3"
            >
              <span className="fa-num text-[10px] font-bold text-[var(--chart-1)]">
                R{String(index + 1).padStart(2, "0")}
              </span>
              <p className="mt-2 text-[12px] leading-relaxed text-[var(--fg-2)]">{rule}</p>
            </div>
          ))}
        </div>
      </div>
    </FACard>
  );
}

export function IOTab({ item }: { item: KnowledgeItem }) {
  const downstreamOutputs = item.downstream.map((d) => d.name);
  const citationOutputs = item.citationFlow.downstream.map((c) => c.title);
  const outputs = [...new Set([...downstreamOutputs, ...citationOutputs])].slice(0, 4);

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <FACard title="输入数据" eyebrow="输入" accent="info" bodyClassName="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {item.inputs.map((input) => (
              <span
                key={input}
                className="inline-flex items-center rounded-[var(--radius-pill)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[10px] text-[var(--fg-3)]"
              >
                {input}
              </span>
            ))}
          </div>
        </FACard>

        <FACard title="输出模块" eyebrow="输出" accent="brand" bodyClassName="space-y-2">
          {outputs.map((output) => (
            <div key={output} className="flex gap-2 text-[11px] text-[var(--fg-3)]">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--brand)]" />
              <span>{output}</span>
            </div>
          ))}
        </FACard>
      </div>

      <FACard title="适用场景" eyebrow="使用场景" accent="info" bodyClassName="space-y-2">
        {item.scenes.map((scene, index) => (
          <div key={index} className="flex gap-2 text-[11px] text-[var(--fg-3)]">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--chart-1)]" />
            <span className="leading-relaxed">{scene}</span>
          </div>
        ))}
      </FACard>
    </div>
  );
}

export function DependenciesTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="space-y-3">
      <FACard title="下游依赖" eyebrow="依赖关系" accent="brand" bodyClassName="space-y-2">
        <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
          {item.downstream.map((dep) => (
            <div
              key={dep.name}
              className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] font-semibold text-[var(--fg-2)]">{dep.name}</span>
                <FAStatusPill tone="info" dot={false}>
                  {dep.state}
                </FAStatusPill>
              </div>
              <p className="mt-1 text-[11px] text-[var(--fg-4)]">{dep.note}</p>
            </div>
          ))}
        </div>
      </FACard>

      <FACard title="剧本化建议" eyebrow="建议" accent="warn">
        <p className="text-[12px] leading-relaxed text-[var(--fg-3)]">
          当前条目的最佳沉淀形态是{" "}
          <span className="font-semibold text-[var(--fg-2)]">{item.typeLabel}</span>。
          如果下一步要强化复用，建议先补充{" "}
          <span className="font-semibold text-[var(--fg-2)]">
            {item.playbookReady ? "盘中动作模板" : "动作约束或失败案例"}
          </span>
          ，再决定是否升级成剧本模板。
        </p>
      </FACard>
    </div>
  );
}

export function ValidationTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="space-y-3">
      <FACard title="关键指标面" eyebrow="监控指标" accent="info" bodyClassName="space-y-3">
        <p className="text-[11px] text-[var(--fg-4)]">
          知识不是静态文档，需要绑定当前观测值、节奏约束和可执行动作。
        </p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {item.monitorMetrics.map((metric) => (
            <FAMetricCard
              key={metric.label}
              label={metric.label}
              value={metric.value}
              delta={metric.change}
              trend={METRIC_TREND[metric.tone]}
            />
          ))}
        </div>
      </FACard>

      <FACard title="验证证据" eyebrow="证据" accent="brand" bodyClassName="space-y-2">
        <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1">
          {item.evidence.map((entry, index) => (
            <div
              key={index}
              className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-[var(--fg-2)]">{entry.title}</span>
                <span className="fa-num text-[10px] text-[var(--fg-5)]">{entry.meta}</span>
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--fg-3)]">{entry.body}</p>
            </div>
          ))}
        </div>
      </FACard>

      <FACard title="验证时间线" eyebrow="时间线" accent="warn" bodyClassName="space-y-2">
        <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
          {item.timeline.map((entry, index) => (
            <div
              key={index}
              className="flex gap-3 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5"
            >
              <div className="mt-1 flex flex-col items-center">
                <span className="h-2 w-2 rounded-full bg-[var(--chart-1)] shadow-[0_0_6px_rgba(245,158,11,0.4)]" />
                {index < item.timeline.length - 1 && <span className="mt-1 w-px flex-1 bg-[var(--border)]" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold text-[var(--fg-2)]">{entry.title}</span>
                  <span className="fa-num shrink-0 text-[10px] text-[var(--fg-5)]">{entry.time}</span>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-[var(--fg-4)]">{entry.copy}</p>
              </div>
            </div>
          ))}
        </div>
      </FACard>
    </div>
  );
}

export function CitationsTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <FAMetricCard label="引用次数" value={item.citations} />
        <FAMetricCard label="来源数" value={item.references} />
        <FAMetricCard label="下游模块" value={item.dashboards} />
        <FAMetricCard label="资产形态" value={item.typeLabel} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <FACard title="上游引用" eyebrow="上游来源" accent="info" bodyClassName="space-y-2">
          <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
            {item.citationFlow.upstream.length > 0 ? (
              item.citationFlow.upstream.map((cite, index) => (
                <div
                  key={index}
                  className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5"
                >
                  <div className="text-[11px] font-semibold text-[var(--fg-2)]">{cite.title}</div>
                  <div className="mt-1 fa-num text-[10px] text-[var(--fg-5)]">{cite.meta}</div>
                </div>
              ))
            ) : (
              <p className="text-[11px] text-[var(--fg-4)]">当前没有显式上游来源，需补充原始依据。</p>
            )}
          </div>
        </FACard>

        <FACard title="下游消费" eyebrow="下游使用" accent="brand" bodyClassName="space-y-2">
          <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
            {item.citationFlow.downstream.map((cite, index) => (
              <div
                key={index}
                className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5"
              >
                <div className="text-[11px] font-semibold text-[var(--fg-2)]">{cite.title}</div>
                <div className="mt-1 fa-num text-[10px] text-[var(--fg-5)]">{cite.meta}</div>
              </div>
            ))}
          </div>
        </FACard>
      </div>
    </div>
  );
}
