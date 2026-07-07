from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.notifications.feishu_card_builder import build_test_message
from apps.notifications.notification_agent import FeishuNotificationAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a finance-agent Feishu notification test message.")
    parser.add_argument("--message", default="finance-agent 飞书通知测试", help="Message body.")
    parser.add_argument("--title", default="Feishu Notification Test", help="Message title.")
    parser.add_argument("--dry-run", action="store_true", help="Build the Feishu payload without sending.")
    parser.add_argument("--no-record-task", action="store_true", help="Do not write a feishu_notification TaskRun.")
    args = parser.parse_args()

    request = build_test_message(message=args.message, title=args.title)
    if args.dry_run:
        request = replace(request, dry_run=True)

    agent = FeishuNotificationAgent(record_task_run=not args.no_record_task)
    result = agent.send(request)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
