import type { ReactNode } from "react";

interface HeaderBreadcrumbProps {
  title: ReactNode;
  rootLabel?: ReactNode;
  meta?: ReactNode;
}

export function HeaderBreadcrumb({ title, rootLabel = "金融分析中台", meta }: HeaderBreadcrumbProps) {
  const titleText = typeof title === "string" ? title : undefined;

  return (
    <div className="header-breadcrumb-summary" aria-label={titleText}>
      <div className="header-breadcrumb">
        <span className="header-breadcrumb-root">{rootLabel}</span>
        <span className="header-breadcrumb-separator">/</span>
        <span className="header-breadcrumb-title" title={titleText} aria-current="page">{title}</span>
      </div>
      {meta ? <div className="header-breadcrumb-meta">{meta}</div> : null}
    </div>
  );
}
