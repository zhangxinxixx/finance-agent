// Explicit synthetic fixtures; never read production artifacts or market data.
export function reportFixture(id = 'unknown', overrides = {}) {
  return { type: 'final_report', family: 'final_report_markdown', title: `隔离合成报告 ${id}`, report_id: id,
    run_id: `run-${id}`, snapshot_id: `snapshot-${id}`, trade_date: '2026-10-13', generated_at: '2026-10-13T04:00:00Z',
    available: true, format: 'markdown', data_status: 'available', ...overrides };
}
export function researchFixture(item, status = 'active') {
  return { schema_version: 'research_identity.v1', report_id: item.report_id, run_id: item.run_id, snapshot_id: item.snapshot_id,
    trade_date: item.trade_date, research_version: `version-${item.report_id}`, data_as_of: '2026-10-13T03:30:00Z', generated_at: item.generated_at,
    key_level_validity: { status, data_as_of: '2026-10-13T03:30:00Z', valid_until: '2026-10-14T00:00:00Z', reason_codes: [] } };
}
export function detailFixture(item) {
  return { ...item, lifecycle_status: item.lifecycle_status, source_refs: [], artifact_refs: [], warnings: [],
    artifacts: [{ artifact_id: `artifact-${item.report_id}`, artifact_type: 'analysis_md', report_id: item.report_id }], input_snapshot_ids: [item.snapshot_id], review_items: [],
    report_identity: item.report_identity ?? { authority: item.authority, output_mode: item.output_mode, publish_allowed: item.publish_allowed, publication_status: item.publication_status },
    research_identity: item.research_identity ?? null };
}
export function reportArtifact(item) {
  return { report_id: item.report_id, artifact_type: 'analysis_md', content_type: 'text/markdown',
    content: `# 隔离合成正文 ${item.report_id}\n\n本报告仅作离线验收，不代表真实分析或交易依据。\n\n## 原始研究\n\n只读正文标记 ${item.report_id}。`, path: `synthetic/${item.report_id}.md` };
}
