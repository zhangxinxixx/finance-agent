import { Outlet } from "react-router-dom";
import { AppSidebar } from "./AppSidebar";
import { AppHeader } from "./AppHeader";
import { DataStatusBar } from "./shared/DataStatusBar";

export function AppShell() {
  return (
    <div className="app-frame text-finance-text-primary">
      <div className="app-shell">
        <AppSidebar />

        <div className="app-main">
          <AppHeader />

          <main className="app-content">
            <div className="app-content-inner">
              <Outlet />
            </div>
          </main>

          <DataStatusBar />
        </div>
      </div>
    </div>
  );
}
