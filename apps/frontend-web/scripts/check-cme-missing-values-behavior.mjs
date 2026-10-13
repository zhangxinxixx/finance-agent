import assert from 'node:assert/strict';
import { loader, React, renderToStaticMarkup, cases } from './strategy-test-harness.mjs';
import { cmeFixture } from './cme-options-test-fixtures.mjs';
async function model(raw = cmeFixture()) {
  return loader({ '@/adapters/apiClient': { fetchJson: async () => structuredClone(raw) } })('@/adapters/cmeOptions').fetchCMEOptionsData();
}
const load = loader();
const fmt = load('@/components/cme-options/cmeOptionsFormat');
const parts = load('@/components/cme-options/OptionsWallTableParts');
const gamma = load('@/components/cme-options/CMEOptionsGammaPanels');
const ladder = load('@/components/cme-options/PriceLadderLevels');
const markup = (component, props) => renderToStaticMarkup(React.createElement(component, props));
await cases([
  ['original-missing-oi-score', async () => {
    const m = await model();
    assert.equal(m.wall_scores[0].oi, null);
    assert.equal(m.wall_scores[0].wall_score, null);
    const html = markup(parts.OptionsWallTableRows, { rows: m.wall_scores });
    assert.match(html, /4100|4,100/); assert.match(html, /—/); assert.match(html, />0\.00</); assert.match(html, />0</);
  }],
  ['invalid-values-and-signed-values', async () => {
    for (const value of [undefined, null, NaN, Infinity, -Infinity, '', ' ', '0', '25', true, false, {}, []]) {
      const raw = cmeFixture(); raw.wall_scores[0].oi = value; raw.wall_scores[0].wall_score = value; raw.wall_scores[0].strike = value;
      raw.support_resistance.resistance[0] = { strike: value, wall_score: value, distance_pct: value };
      raw.gex.by_expiry.OCT26.gex_top[0] = { strike: value, call_gex: value, put_gex: value, net_gex: value, total_gex: value };
      raw.gex.by_expiry.OCT26.summary = { net_gex: value, call_gex: value, put_gex: value, total_gex: value, atm_iv: value, time_to_expiry: value };
      raw.gex.by_expiry.OCT26.iv_skew = { atm_iv: value, skew_25d: value };
      const m = await model(raw);
      for (const row of [m.wall_scores[0], m.support_resistance.resistance[0], m.gex.by_expiry.OCT26.gex_top[0]]) {
        for (const key of Object.keys(row).filter(k => /strike|gex|wall_score|distance_pct|^oi$/.test(k))) assert.equal(row[key], null, key);
      }
      assert.equal(fmt.formatNumber(value), '—'); assert.equal(fmt.formatCompactNumber(value), '—');
      for (const actual of Object.values(m.gex.by_expiry.OCT26.summary).filter(v => typeof v !== 'string')) assert.equal(actual, null);
      assert.equal(m.gex.by_expiry.OCT26.iv_skew.atm_iv, null);
      assert.doesNotMatch(markup(parts.OptionsWallTableRows, { rows: m.wall_scores }), /NaN|Infinity|undefined/);
    }
    const m = await model(cmeFixture(true));
    assert.equal(m.wall_scores[0].delta_oi, -12); assert.equal(m.gex.netgex_aggregate.net_gex, -150);
    assert.match(markup(parts.OptionsWallTableRows, { rows: m.wall_scores }), />-12</);
    assert.equal(fmt.formatNumber(-1.25, 2), '-1.25');
    const overview = load('@/components/cme-options/CMEOptionsOverviewGrid').CMEOptionsOverviewGrid;
    const html = markup(overview, { snapshot: m, wallScores: m.wall_scores, selectedExpiry: 'OCT26' });
    assert.doesNotMatch(html, /NaN|undefined|Infinity/);
  }],
  ['ranking-keeps-zero-excludes-missing', async () => {
    const m = await model();
    for (const direction of ['asc', 'desc']) assert.equal(parts.sortWallRows(m.wall_scores, 'wall_score', direction).at(-1).strike, 4100);
    assert.equal(fmt.topWall(m.wall_scores, 'CALL').strike, 4050);
    assert.equal(fmt.resolveDirectionalWall(m, m.wall_scores, 'CALL').strike, 4050);
    const raw = cmeFixture(); raw.wall_scores = []; raw.support_resistance = { support: [], resistance: [] };
    raw.gex.by_expiry.OCT26.gex_top = [{ strike: 4050, call_gex: 0, put_gex: 0, total_gex: 0, net_gex: 0 }];
    assert.equal(fmt.resolveDirectionalWall(await model(raw), [], 'CALL').gexValue, 0);
  }],
  ['partial-and-all-missing-coverage', async () => {
    const m = await model();
    const summary = markup(gamma.ChangeTable, { snapshot: m });
    assert.match(summary, /持仓.*不可比|不可比.*持仓/); assert.doesNotMatch(summary, /看涨持仓<\/span><span[^>]*>0</);
    assert.equal(ladder.buildPriceLadderLevels(m.support_resistance, null)[0].note.includes('评分 —'), true);
    const raw = cmeFixture(); raw.wall_scores = [{}]; raw.support_resistance.resistance = [{}]; raw.support_resistance.support = [{}];
    raw.gex.by_expiry.OCT26.gex_top = [{}, {}];
    const empty = await model(raw);
    assert.equal(empty.wall_scores.length, 1); assert.equal(empty.gex.by_expiry.OCT26.gex_top.length, 2);
    assert.equal(fmt.topWall(empty.wall_scores, 'CALL'), null);
    assert.equal(ladder.buildPriceLadderLevels(empty.support_resistance, null).length, 0);
    const html = markup(gamma.PriceLadder, { supportResistance: empty.support_resistance, currentPrice: null });
    assert.match(html, /未提供|未绘制/);
    assert.doesNotMatch(markup(gamma.GEXBreakdown, { snapshot: empty, selectedExpiry: 'OCT26' }), /NaN|undefined|Infinity/);
    const overview = load('@/components/cme-options/CMEOptionsOverviewGrid').CMEOptionsOverviewGrid;
    const overviewHtml = markup(overview, { snapshot: empty, wallScores: empty.wall_scores, selectedExpiry: 'OCT26' });
    assert.match(overviewHtml, /部分字段未提供/); assert.doesNotMatch(overviewHtml, /NaN|undefined|Infinity/);
  }],
  ['complete-professional-path-and-switches', async () => {
    const complete = await model(cmeFixture(true));
    assert.equal(fmt.resolveDirectionalWall(complete, complete.wall_scores, 'CALL').strike, 4100);
    assert.match(markup(gamma.ChangeTable, { snapshot: complete }), /120/);
    assert.match(markup(gamma.GEXBreakdown, { snapshot: complete, selectedExpiry: 'DEC26' }), /500/);
    assert.match(markup(gamma.GEXBreakdown, { snapshot: complete, selectedExpiry: 'MISSING' }), /未回退/);
    for (const completeFlag of [false, true, false]) {
      const m = await model(cmeFixture(completeFlag));
      assert.equal(m.wall_scores[0].oi, completeFlag ? 120 : null);
      assert.equal(m.data_source.status, completeFlag ? 'FINAL' : 'PRELIM');
      assert.equal(m.snapshot_id, 'synthetic-2026-10-13');
    }
  }],
]);
