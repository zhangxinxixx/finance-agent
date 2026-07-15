#!/usr/bin/env python3
"""Run the fixed Jin10 daily/weekly VLM stability benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.jin10.vlm_benchmark import build_daily_weekly_manifest, run_benchmark  # noqa: E402
from apps.parsers.jin10.vision_recognition_agent import VisionMarkdownClient  # noqa: E402


def resolve_sample_assets(sample: dict[str, Any]) -> dict[str, Path]:
    parsed_dir = Path(str(sample["parsed_dir"]))
    page_payload = json.loads((parsed_dir / "page_images.json").read_text(encoding="utf-8"))
    page_no = int(sample["page_no"])
    page_item = next(item for item in page_payload.get("pages") or [] if int(item.get("page_no") or 0) == page_no)
    page_image = Path(str(page_item["image_path"]))
    figure_id = str(sample.get("figure_id") or "")
    analysis_image = parsed_dir / "figures" / f"{figure_id}.png" if figure_id else page_image
    if not page_image.is_file():
        raise FileNotFoundError(f"page image not found: {page_image}")
    if not analysis_image.is_file():
        raise FileNotFoundError(f"analysis image not found: {analysis_image}")
    return {"page_image": page_image, "analysis_image": analysis_image}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", default="storage")
    parser.add_argument("--output-root", default="storage/analysis/jin10_vlm_benchmarks")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--sample", action="append", default=None, help="Optional sample_id filter; repeatable.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and print the fixed manifest without reading sample assets or calling models.",
    )
    args = parser.parse_args()

    os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")
    manifest = build_daily_weekly_manifest(storage_root=args.storage_root)
    manifest["repeats"] = max(1, args.repeats)
    manifest["model"] = args.model
    manifest["reasoning_effort"] = args.reasoning_effort
    if args.sample:
        selected = set(args.sample)
        manifest["samples"] = [item for item in manifest["samples"] if item["sample_id"] in selected]
    if not manifest["samples"]:
        raise SystemExit("no benchmark samples selected")
    if args.validate_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    for sample in manifest["samples"]:
        assets = resolve_sample_assets(sample)
        sample["page_image"] = str(assets["page_image"])
        sample["analysis_image"] = str(assets["analysis_image"])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_slug = args.model.replace("/", "-")
    output_dir = Path(args.output_root) / f"{timestamp}-{model_slug}-{args.reasoning_effort}"
    def page_runner(model: dict[str, str], sample: dict[str, Any]) -> dict[str, Any]:
        client = VisionMarkdownClient(
            provider=model["provider"],
            model=model["model"],
            max_retries=0,
            reasoning_effort=args.reasoning_effort,
            timeout=360,
        )
        page_image = Path(str(sample["page_image"]))
        image = cv2.imread(str(page_image))
        if image is None:
            return {"payload": {}, "latency_ms": 0, "attempts": 1, "error": "page_image_unreadable"}
        height, width = image.shape[:2]

        def action() -> dict[str, Any]:
            return client.recognize_page_unified(
                image_path=page_image,
                page_no=int(sample["page_no"]),
                page_width=width,
                page_height=height,
                report_type=str(sample["report_type"]),
                preserve_cover_identity=sample["kind"] == "cover",
            )

        return _run_once(action, result_key="payload")

    result = run_benchmark(
        manifest=manifest,
        output_dir=output_dir,
        page_runner=page_runner,
        max_workers=max(1, args.workers),
        model_spec={"role": "candidate", "provider": "cockpit", "model": args.model},
        progress_callback=lambda completed, total, row: print(
            f"[{completed}/{total}] {row['sample_id']} repeat={row['repeat']} "
            f"success={row['success']} latency_ms={row['latency_ms']} attempts={row['attempts']}",
            flush=True,
        ),
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "overall_passed": result["overall_passed"],
                "production_switch_allowed": result["production_switch_allowed"],
                "metrics": result["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["overall_passed"] else 2


def _run_once(action: Callable[[], Any], *, result_key: str) -> dict[str, Any]:
    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in (1,):
        try:
            value = action()
            return {
                result_key: value,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "attempts": attempt,
                "usage": {},
            }
        except Exception as exc:
            last_error = exc
    return {
        result_key: None,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "attempts": 1,
        "usage": {},
        "error": f"{type(last_error).__name__}:{last_error}",
    }


if __name__ == "__main__":
    raise SystemExit(main())
