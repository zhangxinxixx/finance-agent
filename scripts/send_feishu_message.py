#!/usr/bin/env python3
"""Send a message to a Feishu custom bot webhook."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.output.feishu import send_feishu_message  # noqa: E402


def _read_message(args: argparse.Namespace) -> str:
    if args.message is not None:
        return args.message

    path = Path(args.message_file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"message file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"message file is not a file: {path}")
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a text/post message to a Feishu custom bot webhook.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--message", help="Message body.")
    source.add_argument("--message-file", help="UTF-8 text/markdown file used as message body.")
    parser.add_argument("--title", default=None, help="Title used for post messages.")
    parser.add_argument("--message-type", choices=["text", "post"], default="text")
    parser.add_argument(
        "--webhook-url", default=os.getenv("FEISHU_WEBHOOK_URL"), help="Defaults to FEISHU_WEBHOOK_URL."
    )
    parser.add_argument("--secret", default=os.getenv("FEISHU_BOT_SECRET"), help="Optional custom bot signing secret.")
    parser.add_argument("--dry-run", action="store_true", help="Build and print payload without sending.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args(argv)

    if not args.webhook_url:
        parser.error("--webhook-url is required when FEISHU_WEBHOOK_URL is not set")

    message = _read_message(args)
    result = send_feishu_message(
        webhook_url=args.webhook_url,
        message=message,
        title=args.title,
        message_type=args.message_type,  # type: ignore[arg-type]
        secret=args.secret,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
