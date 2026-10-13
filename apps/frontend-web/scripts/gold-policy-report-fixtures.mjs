import { reportFixture, researchFixture, detailFixture, reportArtifact } from './report-qualification-fixtures.mjs';

// The type/family and IDs follow the registry/index contract; all content is synthetic.
export function goldPolicyFixture(version = 'formal', overrides = {}) {
  const item = reportFixture(`gold_policy_daily:synthetic-127-${version}`, {
    type: 'gold_policy_daily', family: 'gold_policy_daily_report',
    title: `隔离黄金日结 ${version}`, publish_allowed: true,
    lifecycle_status: 'published', review_status: 'approved', publication_status: 'accepted',
    ...overrides,
  });
  if (!Object.hasOwn(overrides, 'research_identity')) {
    item.research_identity = researchFixture(item, version === 'history' ? 'historical' : 'active');
  }
  return item;
}

export function goldPolicyMatrix() {
  return [
    goldPolicyFixture('formal'),
    goldPolicyFixture('revision', { run_id: 'run-revision', generated_at: '2026-10-13T05:00:00Z' }),
    goldPolicyFixture('partial', { data_status: 'partial', lifecycle_status: 'needs_review', review_status: 'pending', publish_allowed: false, publication_status: 'degraded' }),
    goldPolicyFixture('blocked', { data_status: 'unavailable', lifecycle_status: 'needs_review', review_status: 'blocked', publish_allowed: false }),
    goldPolicyFixture('history', { publish_allowed: false, authority: 'historical_only', output_mode: 'historical' }),
    goldPolicyFixture('observe', { publish_allowed: false, lifecycle_status: 'generated', authority: 'observation_only', output_mode: 'observe', publication_status: 'observe' }),
    goldPolicyFixture('unknown', { publish_allowed: null, lifecycle_status: null, review_status: null, publication_status: null, research_identity: null }),
  ];
}

export { detailFixture, reportArtifact };
