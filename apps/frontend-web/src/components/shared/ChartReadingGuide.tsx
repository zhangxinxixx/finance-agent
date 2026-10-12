interface ChartReadingGuideProps {
  question: string;
  reference?: string | null;
  interpretation?: string | null;
  limits: readonly string[];
  className?: string;
}

export function ChartReadingGuide({
  question,
  reference,
  interpretation,
  limits,
  className = "",
}: ChartReadingGuideProps) {
  return (
    <section aria-label="图表阅读说明" className={className}>
      <dl className="grid gap-2 text-[length:var(--type-body-sm)] leading-5 text-[var(--fa-text-body)]">
        <div>
          <dt className="text-[length:var(--type-caption)] text-[var(--fa-text-label)]">看什么</dt>
          <dd className="m-0">{question}</dd>
        </div>
        <div>
          <dt className="text-[length:var(--type-caption)] text-[var(--fa-text-label)]">相对什么</dt>
          <dd className="m-0">{reference?.trim() ? reference : "比较基准未提供"}</dd>
        </div>
        <div>
          <dt className="text-[length:var(--type-caption)] text-[var(--fa-text-label)]">如何理解</dt>
          <dd className="m-0">{interpretation?.trim() ? interpretation : "后端未提供影响解释，本图仅展示观测。"}</dd>
        </div>
        <div>
          <dt className="text-[length:var(--type-caption)] text-[var(--fa-text-label)]">限制</dt>
          <dd className="m-0">
            {limits.length > 0 ? (
              <ul className="m-0 list-disc space-y-1 pl-4">
                {limits.map((limit, index) => <li key={index}>{limit}</li>)}
              </ul>
            ) : "限制未提供"}
          </dd>
        </div>
      </dl>
    </section>
  );
}
