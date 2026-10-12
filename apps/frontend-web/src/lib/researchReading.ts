/** Presentation only: never computes a direction, qualification, probability or market claim. */
export const researchLabels: Record<string, string> = {
  rules: '研究规则', risk_note: '风险与限制', trade_implication: '研究含义', decision_summary: '当前判断', riskPoints: '风险与限制', invalidConditions: '失效条件', confidence: '判断把握程度（非胜率）',
  scenario_summary: '当前判断', risk_points: '风险与限制', invalid_conditions: '失效条件',
  summary: '当前判断', executive_summary: '当前判断', one_line_conclusion: '当前判断', conclusion: '当前判断', thesis: '当前判断', judgment: '当前判断',
  rationale: '关键依据', evidence: '关键依据', key_findings: '关键依据', key_points: '关键依据', analysis: '研究分析', observations: '关键变化', changes: '关键变化',
  why_it_matters: '为什么重要', impact: '为什么重要', implications: '为什么重要', next_watch: '接下来观察', watchlist: '接下来观察', monitoring: '接下来观察',
  trigger_conditions: '触发条件', confirmation_conditions: '确认条件', invalidation: '失效条件', invalidation_conditions: '失效条件', risks: '风险与限制', risk: '风险与限制', warnings: '风险与限制', limitations: '风险与限制', missing_data: '数据缺口',
  current_judgment: '当前判断', supporting_evidence: '关键依据', what_to_watch: '接下来观察', next_steps: '接下来观察', data_gaps: '数据缺口', risk_factors: '风险与限制', uncertainty: '不确定性', invalidation_level: '失效价位', entry_zone: '入场区间', targets: '目标区间', direction: '研究方向',
  scenarios: '研究情景', title: '主题', heading: '主题', text: '说明', content: '研究正文', body: '研究正文', message: '说明', description: '说明', reason: '依据', status: '状态', as_of: '数据时间', trade_date: '数据日期', updated_at: '更新时间',
};
const translations: Record<string, string> = {
  bullish: '偏多', bearish: '偏空', neutral: '中性', long: '多头', short: '空头', no_trade: '观望，不交易',
  accepted: '已通过', verified: '已核验', pending: '待确认', available: '可用', invalid: '无效', blocked: '未通过', missing: '缺失', failed: '失败', provisional: '暂定，需复核', FINAL: '最终公告',
  SUSPENDED_DATA: '数据不足，暂不可参考', NO_TRADE: '观望，不交易', needs_review: '尚需复核', unverified: '尚未核验', unavailable: '暂不可用', degraded: '数据不完整', partial: '部分可用', stale: '数据已过期', PRELIM: '初步数据，尚非最终公告',
  canonical_candle_stale: 'XAUUSD 5 分钟K线已过期', quote_cache_stale: '报价已过期', baseline_options_trade_date_mismatch: '期权与策略日期不一致', option_key_levels_coordinate_mismatch: 'GC期货结构位未验证基差，不能直接与XAUUSD现价比较', fresh_canonical_5m_required: '等待新的XAUUSD 5分钟K线', confirmed_price_event_required: '等待关键位价格事件确认', blocked_data: '数据条件未通过，暂不可参考', gold_direction_authority_unavailable: '黄金日结方向尚未核验', gold_daily_close_prebootstrap_hold: '尚无可用黄金日结基准', gold_direction_authority_invalid: '黄金日结方向核验未通过', gold_strategy_status_not_directional: '黄金日结未给出可用方向',
};
const machine = /(?:(?:^|\s)\/(?:api|home|tmp|mnt|var)\/\S+|\b(?:schema(?:_version)?|source_refs?|snapshot_id|run_id|receipt_id|result_id|state_id|strategy_id|hash|sha256|endpoint|publish_allowed|QualityGate|prior agent|fallback|provenance|agent_output|input_snapshot_ids)\b|\b(?:raw|parsed)\/|storage\/|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9-]{20,}|\b[a-f0-9]{32,}\b)/i;
const technicalHeading = /^(?:来源(?:链|引用|记录|清单|信息|与溯源)?|数据来源|溯源|技术(?:详情|信息)?|审计(?:记录|链)?|生成记录|调用记录|输入输出|架构|证据包|sources?|source[ _-]?(?:refs?|trace)|(?:data[ _-])?provenance|metadata|raw|parsed|appendix|附录)(?:\s|[:：]|$)/i;
const riskPattern = /风险|失效|缺失|缺口|不足|过期|不可|未通过|未核验|待确认|待复核|不确定|尚需|尚未|失败|暂停|仅供|初步数据|needs_review|unverified|unavailable|degraded|stale|blocked|missing|failed|invalid|SUSPENDED_DATA|NO_TRADE|PRELIM/i;
export function isMachineText(text: string): boolean { return machine.test(text); }
export function readableText(text: string, important = false): string {
  let value = text.trim().replace(/^(?:(?:宏观|期权|风险|技术面|新闻|市场赔率)\s*前置风险[:：]\s*|(?:Macro|Options|Risk|Technical|News|MarketOdds)\s+prior risk:\s*)+/gi, '');
  if (/^(?:version|asset|bias|confidence|schema_version|run_id|snapshot_id|receipt_id|result_id)\s*:/i.test(value)) return important && riskPattern.test(value) ? '核验信息存在限制，暂不可确认参考资格。' : '';

  if (/^\s*\{\s*["']|^\s*\[\s*(?:\{|["']|\[)|^\s*["']?[a-z][a-z_]+["']?\s*:\s*[\[{]/i.test(value)) return important || riskPattern.test(value) ? '存在尚未解释的限制，需进一步核实；暂不能据此确认参考条件。' : '';

  value = value.replace(/This report is observe-only and must not replace an accepted final report\.?/gi, '本报告仅供研究观察，不能替代已核验的正式报告。');
  value = value.replace(/^Observe and wait.*?(?=[\u3400-\u9fff])/i, '仅供观察；')
    .replace(/DXY directional change is unavailable;?\s*only the current level is confirmed\.?/gi, '美元方向变化缺失，仅确认当前水平。');
  for (const [key, label] of Object.entries(translations).sort((a, b) => b[0].length - a[0].length)) {
    value = value.replace(new RegExp(`\\b${key}\\b`, 'g'), label);
  }
  value = value.replace(/\bQualityGate\b|\bGate\b/g, '参考条件').replace(/\bconfidence\b/gi, '判断把握程度').replace(/\bpublish_allowed\s*[:=]\s*false\b/gi, '尚不具备正式参考资格');
  value = value.replace(/\[[^\]]*\]\((?:https?:\/\/|\/)[^)]*\)/g, (match) => match.slice(1, match.indexOf(']')));
  if (machine.test(value) || /^\s*\{\s*["']|^\s*\[\s*(?:\{|["']|\[)/.test(value) || /^https?:\/\//.test(value) || /\b[a-z]+_[a-z_]+\b/.test(value)) {
    return important || riskPattern.test(value) ? '存在尚未解释的限制，需进一步核实；暂不能据此确认参考条件。' : '';
  }
  if (!/[\u3400-\u9fff]/.test(value) && /[a-z]{3}/i.test(value) && !/^(?:XAUUSD|DXY|GC|CME|TIPS|GEX|ATR|OI|USD|FedWatch|Gamma|IV|Skew)(?:\s*(?:-|:|：|\/)?\s*[\d.,%+−–-]+(?:bp)?)?$/i.test(value)) return important || riskPattern.test(value) ? '尚无可核实的中文说明，相关限制待确认。' : '';
  const symbolLabels: Record<string, string> = { XAUUSD: '黄金现货', DXY: '美元指数', GC: '黄金期货', CME: '芝商所', FRED: '美国经济数据库', VIX: '市场波动率指数', TIPS: '通胀保值国债', GEX: '伽马敞口', ATR: '平均真实波幅', OI: '未平仓持仓量', USD: '美元', FEDWATCH: '政策利率预期', GAMMA: '伽马', IV: '隐含波动率', SKEW: '波动率偏斜' };
  if (symbolLabels[value.toUpperCase()]) return symbolLabels[value.toUpperCase()];
  return value.replace(/\bGold\b/g, '黄金').replace(/\bHOLD\b/g, '沿用').trim();
}
export function readableWarning(text: string | null | undefined): string {
  return uniqueReading((text ?? '').split(/；|\n/).map((item) => readableText(item, true))).join('；') || '分析存在待确认项，请核实后再参考。';
}
export function uniqueReading(items: string[]): string[] {
  const seen = new Set<string>();
  return items.filter((item) => { const key = item.replace(/[\s*#`]/g, ''); if (!key || seen.has(key)) return false; seen.add(key); return true; });
}
export interface ResearchReading { highlights: string[]; remaining: string[]; risks: string[]; omitted: boolean }
export function researchReading(content: string): ResearchReading {
  const lines: string[] = [];
  const risks: string[] = [];
  let fence = false;
  let riskSection = false;
  let hiddenDepth: number | null = null;
  let omitted = false;
  for (const raw of content.split(/\r?\n|(?<=[。！？；])(?=[^\n])/)) {
    const trimmed = raw.trim();
    if (/^\s*(```|~~~)/.test(raw)) { fence = !fence; omitted = true; continue; }
    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    const plain = trimmed.replace(/^#{1,6}\s+|^[-*+]\s+|^\d+[.)]\s+/g, '').replace(/\*\*/g, '');
    const technical = technicalHeading.test(plain);
    if (heading) {
      riskSection = /风险|失效|限制|缺口|risk|invalid|limitation/i.test(plain);
      if (hiddenDepth !== null && heading[1].length <= hiddenDepth) hiddenDepth = null;
      if (technical) hiddenDepth = heading[1].length;
    }
    const knownHeading = heading ? researchLabels[plain.toLowerCase().replace(/ /g, '_')] : null;
    const readable = knownHeading ?? readableText(plain);
    if (riskPattern.test(plain) && !heading && !technical && plain.length > 0) {
      const risk = readableWarning(plain);
      if (!/^\|[- :|]+\|$/.test(risk)) risks.push(risk);
    }
    if (fence || hiddenDepth !== null || technical || !readable || /^\|[- :|]+\|$/.test(trimmed) || /^!\[/.test(trimmed) || /^<[^>]+>/.test(trimmed)) { omitted ||= Boolean(trimmed); continue; }
    if (heading && /^[A-Za-z _/-]+$/.test(plain)) {
      const label = researchLabels[plain.toLowerCase().replace(/ /g, '_')];
      if (label) lines.push(`### ${label}`);
      continue;
    }
    if (!heading && riskPattern.test(plain) && riskSection) continue;
    lines.push(heading ? `${heading[1]} ${readable}` : readable);
  }
  const sections: Array<{ rank: number; lines: string[] }> = [];
  const rankFor = (heading: string) => /当前判断|综合判断|结论|摘要/.test(heading) ? 0 : /依据|变化|要点/.test(heading) ? 1 : /为什么|重要|影响/.test(heading) ? 2 : /观察|关注|监控/.test(heading) ? 3 : /触发|确认条件/.test(heading) ? 4 : /风险|失效|限制/.test(heading) ? 5 : 6;
  for (const line of uniqueReading(lines)) {
    if (/^#{1,6} /.test(line) || !sections.length) sections.push({ rank: /^#/.test(line) ? rankFor(line) : 0, lines: [] });
    sections[sections.length - 1].lines.push(line);
  }
  const all = sections.sort((a, b) => a.rank - b.rank).flatMap((section) => section.lines);

  const highlights: string[] = [];
  let length = 0;
  let split = 0;
  for (const line of all) {
    if (highlights.length >= 16 || length + line.length > 4800 || line.length > 900) break;
    highlights.push(line); length += line.length; split++;
  }
  return { highlights, remaining: all.slice(split), risks: uniqueReading(risks), omitted };
}
export function structuredResearch(value: unknown): string {
  const result: string[] = [];
  const visit = (node: unknown, depth: number, context = '') => {
    if (depth > 8 || node == null) return;
    if (typeof node === 'string') { if (context) result.push(node); return; }
    if (typeof node === 'number' || typeof node === 'boolean') { if (context) result.push(String(node)); return; }
    if (Array.isArray(node)) { for (const child of node) visit(child, depth + 1, context); return; }
    if (typeof node !== 'object') return;
    for (const [key, child] of Object.entries(node)) {
      if (key === 'publish_allowed' && child === false) { result.push('尚不具备正式参考资格。'); continue; }
      if (/quality[ _-]?gate|gate/i.test(key) && child && typeof child === 'object' && (child as Record<string, unknown>).passed === false) { result.push('参考条件尚未通过，暂不可参考。'); continue; }
      if (machine.test(key) || technicalHeading.test(key)) continue;
      const label = researchLabels[key];
      if (label) { result.push(`### ${label}`); visit(child, depth + 1, key); }
      else if (riskPattern.test(key) && child) result.push('存在尚未解释的风险或限制，需要进一步核实。');
      else if (!context && ['report', 'research', 'sections', 'report_content', 'structured_payload'].includes(key)) visit(child, depth + 1);
    }
  };
  visit(value, 0);
  return result.join('\n');
}
