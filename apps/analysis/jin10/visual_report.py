from __future__ import annotations

from apps.documents.schemas import DailyReportAnalysisSnapshot, Jin10DailyAnalysisReport


def build_jin10_daily_analysis_report(snapshot: DailyReportAnalysisSnapshot) -> Jin10DailyAnalysisReport:
    return Jin10DailyAnalysisReport(
        document_id=snapshot.document_id,
        trade_date=snapshot.trade_date,
        run_id=snapshot.article_id,
        article_id=snapshot.article_id,
        title=snapshot.title,
        family="jin10_daily_visual",
        asset="XAUUSD",
        core_conclusion=snapshot.core_conclusion,
        market_prices=snapshot.market_prices,
        logic_chains=snapshot.logic_chains,
        watch_variables=snapshot.watch_variables,
        key_levels=snapshot.key_levels,
        scenario_matrix=snapshot.scenario_matrix,
        risks=snapshot.risks,
        source_refs=snapshot.source_refs,
        generated_from={
            "source": "jin10_external",
            "document_id": snapshot.document_id,
            "article_id": snapshot.article_id,
        },
    )
