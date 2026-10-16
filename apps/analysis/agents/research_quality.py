"""One versioned method shared by synthesis and its existing challenge pass.

This is a method contract, not a benchmark score or a market evidence source.
"""
from hashlib import sha256
from pathlib import Path
from copy import deepcopy

VERSION = "gold_research_quality.v1"
GATE_VERSION = "research_quality_gate.v1"
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


class ResearchQualityError(ValueError):
    """Safe, traceable refusal; never include local filenames or file contents."""

    def __init__(self, reason_code, *, requested_contract=None, available_contract=None):
        super().__init__(reason_code.replace('_', ' '))
        self.reason_code = reason_code
        self.details = {
            'requested_contract': deepcopy(requested_contract),
            'available_contract': deepcopy(available_contract),
            'recovery_condition': 'Restore the exact frozen standard and method, or create a new '
                                  'request bound to the new versions; never rewrite a frozen request.',
        }


def _materials():
    values = []
    for path, reason in ((STANDARD_PATH, 'quality_standard_unavailable'),
                         (METHOD_PATH, 'quality_method_unavailable')):
        try:
            data = path.read_bytes()
            text = data.decode('utf-8')
            if not text.strip():
                raise ValueError('empty method material')
        except (OSError, UnicodeError, ValueError) as exc:
            raise ResearchQualityError(reason) from exc
        values.append((data, text))
    contract = {
        "version": VERSION,
        "standard_sha256": sha256(values[0][0]).hexdigest(),
        "method_sha256": sha256(values[1][0]).hexdigest(),
        "reference_is_truth": False,
        "benchmark_parity": "not_evaluated",
    }
    return contract, values[1][1]


def quality_contract():
    return _materials()[0]


def quality_instructions(payload):
    contract = payload.get("research_quality_standard")
    if 'research_quality_standard' not in payload:
        if payload.get('report_profile', {}).get('version') == 'gold_reader.v4':
            raise ResearchQualityError('quality_contract_missing')
        return ""
    try:
        available, method = _materials()
    except ResearchQualityError as exc:
        exc.details['requested_contract'] = deepcopy(contract)
        raise
    if contract != available:
        raise ResearchQualityError('quality_method_fingerprint_mismatch',
                                   requested_contract=contract, available_contract=available)
    return method
