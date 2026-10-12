"""Independent source ingestion under the existing Dagster scheduler."""

from dagster import Config, RetryRequested, job, op

from apps.worker.cme_settlement import run_settlement_ingestion


class CmeSettlementConfig(Config):
    storage_root: str = "./storage"
    trade_date: str | None = None


@op(required_resource_keys={"db_session"}, tags={"source": "cme_settlement"})
def cme_settlement_op(context, config: CmeSettlementConfig):
    result = run_settlement_ingestion(
        context.resources.db_session, storage_root=config.storage_root, trade_date=config.trade_date
    )
    health = result["source_health"]
    if health["request_status"] == "failed" and str(health.get("reason") or "").startswith("transport_"):
        # Each retry executes a new recorded task and snapshot. Never hide the failed attempt.
        raise RetryRequested(max_retries=1, seconds_to_wait=5)
    return result


@job(tags={"pipeline": "macro", "source": "cme_settlement"})
def cme_settlement_job():
    cme_settlement_op()
