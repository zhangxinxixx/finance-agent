"""P2-11: Seed prompt_versions table from hardcoded Agent registry.

Run once to migrate the 4 registered agents' prompts into prompt_versions as v1.
Idempotent — skips if a version already exists for an agent.
"""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.models.analysis import PromptVersion, ensure_analysis_tables
from database.models.engine import SessionLocal


def _sha256(obj: dict) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def seed() -> None:
    from apps.analysis.agents.registry import list_agent_registry

    agents = list_agent_registry()

    with SessionLocal() as db:
        ensure_analysis_tables(db)

        for agent in agents:
            agent_id = agent["agent_id"]
            prompt = agent.get("prompt") or {}
            template = prompt.get("template") or {}

            existing = (
                db.query(PromptVersion)
                .filter(PromptVersion.agent_id == agent_id, PromptVersion.version == "v1")
                .first()
            )
            if existing:
                print(f"[SKIP] {agent_id} v1 已存在")
                continue

            pv = PromptVersion(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                version="v1",
                prompt_kind=prompt.get("kind", "llm"),
                prompt_source=prompt.get("source"),
                prompt_template=template,
                prompt_sha256=_sha256(template),
                status="active",
                enabled=True,
                model_routing=prompt.get("model_routing"),
                change_note="从 registry.py 种子初始化（P2-11）",
                created_by="seed_prompt_versions",
            )
            db.add(pv)
            print(f"[OK] {agent_id} v1 已创建  ({prompt.get('kind')})")

        db.commit()
        print(f"\n总计: {db.query(PromptVersion).count()} 条 prompt 版本")


if __name__ == "__main__":
    seed()
