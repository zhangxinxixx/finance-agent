"""Warehouse reconciliation and raw retention use the existing Dagster owner."""

from dagster import Config, job, op
from sqlalchemy.orm import sessionmaker

from apps.data_layer.warehouse_maintenance import run_warehouse_maintenance


class WarehouseMaintenanceConfig(Config):
    storage_root: str = "./storage"
    page_size: int = 500
    max_pages: int = 10
    retention_days: int = 30
    apply_retention: bool = False


@op(required_resource_keys={"db_session"}, tags={"pipeline": "warehouse"})
def warehouse_maintenance_op(context, config: WarehouseMaintenanceConfig):
    factory = sessionmaker(bind=context.resources.db_session.get_bind())
    result = run_warehouse_maintenance(factory, storage_root=config.storage_root,
                                      page_size=config.page_size, max_pages=config.max_pages,
                                      retention_days=config.retention_days, apply_retention=config.apply_retention)
    if result["status"] == "unavailable":
        raise RuntimeError(result["error_code"])
    return result


@job(tags={"pipeline": "warehouse"})
def warehouse_maintenance_job():
    warehouse_maintenance_op()
