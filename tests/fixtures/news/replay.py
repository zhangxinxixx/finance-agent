from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any


_FIXTURE_ROOT = Path(__file__).resolve().parent


def materialize_news_replay(
    target_root: Path,
    *,
    scenario: str,
    include_features: bool,
    include_collectors: bool,
    include_outputs: bool,
) -> dict[str, Any]:
    scenario_root = _FIXTURE_ROOT / scenario / "storage"
    if include_features:
        _copy_tree(scenario_root / "features", target_root / "storage" / "features")
    if include_collectors:
        _copy_tree(scenario_root / "raw", target_root / "storage" / "raw")
        _copy_tree(scenario_root / "parsed", target_root / "storage" / "parsed")
    if include_outputs:
        _copy_tree(scenario_root / "outputs", target_root / "outputs")
    return describe_news_replay(target_root, scenario=scenario)


def describe_news_replay(target_root: Path, *, scenario: str) -> dict[str, Any]:
    feature_date, feature_run_id, feature_dir = _latest_nested_run_dir(target_root / "storage" / "features" / "news")
    output_date, output_run_id, output_dir = _latest_nested_run_dir(target_root / "outputs" / "jin10")
    return {
        "scenario": scenario,
        "storage_root": target_root / "storage",
        "outputs_root": target_root / "outputs",
        "feature_date": feature_date,
        "feature_run_id": feature_run_id,
        "feature_dir": feature_dir,
        "brief_path": feature_dir / "daily_market_brief.json" if feature_dir else None,
        "output_date": output_date,
        "output_run_id": output_run_id,
        "output_dir": output_dir,
        "raw_article_report_path": output_dir / "raw_article_report.json" if output_dir else None,
        "daily_analysis_path": output_dir / "daily_analysis.json" if output_dir else None,
        "report_md_path": output_dir / "report.md" if output_dir else None,
    }


def _latest_nested_run_dir(base: Path) -> tuple[str | None, str | None, Path | None]:
    if not base.exists():
        return None, None, None
    for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
        run_dirs = sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True)
        if run_dirs:
            return date_dir.name, run_dirs[0].name, run_dirs[0]
    return None, None, None


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
