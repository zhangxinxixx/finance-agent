import type { ReactNode } from "react";

interface PageSummaryProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function PageSummary({ eyebrow, title, description, meta, actions, className = "" }: PageSummaryProps) {
  return (
    <section className={`page-summary ${className}`}>
      <div className="page-summary__main">
        {eyebrow ? <div className="page-summary__eyebrow">{eyebrow}</div> : null}
        <div className="page-summary__title">{title}</div>
        {description ? <div className="page-summary__description">{description}</div> : null}
        {meta ? <div className="page-summary__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-summary__actions">{actions}</div> : null}
    </section>
  );
}
