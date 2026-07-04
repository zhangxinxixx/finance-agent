import type { ReactNode } from "react";

interface InspectorRailProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function InspectorRail({ title, subtitle, children, className = "" }: InspectorRailProps) {
  return (
    <section className={`inspector-rail ${className}`}>
      {title || subtitle ? (
        <header className="inspector-rail__header">
          {title ? <div className="inspector-rail__title">{title}</div> : null}
          {subtitle ? <div className="inspector-rail__subtitle">{subtitle}</div> : null}
        </header>
      ) : null}
      <div className="inspector-rail__body">{children}</div>
    </section>
  );
}
