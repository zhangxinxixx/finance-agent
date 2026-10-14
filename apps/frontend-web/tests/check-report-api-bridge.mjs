// Explicit pytest companion. Only transport is replaced; all DTOs are captured HTTP bodies.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [consumerArg, evidenceArg] = process.argv.slice(2);
assert.ok(consumerArg && evidenceArg, 'Usage: node check-report-api-bridge.mjs CONSUMER_ROOT EVIDENCE_DIR');
const consumer = resolve(consumerArg), evidence = resolve(evidenceArg);
const frontend = join(consumer, 'apps/frontend-web');
const { loader, React, renderToStaticMarkup } = await import(pathToFileURL(join(frontend, 'scripts/strategy-test-harness.mjs')));
const raw = readFileSync(join(evidence, 'responses.json'));
const samples = JSON.parse(raw);
const plain = value => JSON.parse(JSON.stringify(value)); // VM objects have a different prototype.
const filters = { reportTypes: [], asset: null, status: null, dataSource: null, dateRange: null };
const observations = [], requests = [];
const assertions = new Set();
const sources = [
  'scripts/strategy-test-harness.mjs', 'src/adapters/reports.ts',
  'src/components/reports/reportListMeta.ts', 'src/components/reports/reportsPageModel.ts',
  'src/components/gold-workspace/goldReadingNavigation.ts', 'src/components/gold-workspace/GoldFrozenReport.tsx',
  'src/components/reports/reportDetailMeta.ts',
  'src/adapters/researchIdentity.ts', 'src/adapters/researchTradePlan.ts',
  'src/adapters/resultIdentity.ts', 'src/adapters/inFlightRequest.ts',
];

function consumerFor(sample, failSource = false) {
  class ApiError extends Error {
    constructor(message, options = {}) { super(message); Object.assign(this, options); }
  }
  return loader({ '@/adapters/apiClient': {
    ApiError,
    fetchJson: async (url, options = {}) => {
      assert.equal(options.method ?? 'GET', 'GET', 'Only GET transport is permitted');
      const captured = sample.responses[url];
      assert.ok(captured, `Uncaptured request forbidden: ${url}`);
      assert.equal(captured.status, 200);
      requests.push({ case: sample.case, url, method: 'GET', controlled_503: failSource && url.endsWith('/source') });
      if (failSource && url.endsWith('/source')) throw new ApiError('Controlled attachment failure', { status: 503, url });
      return structuredClone(captured.body);
    },
  }});
}

for (const sample of samples) {
  const load = consumerFor(sample);
  const adapter = load('@/adapters/reports');
  const meta = load('@/components/reports/reportListMeta');
  const model = load('@/components/reports/reportsPageModel');
  const index = await adapter.fetchReportsIndex();
  const dates = await adapter.fetchReportsDates();
  const reports = model.dedupeSupportedReports(index.reports);
  const selected = reports.find(row => row.report_id === sample.report_id);
  assert.ok(selected);
  assert.equal(meta.canOpenReport(selected), true);
  assert.equal(meta.getReportDetailId(selected), sample.report_id);
  assert.ok(model.filterReports(reports, 'gold_policy_daily', { ...filters, asset: 'XAUUSD', reportTypes: ['gold_policy_daily'] })
    .some(row => row.report_id === sample.report_id));
  assert.equal(dates.total_dates, 1);
  assert.deepEqual(plain(dates.dates[0].modules), ['gold_policy_daily']);
  assert.equal(dates.dates[0].has_final_report, false);
  assert.equal(dates.dates[0].has_strategy_card, false);
  assert.equal(dates.dates[0].trade_date, selected.trade_date);
  assert.equal(dates.dates[0].latest_run_id, selected.run_id);
  assertions.add('registry_only_dates_are_not_final_reports');
  const status = meta.getReportListStatus(selected);
  assert.equal(status.referenceOnly, true);
  if (['accepted', 'matching'].includes(sample.case)) {
    assert.equal(selected.lifecycle_status, 'snapshot_bound');
    assert.equal(selected.publish_allowed, true);
    assert.equal(selected.review_status, null);
    assert.match(status.description, /获准发布/);
    assert.match(status.description, sample.case === 'matching' ? /发布记录未知/ : /尚未发布/);
    assert.notEqual(status.key, 'published');
    assertions.add('accepted_snapshot_bound_does_not_imply_published_or_approved');
  } else if (sample.case === 'published') {
    assert.equal(status.key, 'published');
    assert.equal(selected.review_status, 'approved');
    assert.equal(selected.publish_allowed, true);
  } else if (['observe', 'degraded', 'versions'].includes(sample.case)) {
    assert.equal(status.key, 'review');
    assert.equal(selected.publish_allowed, false);
  } else if (sample.case === 'archived') {
    assert.equal(status.key, 'archived');
    assert.equal(selected.publish_allowed, false);
  } else {
    assert.equal(status.key, 'unknown');
    assert.equal(selected.publish_allowed, null);
    assert.match(status.description, /许可未知/);
  }
  const published = model.filterReports(reports, '', { ...filters, status: 'published' });
  assert.equal(published.some(row => row.report_id === sample.report_id), sample.case === 'published');
  assert.ok(published.every(row => row.lifecycle_status === 'published'));
  assertions.add('published_filter_requires_persisted_publication');
  if (sample.case === 'versions') {
    assert.equal(reports.length, 2);
    assert.equal(reports[0].report_id, sample.report_id);
    assert.equal(reports[0].trade_date, reports[1].trade_date);
    assert.notEqual(reports[0].run_id, reports[1].run_id);
    assert.notEqual(reports[0].report_identity.canonical_receipt_id, reports[1].report_identity.canonical_receipt_id);
    assert.equal(reports[1].publish_allowed, true);
    assertions.add('same_day_distinct_registered_runs_remain_distinct');
  }
  const detail = await adapter.fetchReportDetailView(sample.report_id);
  const capturedDetail = sample.responses[`/api/reports/${sample.report_id}`].body;
  for (const key of ['report_id', 'run_id', 'snapshot_id', 'trade_date', 'publication_status', 'output_mode', 'publish_allowed', 'lifecycle_status']) {
    assert.equal(detail.meta[key] ?? null, selected[key] ?? null, `${sample.case}: selected ${key}`);
    assert.equal(detail.meta[key] ?? null, capturedDetail[key] ?? null, `${sample.case}: API ${key}`);
  }
  // Registry index has no persisted review fact; detail can say not_required.
  // Preserve both API meanings rather than filling an approval into either DTO.
  assert.equal(detail.meta.review_status ?? null, capturedDetail.review_status ?? null);
  if (['accepted', 'matching'].includes(sample.case)) assert.notEqual(detail.meta.review_status, 'approved');
  assert.deepEqual(plain(detail.meta.report_identity), plain(selected.report_identity));
  if (sample.case !== 'missing') {
    assert.equal(detail.meta.report_identity.canonical_receipt_id, sample.persisted_receipt);
  }
  assert.equal(detail.meta.generated_at, capturedDetail.generated_at);
  for (const source of detail.source_refs) {
    const original = capturedDetail.source_refs.find(row =>
      (row.source_name || row.source_id) === source.source_ref && row.file_path === source.artifact_path);
    assert.ok(original);
    assert.equal(source.asOf, original.captured_at);
    assert.equal(source.generated_at, original.captured_at);
    assert.equal(source.trade_date, original.data_date);
  }
  for (const part of ['analysis', 'source', 'visual', 'evidence']) {
    const url = `/api/reports/${sample.report_id}/${part}`;
    assert.equal(sample.responses[url].body.report_id, sample.report_id);
    // Some registered bundles contain no visual attachment. The adapter must
    // decide reads from actual artifact metadata, never invented availability.
    if (detail.tabs[part]) {
      assert.equal(detail.tabs[part].source_endpoint, url);
      assert.equal(detail.tabs[part].generated_at ?? null, sample.responses[url].body.generated_at ?? null);
    }
  }
  assert.ok(detail.tabs.analysis.available && detail.tabs.analysis.content.length > 1000);
  assertions.add('body_and_eligibility_share_exact_selected_report_and_receipt');
  assertions.add('report_and_attachment_source_clocks_retained');
  if (sample.case === 'matching') {
    assert.ok(selected.research_identity);
    assert.deepEqual(plain(selected.research_identity), plain(detail.research_identity));
    for (const key of ['report_id', 'run_id', 'snapshot_id', 'trade_date']) {
      assert.equal(selected.research_identity[key], selected[key]);
    }
    assert.equal(selected.research_identity.data_as_of, '2025-01-21T21:00:00+00:00');
    assert.equal(selected.research_identity.key_level_validity.status, 'historical');
    assertions.add('matching_analysis_snapshot_identity_is_exact_and_historical');
  } else {
    assert.equal(selected.research_identity ?? null, null);
    assert.equal(detail.research_identity?.data_as_of ?? null, null);
    assertions.add('absent_analysis_snapshot_does_not_invent_research_identity');
  }
  const navigation = load('@/components/gold-workspace/goldReadingNavigation');
  assert.equal(navigation.readGoldReadingContext(detail), null, 'Report DTO cannot impersonate workspace observations');
  // Exercise only the shared research field comparison with the unchanged
  // selected API DTO. This is not a fabricated gold_workspace.v1 response.
  const comparisonContext = { workspace: { research: capturedDetail } };
  assert.match(navigation.compareGoldReportResearch(comparisonContext, detail.meta), /字段一致/);
  assert.match(navigation.compareGoldReportResearch(comparisonContext, detail.meta), /仍以报告详情为准/);
  assert.equal(navigation.compareGoldStrategyResearch(comparisonContext).label, '无法核验');
  assert.equal(navigation.goldStrategyNavigation(comparisonContext).strategySource.sourceResultIdentity, null);
  if (sample.case === 'versions') {
    assert.match(navigation.compareGoldReportResearch(comparisonContext, reports[1]), /不同/);
  }
  assertions.add('research_navigation_field_match_never_grants_current_strategy_authority');
  const frozen = load('@/components/gold-workspace/GoldFrozenReport');
  assert.equal(frozen.readFrozenGoldReport(detail), detail);
  const before = JSON.stringify(detail);
  const { MemoryRouter } = load('react-router-dom');
  const markup = renderToStaticMarkup(React.createElement(MemoryRouter, null,
    React.createElement(frozen.GoldFrozenReport, { report: detail, onLatest() { throw new Error('Unexpected refresh'); } })));
  assert.match(markup, /历史／冻结报告/);
  assert.match(markup, /不是当前执行许可/);
  assert.ok(markup.includes(`/reports/${encodeURIComponent(sample.report_id)}`));
  assert.equal(JSON.stringify(detail), before);
  assertions.add('frozen_gold_report_reads_actual_dto_without_refresh_or_mutation');
  if (sample.case === 'accepted') {
    const failedLoad = consumerFor(sample, true);
    const partial = await failedLoad('@/adapters/reports').fetchReportDetailView(sample.report_id);
    assert.ok(requests.some(request => request.controlled_503));
    assert.ok(partial.warnings.some(warning => warning.code === 'report-artifact-read-failed' && warning.field === 'source'));
    assert.equal(partial.tabs.source, undefined);
    assert.equal(partial.tabs.analysis.content, detail.tabs.analysis.content);
    assert.deepEqual(plain(partial.meta.report_identity), plain(detail.meta.report_identity));
    assert.equal(partial.meta.publish_allowed, detail.meta.publish_allowed);
    assertions.add('attachment_503_preserves_body_identity_and_eligibility');
  }
  observations.push({ case: sample.case, report_id: sample.report_id, status_key: status.key,
    publish_allowed: selected.publish_allowed, lifecycle_status: selected.lifecycle_status,
    body_chars: detail.tabs.analysis.content.length, available_tabs: plain(detail.available_tabs) });
}

const receipt = {
  passed: true,
  producer: JSON.parse(readFileSync(join(evidence, 'producer.json'), 'utf8')),
  consumer: {
    head: JSON.parse(readFileSync(join(evidence, 'consumer.json'), 'utf8')).head,
    source_sha256: Object.fromEntries(sources.map(name => [name, createHash('sha256').update(readFileSync(join(frontend, name))).digest('hex')])),
  },
  captured_response_sha256: createHash('sha256').update(raw).digest('hex'),
  captured_response_count: samples.reduce((count, sample) => count + Object.keys(sample.responses).length, 0),
  assertions: [...assertions], cases: observations, transport_requests: requests,
  real_network_calls: 0, api_writes: 0, browser_test: false,
  attribution: { producer: '#130 registry fixture and TestClient contract', consumer: '#129 report consumers; #126 frozen reading; existing #123 attachment isolation retained' },
};
writeFileSync(join(evidence, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({ passed: true, cases: observations.length, captured_response_count: receipt.captured_response_count,
  assertions: receipt.assertions, real_network_calls: 0, api_writes: 0 }));
