import assert from 'node:assert/strict';
import { loader, React, renderToStaticMarkup, cases } from './strategy-test-harness.mjs';
import { reportFixture, researchFixture, detailFixture, reportArtifact, weeklyRevisionFixture } from './report-qualification-fixtures.mjs';
const load = loader({'@/adapters/apiClient': {ApiError: class extends Error{}, fetchJson(){throw new Error('Network forbidden');}}});
const meta = load('@/components/reports/reportListMeta');
const adapter = load('@/adapters/reports');
const detailMeta = load('@/components/reports/reportDetailMeta');
const parts = item => ({ analysis: { key: 'analysis', label: '分析稿', available: true, format: 'markdown', content: reportArtifact(item).content } });
const view = item => adapter.normalizeReportDetail(detailFixture(item), parts(item));
const html = (component, props) => renderToStaticMarkup(React.createElement(load('react-router-dom').StaticRouter, {location:'/'}, React.createElement(component, props)));
await cases([
  ['original-readable-is-not-published', () => {
    const item = reportFixture();
    assert.equal(meta.canOpenReport(item), true);
    assert.equal(meta.getReportListStatus(item).key, 'unknown');
    assert.doesNotMatch(meta.getReportListStatus(item).label, /已发布|已批准/);
  }],
  ['permission-publication-validity-independent', () => {
    for (const publish_allowed of [undefined, null, true, false, 'true', 1]) {
      const item = reportFixture('permission', { publish_allowed });
      const state = meta.getReportListStatus(item);
      assert.notEqual(state.key, 'published');
      assert.equal(meta.canOpenReport(item), true);
      assert.match(state.description, publish_allowed === true ? /获准发布/ : publish_allowed === false ? /不可发布/ : /许可未知/);
      assert.equal(detailMeta.getReportDetailStatus(view(item)).description, state.description);
    }
    const item = reportFixture('accepted', { publish_allowed: true, publication_status: 'accepted', lifecycle_status: 'snapshot_bound' });
    assert.notEqual(meta.getReportListStatus(item).key, 'published');
    const positive = reportFixture('positive', { publish_allowed: true, lifecycle_status: 'published', review_status: 'approved' });
    positive.research_identity = researchFixture(positive);
    assert.equal(meta.getReportListStatus(positive).key, 'published');
    assert.match(meta.getReportListStatus(positive).description, /价位有效/);
    assert.equal(detailMeta.reportNeedsReadingWarning(view(positive)), false);
    const unknownValidity = { ...positive, research_identity: null };
    assert.match(meta.getReportListStatus(unknownValidity).description, /当前有效性未知/);
    assert.equal(detailMeta.reportNeedsReadingWarning(view(unknownValidity)), true);
    for (const overrides of [{data_status:'partial'}, {publication_status:'degraded'}, {review_status:'pending'}]) {
      const restricted = {...positive,...overrides};
      assert.equal(meta.getReportListStatus(restricted).referenceOnly,true);
      assert.equal(detailMeta.getReportDetailStatus(view(restricted)).referenceOnly,true);
      assert.match(meta.getReportListStatus(restricted).description,/已发布/);
    }
    assert.equal(meta.isObservationReport(reportFixture('unknown-readonly')),false);
    assert.equal(meta.isObservationReport(reportFixture('observed',{publication_status:'observe'})),true);
  }],
  ['observation-history-conflict-and-unknown-enums', () => {
    for (const type of ['observation_report','observation_strategy_card']) {
      const item = reportFixture(type, { type, family: type === 'observation_report' ? 'observation_report_markdown' : type, publish_allowed: false, output_mode: 'observe', authority: 'observation_only' });
      assert.equal(meta.getReportListStatus(item).key, 'review'); assert.equal(meta.canOpenReport(item), true);
      assert.equal(detailMeta.reportNeedsReadingWarning(view(item)), true);
      const rendered = html(load('@/components/reports/ReportDetailSections').ReportDetailHero, {data:view(item),metrics:[],onRefresh(){},tabs:[],activeTab:'analysis',onTabChange(){},summaryChips:[]});
      assert.match(rendered, /不可发布/);
      const unknownPermission = {...item,publish_allowed:null};
      const unknownHtml = html(load('@/components/reports/ReportCard').ReportCard,{item:unknownPermission,onSelect(){},searchQuery:''});
      assert.match(unknownHtml,/许可未知/); assert.doesNotMatch(unknownHtml,/不可发布/);
    }
    const history = reportFixture('history', { lifecycle_status: 'published', publish_allowed: false, authority: 'historical_only', output_mode: 'historical' });
    history.research_identity = researchFixture(history, 'historical');
    assert.equal(meta.getReportListStatus(history).key, 'archived'); assert.match(meta.getReportListStatus(history).label, /历史已发布/);
    assert.match(meta.getReportListStatus(history).description, /仅供历史参考/);
    const conflict = reportFixture('conflict', { publish_allowed: true, report_identity: { publish_allowed: false, authority: 'observation_only' } });
    assert.equal(meta.getReportListStatus(conflict).key, 'unknown'); assert.match(meta.getReportListStatus(conflict).description, /冲突/);
    const unknown = reportFixture('enum', { lifecycle_status: 'future_state', authority: 'future_authority' });
    assert.equal(meta.getReportListStatus(unknown).key, 'unknown');
  }],
  ['same-projection-filters-cards-and-readonly-plan', () => {
    const fixtures = [reportFixture(),reportFixture('allowed',{publish_allowed:true}),reportFixture('denied',{publish_allowed:false})];
    const {filterReports} = load('@/components/reports/reportsPageModel');
    const filters = { reportTypes: [], asset: null, status: 'unknown', dataSource: null, dateRange: null };
    assert.equal(filterReports(fixtures,'',filters).length,2);
    assert.equal(filterReports(fixtures,'',{...filters,status:'published'}).length,0);
    for(const item of fixtures) {
      const state = meta.getReportListStatus(item), v=view(item);
      assert.equal(detailMeta.getReportDetailStatus(v).description,state.description);
      assert.match(html(load('@/components/reports/ReportCard').ReportCard,{item,onSelect(){},searchQuery:''}),new RegExp(state.label));
      assert.match(html(load('@/components/reports/ReportsListView').ListView,{items:[item],onSelect(){},searchQuery:''}),new RegExp(state.description));
      assert.match(html(load('@/components/reports/ReportsTimelineView').TimelineView,{items:[item],onSelect(){},searchQuery:''}),new RegExp(state.description));
      assert.equal(v.tabs.analysis.content,reportArtifact(item).content);
    }
    const shared = load('@/components/shared/ResearchTradePlanCard').ResearchTradePlanCard;
    const item = reportFixture('active-observation');
    assert.doesNotMatch(html(shared,{identity:researchFixture(item),referenceOnly:true}),/当前做单策略/);
    assert.match(html(shared,{identity:researchFixture(item)}),/当前做单策略/);
  }],
  ['identity-boundary-and-content-read', async () => {
    const item=reportFixture('requested',{publish_allowed:false});
    const requests=[];
    const isolated=loader({'@/adapters/apiClient':{ ApiError: class extends Error{}, fetchJson:async path=>{
      requests.push(path); return path.endsWith('/analysis') ? reportArtifact(item) : detailFixture(item);
    }}})('@/adapters/reports');
    const v=await isolated.fetchReportDetailView(item.report_id);
    assert.equal(v.meta.report_id,item.report_id); assert.equal(v.meta.publish_allowed,false); assert.equal(v.tabs.analysis.content,reportArtifact(item).content);
    assert.equal(requests.length,2);
    const wrong=loader({'@/adapters/apiClient':{ApiError:class extends Error{},fetchJson:async()=>detailFixture(reportFixture('wrong'))}})('@/adapters/reports');
    await assert.rejects(()=>wrong.fetchReportDetailView('requested'),/身份/);
    const mismatched=loader({'@/adapters/apiClient':{ApiError:class extends Error{},fetchJson:async path=>path.endsWith('/analysis')?reportArtifact(reportFixture('wrong')):detailFixture(item)}})('@/adapters/reports');
    const mismatchView=await mismatched.fetchReportDetailView(item.report_id);
    assert.equal(mismatchView.tabs.analysis,undefined); assert(mismatchView.warnings.length>0);
    const published=reportFixture('same',{publish_allowed:true,lifecycle_status:'published'});
    published.research_identity=researchFixture(published);
    assert.equal(detailMeta.reportSelectionDifference(published,view(published)),null);
    assert.match(detailMeta.reportSelectionDifference({...published,snapshot_id:'other'},view(published)),/身份|版本/);
    assert.equal(view(published).meta.asOf,published.research_identity.data_as_of);
  }],
  ['index-permission-normalization-alias-and-refresh-projection', async () => {
    const items=[undefined,null,true,false,'true',1].map((publish_allowed,i)=>reportFixture(`index-${i}`,{publish_allowed}));
    const indexAdapter=loader({'@/adapters/apiClient':{ApiError:class extends Error{},fetchJson:async()=>({reports:items,asset:'XAUUSD'})}})('@/adapters/reports');
    const index=await indexAdapter.fetchReportsIndex();
    assert.deepEqual(Array.from(index.reports,item=>item.publish_allowed),[null,null,true,false,null,null]);
    const item=reportFixture('canonical',{publish_allowed:true,lifecycle_status:'published'});
    item.research_identity=researchFixture(item);
    const aliasAdapter=loader({'@/adapters/apiClient':{ApiError:class extends Error{},fetchJson:async path=>path.endsWith('/analysis')?reportArtifact(item):detailFixture(item)}})('@/adapters/reports');
    assert.equal((await aliasAdapter.fetchReportDetailView(item.run_id)).report_id,item.report_id);
    const rendered=html(load('@/components/reports/ReportDetailSections').ReportDetailHero,{data:view(item),metrics:[],onRefresh(){},tabs:[],activeTab:'analysis',onTabChange(){},summaryChips:[],qualificationPending:true});
    assert.match(rendered,/资格待重新核验/);assert.doesNotMatch(rendered,/获准发布|已发布/);
  }],
  ['weekly-detail-reads-existing-structured-qualification', () => {
    for (const publicationStatus of ['observe', 'accepted']) {
      const {item, detail} = weeklyRevisionFixture(publicationStatus);
      assert.equal(Object.hasOwn(detail, 'publish_allowed'), false);
      assert.equal(Object.hasOwn(detail, 'publication_status'), false);
      const v = adapter.normalizeReportDetail(detail, parts(item));
      assert.equal(v.meta.publish_allowed, item.publish_allowed);
      assert.equal(v.meta.publication_status, item.publication_status);
      const state = detailMeta.getReportDetailStatus(v);
      assert.match(state.description, item.publish_allowed ? /获准发布/ : /不可发布/);
      assert.doesNotMatch(state.description, /许可未知|已发布/);
      assert.equal(state.key, meta.getReportListStatus(item).key);
      assert.equal(v.tabs.analysis.content, reportArtifact(item).content);
      assert.match(html(load('@/components/reports/ReportDetailSections').ReportDetailHero,
        {data:v,metrics:[],onRefresh(){},tabs:[],activeTab:'analysis',onTabChange(){},summaryChips:[]}),
        item.publish_allowed ? /获准发布/ : /不可发布/);
      for (const structured_payload of [null, {}, {publish_allowed:'false', publication_status:1}]) {
        const missing = adapter.normalizeReportDetail({...detail, structured_payload}, parts(item));
        assert.equal(missing.meta.publish_allowed, null);
        assert.match(detailMeta.getReportDetailStatus(missing).description, /许可未知/);
      }
      for (const overrides of [{publish_allowed:!item.publish_allowed}, {publication_status:'different_status'}]) {
        const conflict = adapter.normalizeReportDetail({...detail,...overrides}, parts(item));
        assert.equal(detailMeta.getReportDetailStatus(conflict).key, 'unknown');
        assert.match(detailMeta.getReportDetailStatus(conflict).description, /冲突/);
      }
    }
    const unrelated = reportFixture('non-weekly');
    const v = adapter.normalizeReportDetail({...detailFixture(unrelated),structured_payload:{publish_allowed:true,publication_status:'accepted'}},parts(unrelated));
    assert.equal(v.meta.publish_allowed,null);
    assert.match(detailMeta.getReportDetailStatus(v).description,/许可未知/);
  }],
]);
