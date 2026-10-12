import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const routerPath = require.resolve("react-router-dom");
const routerBridge = {
  name: "reading-pages-router-interop",
  enforce: "pre",
  resolveId(id) {
    if (id === "react-router-dom") return "\0reading-pages-router";
  },
  load(id) {
    if (id !== "\0reading-pages-router") return undefined;
    return `import { createRequire } from "node:module"; const pkg = createRequire(${JSON.stringify(import.meta.url)})(${JSON.stringify(routerPath)}); export const Link = pkg.Link; export const MemoryRouter = pkg.MemoryRouter; export const useLocation = pkg.useLocation; export const useParams = pkg.useParams; export const useNavigate = pkg.useNavigate; export const useSearchParams = pkg.useSearchParams;`;
  },
};

const server = await createServer({
  configFile: false,
  ssr: { noExternal: ["react-router-dom"] },
  envDir: resolve("."),
  cacheDir: resolve("node_modules/.vite-reading-pages"),
  optimizeDeps: { noDiscovery: true, include: [] },
  plugins: [react(), routerBridge],
  resolve: { alias: { "@": resolve("src") } },
  server: { middlewareMode: true, hmr: false, ws: false },
  appType: "custom",
});

try {
  const knowledgeFormat = await server.ssrLoadModule("/src/components/knowledge/knowledgeFormat.tsx");
  const knowledgeAdapter = await server.ssrLoadModule("/src/adapters/knowledge.ts");
  const llmFormat = await server.ssrLoadModule("/src/components/llm-audit/llmAuditFormat.ts");
  const settingsFormat = await server.ssrLoadModule("/src/components/settings/settingsFormat.ts");
  const strategyLabels = await server.ssrLoadModule("/src/components/strategy/strategyDisplayLabels.ts");
  const reportMeta = await server.ssrLoadModule("/src/components/reports/reportListMeta.ts");
  const reportsModel = await server.ssrLoadModule("/src/components/reports/reportsPageModel.ts");
  const readingFormat = await server.ssrLoadModule("/src/components/reading/readingFormat.ts");
  assert.equal(knowledgeFormat.knowledgeStatusLabel("mystery"), "未知状态（技术值见详情）");
  assert.equal(knowledgeFormat.knowledgeConfidenceLabel(null), "未提供");
  assert.equal(knowledgeFormat.knowledgeConfidenceLabel(Number.NaN), "未提供");
  assert.equal(knowledgeFormat.knowledgeConfidenceLabel(0), "0/100（非胜率）");
  assert.ok(knowledgeAdapter.KNOWLEDGE_TOPICS.includes("芝商所"), "knowledge topic filter must use the Chinese CME label");
  assert.ok(knowledgeAdapter.KNOWLEDGE_TOPICS.includes("智能体规则"), "knowledge topic filter must use the Chinese Agent rule label");
  assert.ok(!knowledgeAdapter.KNOWLEDGE_TOPICS.includes("CME"), "knowledge topic filter must not expose the raw CME token");
  assert.ok(!knowledgeAdapter.KNOWLEDGE_TOPICS.includes("Agent规则"), "knowledge topic filter must not expose the raw Agent rule token");
  assert.equal(llmFormat.auditStatusLabel("success"), "成功");
  assert.equal(settingsFormat.settingsPreferenceValueLabel("language", "zh-CN"), "简体中文");
  assert.equal(settingsFormat.settingsPreferenceValueLabel("language", "en-US"), "英文界面");
  assert.equal(settingsFormat.settingsPreferenceValueLabel("report_template", "standard"), "标准报告");
  assert.equal(settingsFormat.settingsPreferenceValueLabel("report_template", "institutional_focus"), "机构重点报告");
  assert.equal(settingsFormat.agentNameLabel("SourceHealthAgent"), "数据源健康智能体");
  assert.equal(settingsFormat.agentNameLabel("GoldMacroOverviewAgent"), "黄金宏观总览智能体");
  assert.equal(settingsFormat.agentNameLabel("金十快讯重点筛选 Agent"), "金十快讯重点筛选智能体");
  assert.equal(settingsFormat.agentStatusLabel("registered", "黄金 v3 固定 Agent"), "黄金 v3 固定智能体");
  assert.equal(settingsFormat.agentNameLabel("agent_added_later"), "未解释智能体（技术标识见详情）");
  assert.equal(strategyLabels.strategyEvidenceLabel("fresh_canonical_5m_required"), "等待新的现货黄金 5 分钟 K 线");
  assert.equal(strategyLabels.strategySourceLabel("treasury_rates"), "美国财政部利率");
  assert.equal(strategyLabels.strategyTimestampLabel("quote_cache"), "报价缓存时间");
  assert.equal(reportMeta.reportTypeLabel("unknown_report_type"), "其他报告");
  assert.equal(reportMeta.reportAssetLabel("OG"), "黄金期权（OG）");
  const reportSearchFixture = {
    type: "observation_report",
    trade_date: "2026-10-05",
    title: "",
    source_title: "",
    report_id: "fixture-observation-report",
    run_id: "fixture-observation-run",
    available: true,
    status: "available",
  };
  assert.equal(reportMeta.matchesReportSearch(reportSearchFixture, "黄金"), true, "Chinese asset search must match the visible report asset");
  assert.equal(
    reportsModel.filterReports([reportSearchFixture], "黄金", {
      reportTypes: ["observation_report"],
      asset: null,
      status: null,
      dataSource: null,
      dateRange: "all",
    }).length,
    1,
    "the reports page model must keep the same Chinese search surface as the rail",
  );
  assert.equal(readingFormat.readerContractMonth("NOV26"), "2026年11月");
  assert.equal(readingFormat.readerContractMonth("aggregate"), "汇总范围");
  assert.equal(readingFormat.readerContractMonth("unknown_scope"), "未解释期限（技术值见详情）");
  assert.equal(readingFormat.readingErrorMessage(new Error("GET /api/llm/audits?limit=100 failed"), "读取失败"), "读取失败");

  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ status: "available", items: [], stats: {} }), { status: 200, headers: { "content-type": "application/json" } });
    const emptyKnowledge = await knowledgeAdapter.fetchKnowledgeView({});
    assert.equal(emptyKnowledge.items.length, 0, "a real empty knowledge response must stay empty");
    assert.equal(emptyKnowledge.selectedItem, null, "an empty knowledge response must not select a mock item");
    assert.equal(emptyKnowledge.has_data, false, "an empty knowledge response must be marked as unavailable data");

    globalThis.fetch = async () => new Response("service unavailable", { status: 503 });
    await assert.rejects(() => knowledgeAdapter.fetchKnowledgeView({}), /知识库接口暂时不可用/);

    const topicItem = (topic, tags) => ({
      id: `topic-${topic}`,
      title: "主题筛选模拟条目",
      type: "method",
      typeLabel: "方法论",
      topic,
      status: "待复核",
      summary: "中文模拟条目。",
      thesis: "验证记录尚未提供。",
      updated: "今天",
      createdAt: "今天",
      verifiedAt: "未提供",
      version: "模拟",
      author: "本地模拟",
      confidence: 0,
      citations: 0,
      references: 0,
      dashboards: 0,
      agentReady: false,
      playbookReady: false,
      pinned: false,
      reviewQueued: true,
      tags,
      scenes: [],
      rules: [],
      inputs: [],
      monitorMetrics: [],
      evidence: [],
      downstream: [],
      timeline: [],
      citationFlow: { upstream: [], downstream: [] },
    });
    globalThis.fetch = async () => new Response(JSON.stringify({ status: "available", items: [topicItem("CME", ["CME"])] }), { status: 200, headers: { "content-type": "application/json" } });
    const cmeTopic = await knowledgeAdapter.fetchKnowledgeView({ topic: "芝商所" });
    assert.equal(cmeTopic.items.length, 1, "Chinese CME filter must match the backend CME value");
    globalThis.fetch = async () => new Response(JSON.stringify({ status: "available", items: [topicItem("Agent规则", ["Agent规则"])] }), { status: 200, headers: { "content-type": "application/json" } });
    const agentTopic = await knowledgeAdapter.fetchKnowledgeView({ topic: "智能体规则" });
    assert.equal(agentTopic.items.length, 1, "Chinese Agent-rule filter must match the backend value");
  } finally {
    globalThis.fetch = originalFetch;
  }

  const { KnowledgeListItem } = await server.ssrLoadModule("/src/components/knowledge/KnowledgeListItem.tsx");
  const knowledgeHtml = renderToStaticMarkup(React.createElement(KnowledgeListItem, {
    item: {
      id: "fixture-knowledge",
      title: "测试知识条目",
      type: "method",
      typeLabel: "方法论",
      topic: "黄金",
      status: "mystery",
      agentReady: false,
      citations: 0,
      updated: "今天",
    },
    isActive: true,
    onSelect() {},
  }));
  assert.ok(knowledgeHtml.includes("未知状态（技术值见详情）"));
  assert.ok(!knowledgeHtml.includes(">mystery<"));

  const { OverviewTab } = await server.ssrLoadModule("/src/components/knowledge/KnowledgeDetailTabViews.tsx");
  const overviewHtml = renderToStaticMarkup(React.createElement(OverviewTab, {
    item: {
      id: "fixture-knowledge",
      title: "测试知识条目",
      type: "method",
      typeLabel: "方法论",
      topic: "黄金",
      status: "长期有效",
      summary: "中文摘要。",
      thesis: "中文主张。",
      version: "v1",
      verifiedAt: "今天",
      rules: ["规则一", "规则二", "规则三", "规则四", "规则五"],
      monitorMetrics: [{ label: "黄金", value: "4200", change: "+1", tone: "positive" }, { label: "美元", value: "100", change: "-1", tone: "negative" }, { label: "利率", value: "2%", change: "+1bp", tone: "neutral" }],
      evidence: [{ title: "证据", body: "中文证据。", meta: "今天" }],
      scenes: [],
      inputs: [],
      downstream: [],
      citationFlow: { upstream: [], downstream: [] },
      citations: 0,
      references: 0,
      dashboards: 0,
      confidence: 70,
      createdAt: "今天",
      author: "研究员",
      updated: "今天",
      playbookReady: false,
      pinned: false,
      reviewQueued: false,
      timeline: [],
    },
  }));
  assert.ok(overviewHtml.includes("另有 1 条"));
  assert.ok(overviewHtml.includes("利率 +1bp"));

  const { LLMAuditDetailPanel } = await server.ssrLoadModule("/src/components/llm-audit/LLMAuditDetailPanel.tsx");
  const auditHtml = renderToStaticMarkup(React.createElement(LLMAuditDetailPanel, {
    audit: {
      audit_id: "fixture-audit",
      call_id: "fixture-call",
      status: "success",
      caller: "synthesis_agent",
      provider_resolved: "fixture-provider",
      model_resolved: "fixture-model",
      reasoning_effort_resolved: "medium",
      request_config: {},
      request_sha256: "fixture-request-sha",
      prompt_message_count: 1,
      prompt_char_count: 1,
      response_char_count: 1,
      usage: {},
      attempt_count: 1,
      request_messages: [],
      response_text: "中文输出。",
      attempts: [],
      context: {},
      source_refs: [],
      secrets_redacted: true,
      sanitization_performed: true,
      content_included: true,
      immutable: true,
      run_id: null,
      report_id: null,
      created_at: "2026-10-05T09:00:00Z",
    },
  }));
  assert.ok(auditHtml.includes("模型调用审计"));
  assert.ok(auditHtml.includes("成功"));
  assert.ok(auditHtml.includes("提示词校验摘要已记录"));
  assert.ok(!auditHtml.includes("LLM 调用审计"));

  const { ReportAgentOutputCard } = await server.ssrLoadModule("/src/components/reports/ReportAgentOutputCard.tsx");
  const reportHtml = renderToStaticMarkup(React.createElement(ReportAgentOutputCard, {
    item: {
      agent_output_id: "fixture-output",
      display_name: "综合分析",
      status: "available",
      summary: "English conclusion requiring human review.",
      summary_zh: null,
      key_findings: ["finding one", "finding two", "finding three", "finding four"],
      risk_points: ["risk one", "risk two", "risk three", "risk four"],
      invalid_conditions: ["invalid one", "invalid two", "invalid three", "invalid four", "invalid five"],
      watchlist: ["watch one", "watch two", "watch three", "watch four", "watch five"],
      source_refs: [],
      artifact_refs: [],
      claim_count: 4,
      confidence: 0.5,
      bias: "neutral",
      generated_by: "llm",
      fact_review_status: "not_reviewed",
      created_at: "2026-10-05T09:00:00Z",
      role: "synthesis_agent",
      agent_name: "synthesis_agent",
      llm_audit: null,
      prompt_version: null,
    },
  }));
  assert.ok(reportHtml.includes("中文整理缺口"));
  assert.ok(reportHtml.includes("risk four"));
  assert.ok(reportHtml.includes("invalid five"));
  assert.ok(reportHtml.includes("watch five"));

  const targetSources = [
    "/src/pages/LLMAuditPage.tsx",
    "/src/pages/SettingsAuditPage.tsx",
    "/src/components/settings/SettingsAuditSummary.tsx",
    "/src/components/reports/CMEVisualReportViewer.tsx",
    "/src/components/reports/Jin10DailyVisualViewer.tsx",
    "/src/components/strategy/StrategyTracePanel.tsx",
    "/src/components/strategy/LiveStrategyWorkspace.tsx",
    "/src/components/strategy/LiveStrategyScenarios.tsx",
    "/src/components/strategy/ShadowEvaluationPanel.tsx",
    "/src/components/strategy/ShadowEvaluationHistoryPanel.tsx",
  ];
  for (const path of targetSources) {
    const loaded = await server.ssrLoadModule(path);
    assert.ok(loaded, `${path} should remain loadable`);
  }
  console.log("Reading pages Chinese/trace behavior OK: known status labels, full risk arrays, explicit English-analysis gap, collapsed technical identity.");
} finally {
  await server.close();
}
