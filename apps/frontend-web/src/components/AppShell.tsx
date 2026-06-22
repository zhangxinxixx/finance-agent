import { useLayoutEffect, useRef } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AppSidebar } from "./AppSidebar";
import { AppHeader } from "./AppHeader";
import { DataStatusBar } from "./shared/DataStatusBar";

export function AppShell() {
  const location = useLocation();
  const contentRef = useRef<HTMLElement | null>(null);
  const routeContentKey = `${location.pathname}${location.search}`;

  useLayoutEffect(() => {
    const resetScroll = () => {
      contentRef.current?.scrollTo({ top: 0, left: 0 });
      document
        .querySelectorAll<HTMLElement>(".finance-page-shell, .fa-scroll-column")
        .forEach((element) => element.scrollTo({ top: 0, left: 0 }));
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
    <div className="app-frame text-finance-text-primary">
      <div className="app-shell">
        <AppSidebar />

        <div className="app-main">
          <AppHeader />

          <main ref={contentRef} className="app-content">
            <div key={routeContentKey} className="app-content-inner">
              <Outlet />
            </div>
          </main>

          <DataStatusBar />
        </div>
      </div>
    </div>
  );
}
