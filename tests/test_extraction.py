"""擷取管線單元測試——全部用 FakeLLM/序列 LLM,不需要金鑰,CI 可跑。"""
import json

import pytest

from app.pipeline.extraction import ExtractionError, LlmExtractor
from app.pipeline.profile import aggregate_display_skills, build_profile
from app.providers.llm import FakeLLM
from app.schemas.domain import CanonicalSkill

NARR = ["我大二在系學會當行銷組長,把社團 IG 從零做到一千二追蹤"]

GOOD = json.dumps({"experiences": [{
    "title": "系學會行銷組長", "category": "社團", "time_range": "2024.09 - 2025.06",
    "description": "負責社群經營,IG 從零累積至一千二百追蹤。",
    "raw_skills": ["社群經營", "內容創作"],
    "source_quote": "把社團 IG 從零做到一千二追蹤", "confidence": 88}]}, ensure_ascii=False)


class SeqLLM:
    """依序回傳預先排好的輸出,測重試路徑。"""
    def __init__(self, outputs):
        self._outputs = list(outputs)

    def complete(self, system, user, force_json=False):
        return self._outputs.pop(0)


def test_happy_path():
    drafts = LlmExtractor(FakeLLM(GOOD)).extract(NARR)
    assert len(drafts) == 1 and drafts[0].category == "社團"
    assert drafts[0].source_quote in NARR[0]


def test_retry_recovers_from_garbage():
    drafts = LlmExtractor(SeqLLM(["這不是 JSON", GOOD])).extract(NARR)
    assert drafts[0].title == "系學會行銷組長"


def test_double_failure_raises():
    with pytest.raises(ExtractionError):
        LlmExtractor(SeqLLM(["垃圾", "還是垃圾"])).extract(NARR)


def test_fabricated_quote_rejected():
    fake = GOOD.replace("把社團 IG 從零做到一千二追蹤", "我拿過金牌")
    with pytest.raises(ExtractionError):   # 證據句不在原文 → 防捏造防線觸發
        LlmExtractor(SeqLLM([fake, fake])).extract(NARR)


def test_exclamation_sanitized():
    noisy = GOOD.replace("負責社群經營,", "負責社群經營!超強!")
    drafts = LlmExtractor(FakeLLM(noisy)).extract(NARR)
    assert "!" not in drafts[0].description and "！" not in drafts[0].description


def test_profile_w1_and_w2_modes():
    drafts = LlmExtractor(FakeLLM(GOOD)).extract(NARR)
    p1 = build_profile("dev_user_001", drafts)             # W1:無 normalizer
    assert p1.raw_tags and not p1.skills
    assert aggregate_display_skills(p1) == p1.raw_tags

    class StubNorm:                                        # W2:A 的正規化器插入
        def normalize(self, raw):
            return CanonicalSkill(skill_id="skill_sns", name_zh="社群經營") \
                if raw == "社群經營" else None

    p2 = build_profile("dev_user_001", drafts, StubNorm())
    assert p2.skills[0].skill_id == "skill_sns" and "內容創作" in p2.raw_tags
