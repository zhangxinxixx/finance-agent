import type { ReactNode } from "react";

interface FAPageIntroProps {
  title: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function FAPageIntro({
  title,
  eyebrow,
  description,
  meta,
  action,
  className = "",
}: FAPageIntroProps) {
  return (
    <section className={`fa-page-intro ${className}`}>
      <div className="fa-page-intro-copy">
        {eyebrow ? <div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">{eyebrow}</div> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
        {meta ? <div className="fa-page-intro-meta mt-3">{meta}</div> : null}
      </div>

      {action ? <div className="fa-page-intro-side">{action}</div> : null}
    </section>
  );
}
