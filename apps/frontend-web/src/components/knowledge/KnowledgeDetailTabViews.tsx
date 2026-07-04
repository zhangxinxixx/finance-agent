import type { ReactNode } from "react";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { KnowledgeCitation, KnowledgeItem } from "@/types/knowledge";

export function OverviewTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="knowledge-reader-stack">
      <ReaderSection title="基础信息" eyebrow="概览">
        <div className="knowledge-field-grid">
          <Field label="类型 / 主题" value={`${item.typeLabel} / ${item.topic}`} />
          <Field label="版本 / 有效性" value={`${item.version} / ${item.status}`} />
          <Field label="智能体 / 引用" value={`${item.agentReady ? "可调用" : "未接入"} / ${item.citations}`} />
          <Field label="最近验证" value={item.verifiedAt} />
        </div>
      </ReaderSection>

      <div className="knowledge-reader-split">
        <ReaderSection title="核心摘要" eyebrow="摘要">
          <p className="knowledge-reader-copy">{item.summary}</p>
          <div className="knowledge-reader-divider" />
          <div className="knowledge-reader-subtitle">这条知识解决什么问题</div>
          <p className="knowledge-reader-copy">{item.thesis}</p>
        </ReaderSection>

        <ReaderSection title="核心规则预览" eyebrow="规则预览" tone="warn">
          <RuleList rules={item.rules.slice(0, 4)} />
          <p className="knowledge-reader-note">完整规则已放入「规则」标签页。</p>
        </ReaderSection>
      </div>

      <div className="knowledge-reader-split">
        <ReaderSection title="应用工作台" eyebrow="使用场景">
          <BulletList items={item.scenes} />
        </ReaderSection>

        <ReaderSection title="触发 / 失效条件" eyebrow="条件说明" tone="warn">
          <div className="knowledge-definition-list">
            <Field label="触发条件" value={item.monitorMetrics.slice(0, 2).map((m) => `${m.label} ${m.change}`).join("；")} />
            <Field label="失效条件" value={item.evidence[0]?.body ?? "暂无明确失效条件"} />
          </div>
        </ReaderSection>
      </div>
    </div>
  );
}

export function RulesTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="knowledge-reader-stack">
      <ReaderSection title="核心规则" eyebrow="规则详情" description="规则以行式结构呈现，方便复用到 Prompt、Agent 和盘前会议。">
        <div className="knowledge-rule-list knowledge-rule-list--full">
          {item.rules.map((rule, index) => (
            <RuleItem key={index} rule={rule} index={index} />
          ))}
        </div>
      </ReaderSection>
    </div>
  );
}

export function IOTab({ item }: { item: KnowledgeItem }) {
  const downstreamOutputs = item.downstream.map((d) => d.name);
  const citationOutputs = item.citationFlow.downstream.map((c) => c.title);
  const outputs = [...new Set([...downstreamOutputs, ...citationOutputs])].slice(0, 4);

  return (
    <div className="knowledge-reader-stack">
      <div className="knowledge-reader-split">
        <ReaderSection title="输入数据" eyebrow="输入">
          <PillList items={item.inputs} />
        </ReaderSection>

        <ReaderSection title="输出模块" eyebrow="输出">
          <BulletList items={outputs} />
        </ReaderSection>
      </div>

      <ReaderSection title="适用场景" eyebrow="使用场景">
        <BulletList items={item.scenes} />
      </ReaderSection>
    </div>
  );
}

export function DependenciesTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="knowledge-reader-stack">
      <ReaderSection title="下游依赖" eyebrow="依赖关系">
        <div className="knowledge-row-list">
          {item.downstream.map((dep) => (
            <div key={dep.name} className="knowledge-row-item">
              <div className="min-w-0">
                <div className="knowledge-row-title">{dep.name}</div>
                <p className="knowledge-row-copy">{dep.note}</p>
              </div>
              <FAStatusPill tone="info" dot={false}>
                {dep.state}
              </FAStatusPill>
            </div>
          ))}
        </div>
      </ReaderSection>

      <ReaderSection title="剧本化建议" eyebrow="建议" tone="warn">
        <p className="knowledge-reader-copy">
          当前条目的最佳沉淀形态是 <strong>{item.typeLabel}</strong>。如果下一步要强化复用，建议先补充{" "}
          <strong>{item.playbookReady ? "盘中动作模板" : "动作约束或失败案例"}</strong>，再决定是否升级成剧本模板。
        </p>
      </ReaderSection>
    </div>
  );
}

export function ValidationTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="knowledge-reader-stack">
      <ReaderSection title="关键指标面" eyebrow="监控指标" description="知识不是静态文档，需要绑定当前观测值、节奏约束和可执行动作。">
        <div className="knowledge-metric-table">
          {item.monitorMetrics.map((metric) => (
            <div key={metric.label} className={`knowledge-metric-row knowledge-metric-row--${metric.tone}`}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <em>{metric.change}</em>
            </div>
          ))}
        </div>
      </ReaderSection>

      <ReaderSection title="验证证据" eyebrow="证据">
        <div className="knowledge-row-list">
          {item.evidence.map((entry, index) => (
            <div key={index} className="knowledge-row-item knowledge-row-item--stacked">
              <div className="knowledge-row-meta">
                <span>{entry.title}</span>
                <span className="fa-num">{entry.meta}</span>
              </div>
              <p className="knowledge-row-copy">{entry.body}</p>
            </div>
          ))}
        </div>
      </ReaderSection>

      <ReaderSection title="验证时间线" eyebrow="时间线" tone="warn">
        <div className="knowledge-timeline">
          {item.timeline.map((entry, index) => (
            <div key={index} className="knowledge-timeline-row">
              <span className="knowledge-timeline-dot" />
              <div className="min-w-0">
                <div className="knowledge-row-meta">
                  <span>{entry.title}</span>
                  <span className="fa-num">{entry.time}</span>
                </div>
                <p className="knowledge-row-copy">{entry.copy}</p>
              </div>
            </div>
          ))}
        </div>
      </ReaderSection>
    </div>
  );
}

export function CitationsTab({ item }: { item: KnowledgeItem }) {
  return (
    <div className="knowledge-reader-stack">
      <div className="knowledge-fact-strip knowledge-fact-strip--inline">
        <InlineFact label="引用次数" value={item.citations} />
        <InlineFact label="来源数" value={item.references} />
        <InlineFact label="下游模块" value={item.dashboards} />
        <InlineFact label="资产形态" value={item.typeLabel} />
      </div>

      <div className="knowledge-reader-split">
        <ReaderSection title="上游引用" eyebrow="上游来源">
          <CitationList citations={item.citationFlow.upstream} emptyText="当前没有显式上游来源，需补充原始依据。" />
        </ReaderSection>

        <ReaderSection title="下游消费" eyebrow="下游使用">
          <CitationList citations={item.citationFlow.downstream} />
        </ReaderSection>
      </div>
    </div>
  );
}

function ReaderSection({
  title,
  eyebrow,
  description,
  tone = "info",
  children,
}: {
  title: string;
  eyebrow: string;
  description?: string;
  tone?: "info" | "warn";
  children: ReactNode;
}) {
  return (
    <section className={`knowledge-reader-section knowledge-reader-section--${tone}`}>
      <header className="knowledge-reader-section-header">
        <span>{eyebrow}</span>
        <strong>{title}</strong>
        {description ? <p>{description}</p> : null}
      </header>
      <div className="knowledge-reader-section-body">{children}</div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="knowledge-field">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function InlineFact({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="knowledge-fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function RuleList({ rules }: { rules: string[] }) {
  return (
    <div className="knowledge-rule-list">
      {rules.map((rule, index) => (
        <RuleItem key={index} rule={rule} index={index} />
      ))}
    </div>
  );
}

function RuleItem({ rule, index }: { rule: string; index: number }) {
  return (
    <div className="knowledge-rule-item">
      <span className="fa-num">R{String(index + 1).padStart(2, "0")}</span>
      <p>{rule}</p>
    </div>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <div className="knowledge-bullet-list">
      {items.map((item, index) => (
        <div key={index} className="knowledge-bullet-row">
          <span />
          <p>{item}</p>
        </div>
      ))}
    </div>
  );
}

function PillList({ items }: { items: string[] }) {
  return (
    <div className="knowledge-pill-list">
      {items.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  );
}

function CitationList({
  citations,
  emptyText = "暂无引用记录。",
}: {
  citations: KnowledgeCitation[];
  emptyText?: string;
}) {
  if (citations.length === 0) {
    return <p className="knowledge-reader-note">{emptyText}</p>;
  }

  return (
    <div className="knowledge-row-list">
      {citations.map((cite, index) => (
        <div key={index} className="knowledge-row-item knowledge-row-item--stacked">
          <div className="knowledge-row-title">{cite.title}</div>
          <div className="fa-num knowledge-row-submeta">{cite.meta}</div>
        </div>
      ))}
    </div>
  );
}
