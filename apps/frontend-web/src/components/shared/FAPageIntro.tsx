import type { ReactNode } from "react";

interface FAPageIntroProps {
  title: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  metaPlacement?: "body" | "side";
  action?: ReactNode;
  className?: string;
}

export function FAPageIntro({
  title,
  eyebrow,
  description,
  meta,
  metaPlacement = "body",
  action,
  className = "",
}: FAPageIntroProps) {
  const sideMeta = metaPlacement === "side" ? meta : null;
  const bodyMeta = metaPlacement === "body" ? meta : null;
  const hasSide = sideMeta || action;
  const sideClass = hasSide ? "fa-page-intro--with-side" : "";

  return (
    <section className={`fa-page-intro ${sideClass} ${className}`}>
      <div className="fa-page-intro-copy">
        {eyebrow ? <div className="fa-eyebrow">{eyebrow}</div> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
        {bodyMeta ? <div className="fa-page-intro-meta mt-3">{bodyMeta}</div> : null}
      </div>

      {hasSide ? (
        <div className="fa-page-intro-side">
          {sideMeta ? <div className="fa-page-intro-meta fa-page-intro-meta--side">{sideMeta}</div> : null}
          {action}
        </div>
      ) : null}
    </section>
  );
}
