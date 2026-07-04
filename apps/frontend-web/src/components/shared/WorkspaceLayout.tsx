import type { ReactNode } from "react";

interface WorkspaceLayoutProps {
  main: ReactNode;
  rail?: ReactNode;
  className?: string;
  railWidth?: "sm" | "md" | "lg";
}

export function WorkspaceLayout({ main, rail, className = "", railWidth = "md" }: WorkspaceLayoutProps) {
  return (
    <div className={`workspace-layout workspace-layout--${railWidth} ${className}`}>
      <main className="workspace-layout__main">{main}</main>
      {rail ? <aside className="workspace-layout__rail">{rail}</aside> : null}
    </div>
  );
}
