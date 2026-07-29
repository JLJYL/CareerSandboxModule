"""回程評測器的評分邏輯測試——純函式,不需 LLM 與模型,CI 可跑。"""
import importlib.util
from pathlib import Path

from app.schemas.domain import ExtractedExperience

_spec = importlib.util.spec_from_file_location(
    "batch_eval", Path(__file__).resolve().parents[1] / "scripts" / "batch_eval.py")
batch_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(batch_eval)


def _draft(cat, time_range, skills):
    return ExtractedExperience(
        title="t", category=cat, time_range=time_range, description="d",
        raw_skills=skills, source_quote="q", confidence=70)


ANSWER = {
    "expectedExperiences": [
        {"type": "campus", "spokenPeriod": "大二那一年"},
        {"type": "part_time", "spokenPeriod": ""},
    ],
    "ownedSkills": ["Excel", "門市接待"],
}


def test_grade_all_pass_with_lossless_abbreviation():
    drafts = [_draft("社團", "大二", ["活動企劃"]),      # 大二那一年→大二 = 無損縮寫
              _draft("工作", "", ["Excel", "門市接待"])]  # 無線索→空字串
    g = batch_eval.grade_sample(drafts, ANSWER, narrative="大二那一年在社團,也在店裡打工")
    assert g["card_count_ok"] and g["categories_ok"] and g["time_ok"]
    assert g["skills_recall"] == 1.0


def test_grade_catches_fabricated_time_and_wrong_category():
    drafts = [_draft("學業", "2025.09 - 2026.06", []),   # 類別錯+時間憑空變西元
              _draft("工作", "", [])]
    g = batch_eval.grade_sample(drafts, ANSWER, narrative="大二那一年在社團,也在店裡打工")
    assert not g["categories_ok"] and not g["time_ok"]


def test_omitted_time_in_narrative_downgrades_expectation():
    """出題寫手吞了時間台詞:答案卡有 spokenPeriod、敘述裡卻沒有——
    引擎誠實給空字串應判對;腦補出時間仍要抓。"""
    narrative = "- 參與迎新宿營活動\n- 在咖啡店打工"   # 通篇無時間詞
    honest = [_draft("社團", "", []), _draft("工作", "", [])]
    g = batch_eval.grade_sample(honest, ANSWER, narrative=narrative)
    assert g["time_ok"]

    fabricated = [_draft("社團", "大二", []), _draft("工作", "", [])]
    g2 = batch_eval.grade_sample(fabricated, ANSWER, narrative=narrative)
    assert not g2["time_ok"]
