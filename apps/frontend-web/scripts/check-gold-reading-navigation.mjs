import assert from 'node:assert/strict';
import { StaticRouter } from 'react-router-dom';
import { loader, React, renderToStaticMarkup, hookRunner, tick, liveRaw } from './strategy-test-harness.mjs';
const load=loader({'@/adapters/apiClient':{fetchJson(){throw new Error('Network forbidden');}}});
const nav=load('@/components/gold-workspace/goldReadingNavigation');
const adapter=loader({'@/adapters/apiClient':{fetchJson(){throw new Error('Network forbidden');}}})('@/adapters/goldWorkspace');
const source={report_id:'engineering-report',run_id:'engineering-run',snapshot_id:'engineering-snapshot',trade_date:'2026-10-13'};
const workspace=adapter.normalizeGoldWorkspace({schema_version:'gold_workspace.v1',generated_at:'2026-10-13T01:00:00Z',status:'partial',
 price:{key:'XAUUSD',value:0,observed_at:null},factors:[],research:{...source,status:'historical',latest_status:'unavailable',narrative:'工程冻结全文',summary:'工程判断',as_of:null},warnings:['工程限制']});
const context={workspace,scrollTop:1500,expandedSections:['完整依据'],topicGroup:'macro',focusLabel:'返回研究'};
const restored=nav.readGoldReadingContext(JSON.parse(JSON.stringify(context)));
assert.equal(restored.workspace.research.run_id,source.run_id);assert.equal(restored.workspace.price.value,0);
assert.equal(restored.workspace.price.observed_at,null);assert.equal(restored.scrollTop,1500);
assert.equal(restored.topicGroup,'macro');assert.equal(restored.workspace.research.status,'historical');
for(const bad of [null,{}, {workspace:{}},{workspace:{...workspace,schema_version:'future'}},{workspace:{...workspace,research:{}}}])assert.equal(nav.readGoldReadingContext(bad),null);
assert.equal(nav.readGoldReadingContext({...context,scrollTop:-5,topicGroup:'unknown'}).scrollTop,0);
assert.match(nav.compareGoldReportResearch(context,source),/字段一致/);
for(const field of Object.keys(source)) assert.match(nav.compareGoldReportResearch(context,{...source,[field]:'different'}),/不同/);
assert.match(nav.compareGoldReportResearch(context,{...source,snapshot_id:null}),/未完整核验/);
const state=nav.goldStrategyNavigation(context);
assert.equal(state.strategySource.sourceResultIdentity,null);assert.equal(state.strategySource.snapshotId,source.snapshot_id);
const strategy=load('@/components/strategy/strategyNavigation');
assert.equal(strategy.readStrategyNavigationState(JSON.parse(JSON.stringify(state))).goldWorkspaceResult.workspace.research.report_id,source.report_id);
assert.equal(strategy.readStrategyNavigationState({strategySource:{source:'external'}}),null);
assert.equal(nav.compareGoldStrategyResearch(context,null).label,'无法核验');
const identity=liveRaw().result_identity;
assert.equal(nav.compareGoldStrategyResearch(context,identity).label,'不同研究');
assert.equal(nav.compareGoldStrategyResearch(context,{...identity,effective_baseline:{...identity.effective_baseline,run_id:source.run_id}}).label,'无法核验','same run cannot prove authority/receipt identity');
assert.equal(nav.compareGoldStrategyResearch(context,{...identity,schema_version:'future'}).label,'无法核验');
// Existing formal identity behavior is retained for consumers that possess that contract.
const formalSource={...state.strategySource,sourceResultIdentity:identity};
assert.equal(strategy.compareStrategySourceIdentity(formalSource,identity).label,'身份一致');
assert.equal(strategy.compareStrategySourceIdentity(formalSource,{...identity,subject:{...identity.subject,result_id:'another'}}).label,'不同结果');
const { GoldResearchDecision }=load('@/components/gold-workspace/GoldWorkspacePanel');
const render=(component,props)=>renderToStaticMarkup(React.createElement(StaticRouter,{},React.createElement(component,props)));
const html=render(GoldResearchDecision,{data:workspace,reviewOnly:true});
assert.match(html,/本次研究未完成/);assert.match(html,/原策略仅供阅读/);assert.match(html,/工程限制/);assert.doesNotMatch(html,/现在怎么做/);
const unknownTime=render(GoldResearchDecision,{data:{...workspace,research:{...workspace.research,as_of:'2099-01-01T00:00:00Z'}},reviewOnly:true});
assert.match(unknownTime,/数据时点 未提供/);assert.doesNotMatch(unknownTime,/2099-01-01/,'report cutoff cannot fill missing research data_as_of');
const changed=render(GoldResearchDecision,{data:{...workspace,research:{...workspace.research,topics:[{group:'changes',status:'historical',judgment:'工程后端变化原文'}]}},reviewOnly:true});
assert.match(changed,/工程后端变化原文/);assert.match(changed,/报告当时变化/);
const missingChange=render(GoldResearchDecision,{data:{...workspace,research:{...workspace.research,topics:[{group:'changes',status:'unavailable',judgment:'MUST_NOT_PROMOTE_UNBOUND_CHANGE'}]}},reviewOnly:true});
assert.doesNotMatch(missingChange,/MUST_NOT_PROMOTE_UNBOUND_CHANGE/);
const actions=[];
const hook=hookRunner('@/hooks/useGoldAnalysisRefresh','useGoldAnalysisRefresh',{'@/adapters/goldWorkspace':{
 readGoldAnalysisTask(){actions.push('saved');return null;},fetchGoldAnalysisPreflight(){actions.push('preflight');return Promise.resolve({active_task_id:null});},
 startGoldAnalysis(){actions.push('write');throw new Error('Unexpected launch');},fetchGoldAnalysisTask(){throw new Error('Unexpected poll');},rememberGoldAnalysisTask(){}
}});
hook.render(async()=>false,false);hook.flush();await hook.render(async()=>false,false).start();await tick();assert.deepEqual(actions,[],'frozen reading must not preflight, poll or launch');
hook.render(async()=>false,true);hook.flush();await tick();assert.deepEqual(actions,['saved','preflight']);hook.unmount();
const {GoldFrozenReport,readFrozenGoldReport}=load('@/components/gold-workspace/GoldFrozenReport');
const frozenReport={report_id:'engineering-report',meta:{report_id:'engineering-report',asset:'XAUUSD',family:'gold_policy_daily',lifecycle_status:'needs_review'},
 available_tabs:['analysis'],tabs:{analysis:{key:'analysis',format:'markdown',content:'SHOULD_NOT_RENDER_BLOCKED_ARTIFACT'}},warnings:[],data_status:'unavailable',source_refs:[],artifact_refs:[],result_identity:null};
assert.equal(readFrozenGoldReport({...frozenReport,meta:{...frozenReport.meta,asset:'BTC'}}),null);
assert.equal(readFrozenGoldReport({...frozenReport,meta:{...frozenReport.meta,report_id:'another'}}),null);
const frozenMarkup=render(GoldFrozenReport,{report:frozenReport,onLatest(){}});
assert.match(frozenMarkup,/报告未通过质量审核/);assert.doesNotMatch(frozenMarkup,/SHOULD_NOT_RENDER_BLOCKED_ARTIFACT/);
const {GoldSpotLevels,GoldCmeLevels}=load('@/components/gold-workspace/GoldKeyLevels');
assert.match(render(GoldSpotLevels,{data:workspace,reviewOnly:true}),/不确认当前有效性或触发/);
assert.match(render(GoldCmeLevels,{data:workspace,reviewOnly:true}),/上次读取的GC结构/);
console.log('Gold reading navigation passed: frozen DTO/zero/missing timing, malformed state, all report identity mismatches, strategy unknown/different/formal comparisons, fail-closed reading and disabled analysis transport.');
