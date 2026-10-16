"""One versioned method shared by synthesis and its existing challenge pass.

This is a method contract, not a benchmark score or a market evidence source.
"""
from hashlib import sha256
from pathlib import Path

VERSION = "gold_research_quality.v1"
ROOT = Path(__file__).resolve().parents[3]
STANDARD_PATH = ROOT / "docs/evals/gold-research-quality-v1.md"
METHOD_PATH = ROOT / "apps/analysis/prompts/gold_research_quality.md"

QUALITY_QUESTIONS = [
    "前序论点动态改判：对已完整提供的合格前序逐项说明旧论点、新证据、强化/保持/削弱/失效/未知及复查条件；"
    "优先至少两项决定性论点，不足两项如实说明。没读到正文不能声称复盘，也不能只列指标涨跌代替改判。",
    "主导矛盾与竞争解释：区分事实、与事实相容的解释和已验证传导；给最强竞争解释、最强反证及可观测改判条件。"
    "缺证据可保留未知，不能把几何空间比当方向概率、OI增仓当买方身份或参考稿当真值。",
    "条件决策与事件增量：主/上/下路径共用明确期限；区分未确认、风险过宽、目标空间不足和缺数。"
    "事件快评只用截止前可得事实，区分初值/修订及首报/后续补证；旧CME和日终TIPS不能冒充事件后新证据。",
]


def quality_contract():
    return {
        "version": VERSION,
        "standard_sha256": sha256(STANDARD_PATH.read_bytes()).hexdigest(),
        "method_sha256": sha256(METHOD_PATH.read_bytes()).hexdigest(),
        "reference_is_truth": False,
        "benchmark_parity": "not_evaluated",
    }


def quality_instructions(payload):
    contract = payload.get("research_quality_standard")
    if contract is None:
        return ""
    if contract != quality_contract():
        raise ValueError("research quality method fingerprint mismatch; use its frozen source version")
    return METHOD_PATH.read_text(encoding="utf-8")
