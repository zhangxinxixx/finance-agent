from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.web_flash import (
    collect_jin10_web_flash_from_html,
    collect_jin10_web_flash_with_browser_profile,
)
from apps.features.news.jin10_web_flash_briefs import archive_jin10_web_flash_briefs, build_jin10_web_flash_briefs
from apps.parsers.jin10.web_flash import parse_jin10_web_flash_html


def generate_jin10_web_flash_sample(
    *,
    html_file: Path | None,
    browser_profile: Path | None = None,
    chromium_executable: Path | None = None,
    homepage_url: str = "https://www.jin10.com/",
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    fetched_at: str,
    dry_run: bool,
    overwrite: bool,
) -> dict[str, Any]:
    html_path = Path(html_file) if html_file is not None else None
    profile_path = Path(browser_profile) if browser_profile is not None else None
    chromium_path = Path(chromium_executable) if chromium_executable is not None else None
    root = Path(storage_root)
    source_mode = "browser_profile" if profile_path is not None else "fixture"
    _validate_storage_args(retrieved_date=retrieved_date, run_id=run_id)
    if source_mode == "fixture" and (html_path is None or not html_path.is_file()):
        raise FileNotFoundError(f"HTML fixture not found: {html_path}")

    planned = _planned_paths(root, retrieved_date, run_id)
    if dry_run:
        item_count = 0
        if source_mode == "fixture":
            html = html_path.read_text(encoding="utf-8")
            parsed = parse_jin10_web_flash_html(
                html,
                fetched_at=fetched_at,
                raw_artifact_path=planned["raw_path"].as_posix(),
            )
            item_count = len(parsed.get("items") or [])
        return {
            "status": "planned",
            "dry_run": True,
            "source_mode": source_mode,
            "retrieved_date": retrieved_date,
            "run_id": run_id,
            "item_count": item_count,
            "brief_count": 0,
            "artifact_path": planned["feature_relative"],
            "planned_paths": {
                "raw": planned["raw_path"].as_posix(),
                "parsed": planned["parsed_path"].as_posix(),
                "feature": planned["feature_path"].as_posix(),
            },
        }

    _refuse_existing_targets(planned, overwrite=overwrite)

    if source_mode == "browser_profile":
        parsed_payload = collect_jin10_web_flash_with_browser_profile(
            storage_root=root,
            retrieved_date=retrieved_date,
            run_id=run_id,
            fetched_at=fetched_at,
            user_data_dir=profile_path,
            executable_path=chromium_path,
            homepage_url=homepage_url,
        )
    else:
        html = html_path.read_text(encoding="utf-8")
        parsed_payload = collect_jin10_web_flash_from_html(
            html,
            storage_root=root,
            retrieved_date=retrieved_date,
            run_id=run_id,
            fetched_at=fetched_at,
        )
    bundle = build_jin10_web_flash_briefs(parsed_payload=parsed_payload, as_of=fetched_at)
    feature_relative_from_storage = archive_jin10_web_flash_briefs(
        storage_root=root / "storage",
        retrieved_date=retrieved_date,
        run_id=run_id,
        bundle=bundle,
    )

    return {
        "status": bundle.status,
        "dry_run": False,
        "source_mode": source_mode,
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        "item_count": int(parsed_payload.get("itemCount") or 0),
        "brief_count": bundle.brief_count,
        "artifact_path": f"storage/{feature_relative_from_storage}",
        "raw_artifact_path": _optional_relative_to_root(parsed_payload.get("rawArtifactPath"), root),
        "parsed_artifact_path": _optional_relative_to_root(parsed_payload.get("parsedArtifactPath"), root),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a local Jin10 Web Important/VIP flash sample artifact from a fixture or browser profile."
    )
    parser.add_argument(
        "--html-file",
        type=Path,
        default=Path("tests/fixtures/jin10/web_flash/home_fixture.html"),
        help="Local Jin10 homepage HTML fixture. Default: tests/fixtures/jin10/web_flash/home_fixture.html.",
    )
    parser.add_argument(
        "--browser-profile",
        type=Path,
        help=(
            "Chromium user data directory for manual Jin10 homepage collection. "
            "Example: ~/.finance-agent/jin10_browser_profile."
        ),
    )
    parser.add_argument(
        "--chromium-executable",
        type=Path,
        help="Optional Chromium executable path for browser-profile collection.",
    )
    parser.add_argument(
        "--homepage-url",
        default="https://www.jin10.com/",
        help="Jin10 homepage URL for browser-profile collection. Default: https://www.jin10.com/.",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path("."),
        help="Workspace root where the storage/ tree will be created. Default: current directory.",
    )
    parser.add_argument(
        "--retrieved-date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Retrieved date in YYYY-MM-DD format. Default: current UTC date.",
    )
    parser.add_argument(
        "--run-id",
        default="jin10-web-flash-sample",
        help="Run identifier used in storage paths. Default: jin10-web-flash-sample.",
    )
    parser.add_argument(
        "--fetched-at",
        default=datetime.now(timezone.utc).isoformat(),
        help="Fetch timestamp stored in source refs and feature metadata. Default: current UTC timestamp.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned writes without creating files.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing sample artifacts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = generate_jin10_web_flash_sample(
        html_file=args.html_file,
        browser_profile=args.browser_profile,
        chromium_executable=args.chromium_executable,
        homepage_url=args.homepage_url,
        storage_root=args.storage_root,
        retrieved_date=args.retrieved_date,
        run_id=args.run_id,
        fetched_at=args.fetched_at,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _planned_paths(root: Path, retrieved_date: str, run_id: str) -> dict[str, Any]:
    return {
        "raw_path": root / "storage" / "raw" / "jin10" / "web_flash" / retrieved_date / run_id / "home.html",
        "parsed_path": root
        / "storage"
        / "parsed"
        / "jin10"
        / "web_flash"
        / retrieved_date
        / run_id
        / "web_flash_items.json",
        "feature_path": root / "storage" / "features" / "news" / retrieved_date / run_id / "jin10_web_flash_briefs.json",
        "feature_relative": f"storage/features/news/{retrieved_date}/{run_id}/jin10_web_flash_briefs.json",
    }


def _validate_storage_args(*, retrieved_date: str, run_id: str) -> None:
    if "/" in retrieved_date or "\\" in retrieved_date or ".." in retrieved_date:
        raise ValueError("retrieved_date must be a single YYYY-MM-DD path component")
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError("run_id must be a single path component")


def _refuse_existing_targets(planned: dict[str, Any], *, overwrite: bool) -> None:
    if overwrite:
        return
    existing = [path for key, path in planned.items() if key.endswith("_path") and isinstance(path, Path) and path.exists()]
    if existing:
        existing_text = ", ".join(path.as_posix() for path in existing)
        raise FileExistsError(f"Refusing to overwrite existing Jin10 web flash sample artifacts: {existing_text}")


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _optional_relative_to_root(path: Any, root: Path) -> str | None:
    if not path:
        return None
    return _relative_to_root(Path(path), root)


if __name__ == "__main__":
    raise SystemExit(main())
