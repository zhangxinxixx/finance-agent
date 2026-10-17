"""Bounded macro daily in the existing Dagster control plane; no collection."""
from dataclasses import replace
from pathlib import Path

from dagster import Config, Field, String, Bool, job, op, resource

from apps.worker.pipelines.gold_macro_daily_scheduled import run_scheduled_gold_macro_daily
from dagster_finance.resources.db import DbSessionResource


class MacroDailyNoonConfig(Config):
    scheduled_for: str
    storage_root: str
    source_root: str
    prior_report_root: str
    recover: bool = False


@resource(config_schema={'enabled': Field(Bool, default_value=False),
                         'provider': Field(String, is_required=False)})
def macro_daily_gateway(context):
    if not context.resource_config['enabled']:
        return None
    from apps.llm.config import LLMConfig
    from apps.llm.gateway import LLMGateway
    config = LLMConfig.from_env()
    provider = context.resource_config.get('provider')
    if not provider or provider not in config.providers:
        raise ValueError('macro_daily_requires_explicit_configured_provider')
    return LLMGateway(config=replace(config, default_provider=provider, fallback_providers=(),
                                    providers={provider: config.providers[provider]}))


@op(required_resource_keys={'db_session', 'macro_daily_gateway'})
def gold_macro_daily_noon_op(context, config: MacroDailyNoonConfig):
    result = run_scheduled_gold_macro_daily(context.resources.db_session,
        scheduled_for=config.scheduled_for, source_root=Path(config.source_root),
        storage_root=Path(config.storage_root), prior_report_root=Path(config.prior_report_root),
        gateway=context.resources.macro_daily_gateway, recover=config.recover)
    context.add_output_metadata({'report_status': result['status'], 'publish_allowed': False,
                                 'report_id': result.get('report_id', 'none')})
    if result['status'] != 'generated':
        context.log.warning('Macro daily blocked: %s', result)
    else:
        context.log.info('Macro daily result: %s', result)
    return result


@job(resource_defs={'macro_daily_gateway': macro_daily_gateway, 'db_session': DbSessionResource()},
     tags={'pipeline': 'gold_macro_daily', 'publication': 'candidate'})
def gold_macro_daily_job():
    gold_macro_daily_noon_op()
