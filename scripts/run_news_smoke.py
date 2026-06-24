from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.news.base import NewsCollectionResult


CollectorFn = Callable[..., NewsCollectionResult]


def _collector_registry() -> list[tuple[str, CollectorFn]]:
    from apps.worker.pipelines.news import _collectors

    return _collectors()


def _query_group_registry() -> dict[str, dict[str, str]]:
    from apps.collectors.news.gdelt import GDELT_DOC_QUERIES
    from apps.collectors.news.google_news_rss import GOOGLE_NEWS_QUERIES
    from apps.collectors.news.reuters_public import REUTERS_PUBLIC_QUERIES

    return {
        "gdelt_news": GDELT_DOC_QUERIES,
        "google_news_rss": GOOGLE_NEWS_QUERIES,
        "reuters_public_news": REUTERS_PUBLIC_QUERIES,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run finance-agent news collectors as a standalone smoke CLI.")
    parser.add_argument(
        "--sources",
        default="all",
        help="Comma-separated news source keys, or 'all'. Default: all.",
    )
    parser.add_argument(
        "--storage-root",
        default="storage",
        help="finance-agent storage root used by underlying collectors.",
    )
    parser.add_argument(
        "--retrieved-date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Retrieved date in YYYY-MM-DD format. Default: current UTC date.",
    )
    parser.add_argument(
        "--run-id",
        default=_default_run_id(),
        help="Logical run identifier echoed in the JSON summary.",
    )
    parser.add_argument(
        "--query-groups",
        default="",
        help="Optional comma-separated query-group keys for candidate sources such as gdelt_news/google_news_rss/reuters_public_news.",
    )
    parser.add_argument(
        "--max-items-per-group",
        type=int,
        default=None,
        help="Optional per-query-group item cap passed to collectors that support it.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=None,
        help="Optional HTTP request timeout passed to collectors that support it.",
    )
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="Optional HTTP proxy URL passed to collectors that support explicit proxy routing.",
    )
    parser.add_argument(
        "--no-trust-env",
        action="store_true",
        help="Disable environment proxy settings for collectors that support trust_env.",
    )
    parser.add_argument(
        "--timespan",
        default=None,
        help="Optional GDELT-style timespan override, passed only to collectors that support it.",
    )
    parser.add_argument(
        "--rate-limit-cooldown-seconds",
        type=int,
        default=None,
        help="Optional local rate-limit cooldown passed only to collectors that support it.",
    )
    return parser


def _default_run_id() -> str:
    return "news-smoke-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_sources(raw_value: str, available_sources: list[str]) -> list[str]:
    tokens = [token.strip() for token in raw_value.split(",") if token.strip()]
    if not tokens or any(token == "all" for token in tokens):
        return list(available_sources)

    unknown = [token for token in tokens if token not in available_sources]
    if unknown:
        raise ValueError(
            f"Unknown source(s): {', '.join(unknown)}. Available: {', '.join(available_sources)}"
        )
    return tokens


def _parse_group_names(raw_value: str) -> list[str]:
    return [token.strip() for token in raw_value.split(",") if token.strip()]


def _select_query_groups(source_key: str, group_names: list[str]) -> dict[str, str] | None:
    if not group_names:
        return None
    source_groups = _query_group_registry().get(source_key)
    if not source_groups:
        return None
    selected = {name: query for name, query in source_groups.items() if name in group_names}
    return selected


def _build_collector_kwargs(
    *,
    collector: CollectorFn,
    source_key: str,
    retrieved_date: str,
    storage_root: Path,
    query_group_names: list[str],
    max_items_per_group: int | None,
    request_timeout_seconds: float | None,
    request_proxy: str | None,
    trust_env: bool | None,
    timespan: str | None,
    rate_limit_cooldown_seconds: int | None,
) -> dict[str, Any]:
    signature = inspect.signature(collector)
    parameters = signature.parameters
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    kwargs: dict[str, Any] = {
        "retrieved_date": retrieved_date,
        "storage_root": storage_root,
    }
    selected_query_groups = _select_query_groups(source_key, query_group_names)
    if selected_query_groups is not None:
        kwargs["query_groups"] = selected_query_groups
    if max_items_per_group is not None:
        kwargs["max_items_per_group"] = max_items_per_group
    if request_timeout_seconds is not None:
        if accepts_kwargs or "request_timeout" in parameters:
            kwargs["request_timeout"] = request_timeout_seconds
        elif "request_timeout_seconds" in parameters:
            kwargs["request_timeout_seconds"] = request_timeout_seconds
    if request_proxy is not None:
        kwargs["request_proxy"] = request_proxy
    if trust_env is not None:
        kwargs["trust_env"] = trust_env
    if timespan is not None:
        kwargs["timespan"] = timespan
    if rate_limit_cooldown_seconds is not None:
        kwargs["rate_limit_cooldown_seconds"] = rate_limit_cooldown_seconds

    if accepts_kwargs:
        return kwargs
    allowed = set(parameters)
    return {key: value for key, value in kwargs.items() if key in allowed}


def _summarize_source_refs(source_refs: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(ref.get("status") or "unknown") for ref in source_refs if isinstance(ref, dict))
    sample: list[dict[str, Any]] = []
    for ref in source_refs[:5]:
        if not isinstance(ref, dict):
            continue
        sample.append(
            {
                key: ref[key]
                for key in (
                    "source_ref",
                    "status",
                    "feed_key",
                    "query_group",
                    "reason_code",
                    "reason",
                    "warning",
                    "raw_path",
                    "parsed_path",
                )
                if key in ref and ref[key] is not None
            }
        )
    return {
        "count": len(source_refs),
        "status_counts": dict(status_counts),
        "sample": sample,
    }


def _success_summary(
    *,
    result: NewsCollectionResult,
    storage_root: Path,
    run_id: str,
    retrieved_date: str,
) -> dict[str, Any]:
    return {
        "source_key": result.source_key,
        "status": result.status,
        "item_count": len(result.items),
        "warning_count": len(result.warnings),
        "unavailable_feeds": list(result.unavailable_feeds),
        "source_refs": _summarize_source_refs(result.source_refs),
        "storage_root": str(storage_root.resolve()),
        "run_id": run_id,
        "retrieved_date": retrieved_date,
    }


def _error_summary(
    *,
    source_key: str,
    exc: Exception,
    storage_root: Path,
    run_id: str,
    retrieved_date: str,
) -> dict[str, Any]:
    reason = f"{type(exc).__name__}: {exc}"
    return {
        "source_key": source_key,
        "status": "error",
        "item_count": 0,
        "warning_count": 1,
        "unavailable_feeds": [],
        "source_refs": _summarize_source_refs(
            [
                {
                    "source_ref": f"{source_key}:collector_runtime",
                    "status": "error",
                    "reason": reason,
                    "reason_code": "collector_runtime_error",
                    "warning": reason,
                }
            ]
        ),
        "storage_root": str(storage_root.resolve()),
        "run_id": run_id,
        "retrieved_date": retrieved_date,
    }


def _query_group_selection_summary(
    *,
    source_key: str,
    requested_query_groups: list[str],
    available_query_groups: list[str],
    storage_root: Path,
    run_id: str,
    retrieved_date: str,
) -> dict[str, Any]:
    reason = (
        f"No requested query groups match {source_key}. "
        f"Requested: {', '.join(requested_query_groups)}. "
        f"Available: {', '.join(available_query_groups)}"
    )
    return {
        "source_key": source_key,
        "status": "unavailable",
        "item_count": 0,
        "warning_count": 1,
        "unavailable_feeds": list(requested_query_groups),
        "source_refs": _summarize_source_refs(
            [
                {
                    "source_ref": f"{source_key}:query_groups",
                    "status": "unavailable",
                    "reason": reason,
                    "reason_code": "invalid_query_groups",
                    "warning": reason,
                }
            ]
        ),
        "storage_root": str(storage_root.resolve()),
        "run_id": run_id,
        "retrieved_date": retrieved_date,
    }


def _overall_status(results: list[dict[str, Any]]) -> str:
    statuses = [str(item.get("status") or "") for item in results]
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "partial" for status in statuses):
        return "partial"
    if results and all(status == "success" for status in statuses):
        return "success"
    if any(status == "success" for status in statuses):
        return "partial"
    if any(status == "unavailable" for status in statuses):
        return "unavailable"
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    storage_root = Path(args.storage_root).expanduser()
    registry = dict(_collector_registry())
    available_sources = list(registry.keys())

    try:
        selected_sources = _parse_sources(args.sources, available_sources)
    except ValueError as exc:
        parser.error(str(exc))
    query_group_names = _parse_group_names(args.query_groups)
    trust_env = False if args.no_trust_env else None

    results: list[dict[str, Any]] = []
    had_runtime_error = False
    query_group_registry = _query_group_registry()
    for source_key in selected_sources:
        collector = registry[source_key]
        source_query_groups = query_group_registry.get(source_key)
        selected_query_groups = _select_query_groups(source_key, query_group_names)
        if query_group_names and source_query_groups is not None and selected_query_groups == {}:
            results.append(
                _query_group_selection_summary(
                    source_key=source_key,
                    requested_query_groups=query_group_names,
                    available_query_groups=list(source_query_groups),
                    storage_root=storage_root,
                    run_id=args.run_id,
                    retrieved_date=args.retrieved_date,
                )
            )
            continue
        try:
            result = collector(**_build_collector_kwargs(
                collector=collector,
                source_key=source_key,
                retrieved_date=args.retrieved_date,
                storage_root=storage_root,
                query_group_names=query_group_names,
                max_items_per_group=args.max_items_per_group,
                request_timeout_seconds=args.request_timeout_seconds,
                request_proxy=args.proxy_url,
                trust_env=trust_env,
                timespan=args.timespan,
                rate_limit_cooldown_seconds=args.rate_limit_cooldown_seconds,
            )
            )
        except Exception as exc:
            had_runtime_error = True
            results.append(
                _error_summary(
                    source_key=source_key,
                    exc=exc,
                    storage_root=storage_root,
                    run_id=args.run_id,
                    retrieved_date=args.retrieved_date,
                )
            )
            continue

        results.append(
            _success_summary(
                result=result,
                storage_root=storage_root,
                run_id=args.run_id,
                retrieved_date=args.retrieved_date,
            )
        )

    payload = {
        "run_id": args.run_id,
        "retrieved_date": args.retrieved_date,
        "storage_root": str(storage_root.resolve()),
        "requested_sources": selected_sources,
        "requested_query_groups": query_group_names,
        "proxy_url": args.proxy_url,
        "trust_env": not args.no_trust_env,
        "overall_status": _overall_status(results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if had_runtime_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
