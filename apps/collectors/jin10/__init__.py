"""Jin10 external report adapter."""

from apps.collectors.jin10.adapter import build_jin10_outputs, write_jin10_outputs
from apps.collectors.jin10.fetcher import (
    fetch_category_entries,
    fetch_svip_report,
    fetch_svip_report_via_browser_profile,
    write_external_report,
)

__all__ = [
    "build_jin10_outputs",
    "write_jin10_outputs",
    "fetch_category_entries",
    "fetch_svip_report",
    "fetch_svip_report_via_browser_profile",
    "write_external_report",
]
