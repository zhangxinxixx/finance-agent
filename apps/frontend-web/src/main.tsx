import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import "./index.css";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const DashboardAnalysisPage = lazy(() => import("./pages/DashboardAnalysisPage").then((module) => ({ default: module.DashboardAnalysisPage })));
const GoldMainlinesPage = lazy(() => import("./pages/GoldMainlinesPage").then((module) => ({ default: module.GoldMainlinesPage })));
const RatesDollarPage = lazy(() => import("./pages/RatesDollarPage").then((module) => ({ default: module.RatesDollarPage })));
const OilGeopoliticsPage = lazy(() => import("./pages/OilGeopoliticsPage").then((module) => ({ default: module.OilGeopoliticsPage })));
const DataIngestionPage = lazy(() => import("./pages/DataIngestionPage").then((module) => ({ default: module.DataIngestionPage })));
const MarketMonitorPage = lazy(() => import("./pages/MarketMonitorPage").then((module) => ({ default: module.MarketMonitorPage })));
const CMEOptionsPage = lazy(() => import("./pages/CMEOptionsPage").then((module) => ({ default: module.CMEOptionsPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })));
const ReportDetailPage = lazy(() => import("./pages/ReportDetailPage").then((module) => ({ default: module.ReportDetailPage })));
const EventFlowPage = lazy(() => import("./pages/EventFlowPage").then((module) => ({ default: module.EventFlowPage })));
const EventFlowDetailPage = lazy(() => import("./pages/EventFlowDetailPage").then((module) => ({ default: module.EventFlowDetailPage })));
const FeishuMonitorPage = lazy(() => import("./pages/FeishuMonitorPage").then((module) => ({ default: module.FeishuMonitorPage })));
const KnowledgeBasePage = lazy(() => import("./pages/KnowledgeBasePage").then((module) => ({ default: module.KnowledgeBasePage })));
const SchedulerCenterPage = lazy(() => import("./pages/SchedulerCenterPage").then((module) => ({ default: module.SchedulerCenterPage })));
const TaskScheduleListPage = lazy(() => import("./pages/TaskScheduleListPage").then((module) => ({ default: module.TaskScheduleListPage })));
const PipelineDagPage = lazy(() => import("./pages/PipelineDagPage").then((module) => ({ default: module.PipelineDagPage })));
const AgentTasksPage = lazy(() => import("./pages/AgentTasksPage").then((module) => ({ default: module.AgentTasksPage })));
const AgentTaskDetailPage = lazy(() => import("./pages/AgentTaskDetailPage").then((module) => ({ default: module.AgentTaskDetailPage })));
const ReviewCenterPage = lazy(() => import("./pages/ReviewCenterPage").then((module) => ({ default: module.ReviewCenterPage })));
const StrategyPage = lazy(() => import("./pages/StrategyPage").then((module) => ({ default: module.StrategyPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const SettingsAuditPage = lazy(() => import("./pages/SettingsAuditPage").then((module) => ({ default: module.SettingsAuditPage })));

function RouteFallback() {
  return (
    <div className="finance-page-shell">
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <div className="h-3 w-36 animate-pulse rounded bg-[var(--bg-hover)]" />
        <div className="mt-3 grid gap-2">
          <div className="h-20 animate-pulse rounded-[var(--radius-md)] bg-[var(--bg-card-inner)]" />
          <div className="h-20 animate-pulse rounded-[var(--radius-md)] bg-[var(--bg-card-inner)]" />
        </div>
      </div>
    </div>
  );
}

function lazyPage(page: React.ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{page}</Suspense>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={lazyPage(<DashboardPage />)} />
          <Route path="/dashboard/analysis" element={lazyPage(<DashboardAnalysisPage />)} />
          <Route path="/gold-mainlines" element={lazyPage(<GoldMainlinesPage />)} />
          <Route path="/rates-dollar" element={lazyPage(<RatesDollarPage />)} />
          <Route path="/oil-geopolitics" element={lazyPage(<OilGeopoliticsPage />)} />
          <Route path="/data-ingestion" element={lazyPage(<DataIngestionPage />)} />
          <Route path="/data-sources/:sourceId" element={lazyPage(<DataIngestionPage />)} />
          <Route path="/market-monitor" element={lazyPage(<MarketMonitorPage />)} />
          <Route path="/cme-options" element={lazyPage(<CMEOptionsPage />)} />
          <Route path="/reports" element={lazyPage(<ReportsPage />)} />
          <Route path="/reports/:reportId" element={lazyPage(<ReportDetailPage />)} />
          <Route path="/event-flow" element={lazyPage(<EventFlowPage />)} />
          <Route path="/event-flow/:eventId" element={lazyPage(<EventFlowDetailPage />)} />
          <Route path="/feishu-monitor" element={lazyPage(<FeishuMonitorPage />)} />
          <Route path="/knowledge" element={lazyPage(<KnowledgeBasePage />)} />
          <Route path="/knowledge-base" element={lazyPage(<KnowledgeBasePage />)} />
          <Route path="/knowledge/:knowledgeId" element={lazyPage(<KnowledgeBasePage />)} />
          <Route path="/agent-tasks" element={<Navigate to="/scheduler" replace />} />
          <Route path="/agent-tasks/:runId" element={lazyPage(<AgentTaskDetailPage />)} />
          <Route path="/scheduler" element={lazyPage(<PipelineDagPage />)} />
          <Route path="/scheduler/grid" element={lazyPage(<SchedulerCenterPage />)} />
          <Route path="/scheduler/tasks" element={lazyPage(<TaskScheduleListPage />)} />
          <Route path="/review-center" element={lazyPage(<ReviewCenterPage />)} />
          <Route path="/strategy" element={lazyPage(<StrategyPage />)} />
          <Route path="/settings" element={lazyPage(<SettingsPage />)} />
          <Route path="/settings/audit" element={lazyPage(<SettingsAuditPage />)} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
