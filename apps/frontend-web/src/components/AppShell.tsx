import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AppSidebar } from "./AppSidebar";
import { AppHeader } from "./AppHeader";
import { DataStatusBar } from "./shared/DataStatusBar";

type AppTheme = "light" | "dark";

export interface AppShellOutletContext {
  setHeaderContent: (content: ReactNode | null) => void;
}

function readInitialTheme(): AppTheme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem("finance-agent-theme");
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readInitialSidebarCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia?.("(max-width: 840px)").matches) return true;
  const stored = window.localStorage.getItem("finance-agent-sidebar-collapsed");
  return stored === "true";
}

export function AppShell() {
  const location = useLocation();
  const contentRef = useRef<HTMLElement | null>(null);
  const routeContentKey = `${location.pathname}${location.search}`;
  const [theme, setTheme] = useState<AppTheme>(readInitialTheme);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readInitialSidebarCollapsed);
  const [headerContent, setHeaderContent] = useState<ReactNode | null>(null);
  const outletContext = useMemo<AppShellOutletContext>(() => ({ setHeaderContent }), []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("finance-agent-theme", theme);
  }, [theme]);

  function toggleSidebarCollapsed() {
    setSidebarCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("finance-agent-sidebar-collapsed", next ? "true" : "false");
      return next;
    });
  }

  useLayoutEffect(() => {
    const resetScroll = () => {
      contentRef.current?.scrollTo({ top: 0, left: 0 });
    };

    resetScroll();
    const frame = window.requestAnimationFrame(resetScroll);
    const timeout = window.setTimeout(resetScroll, 150);

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
    };
  }, [location.pathname, location.search]);

  return (
    <div className={`app-frame text-finance-text-primary ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <div className="app-shell">
        <AppSidebar collapsed={sidebarCollapsed} onToggleCollapsed={toggleSidebarCollapsed} />

        <div className="app-main">
          <AppHeader theme={theme} onToggleTheme={() => setTheme((current) => (current === "dark" ? "light" : "dark"))} headerContent={headerContent} />

          <main ref={contentRef} className="app-content">
            <div key={routeContentKey} className="app-content-inner">
              <Outlet context={outletContext} />
            </div>
          </main>

          <DataStatusBar />
        </div>
      </div>
    </div>
  );
}
