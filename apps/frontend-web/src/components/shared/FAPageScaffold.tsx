import type { ReactNode } from "react";

interface FAPageScaffoldProps {
  intro?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function FAPageScaffold({
  intro,
  toolbar,
  children,
  className = "",
  bodyClassName = "",
}: FAPageScaffoldProps) {
  return (
    <div className={`finance-page-shell ${className}`}>
      {intro}
      {toolbar}
      <div className={`fa-layout-fill ${bodyClassName}`}>{children}</div>
    </div>
  );
}
