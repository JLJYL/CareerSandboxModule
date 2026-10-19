"""資源目錄品質測試（成員 A）——目錄進 repo 前的守門。

對象：課程 `fixtures/resources/resources_v1.json`、競賽 `fixtures/resources/competitions_v1.jsonl`
（競賽的正式歸宿是 Mongo，此檔是標好技能的版本，既供後端組匯入、也當 reinforce 的 fallback）。
重點：每筆資源的 skills 都必須是詞彙表的 name_zh，否則配對永遠對不上、靜默回空。
這條測試讓「技能寫錯字」在 CI 就爆，而不是上線後前端拿到空清單才發現。
"""
import json
import re
from datetime import date
from pathlib import Path

from app.pipeline.reinforce import _competitions_fixture, load_resources

_VOCAB_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "vocab" / "skills_v1.json"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _vocab_names() -> set[str]:
    return {e["name_zh"] for e in json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))}


def test_catalog_loads_and_nonempty():
    cat = load_resources()
    assert isinstance(cat, list) and cat, "目錄不得為空"


def test_every_skill_is_vocab_name_zh():
    """最關鍵的一條：skills 必須逐字命中詞彙表 name_zh。"""
    vocab = _vocab_names()
    offenders = {
        r["resourceId"]: [s for s in r["skills"] if s not in vocab]
        for r in load_resources()
        if any(s not in vocab for s in r["skills"])
    }
    assert not offenders, f"下列資源的技能不在詞彙表 name_zh：{offenders}"


def test_required_fields_present():
    for r in load_resources():
        for key in ("resourceId", "type", "title", "provider", "providerKey", "skills"):
            assert r.get(key) not in (None, ""), f"{r.get('resourceId')} 缺欄位 {key}"
        assert isinstance(r["skills"], list) and r["skills"], f"{r['resourceId']} skills 不得為空"


def test_resource_id_unique():
    ids = [r["resourceId"] for r in load_resources()]
    assert len(ids) == len(set(ids)), "resourceId 有重複"


def test_type_and_id_prefix_agree():
    """type 只能是兩值，且 id 前綴要和 type 一致（crs_=課程 / cmp_=競賽）。"""
    for r in load_resources():
        assert r["type"] in ("course", "competition"), f"{r['resourceId']} type 非法：{r['type']}"
        prefix = "crs_" if r["type"] == "course" else "cmp_"
        assert r["resourceId"].startswith(prefix), \
            f"{r['resourceId']} 前綴與 type（{r['type']}）不符"


def test_deadline_format_and_course_has_none():
    """競賽 deadline 空或 YYYY-MM-DD；課程一律空（課程不設截止）。"""
    for r in load_resources():
        dl = r.get("deadline", "")
        if r["type"] == "course":
            assert dl == "", f"{r['resourceId']} 是課程，deadline 應為空"
        elif dl:
            assert _DATE_RE.match(dl), f"{r['resourceId']} deadline 格式非 YYYY-MM-DD：{dl}"


def test_courses_only_in_resources_file():
    """resources_v1.json 現在只放課程；競賽另存 competitions_v1.jsonl。"""
    assert all(r["type"] == "course" for r in load_resources())


# ---------------------------------------------------------------------------
# 競賽目錄（competitions_v1.jsonl，經 tag_competitions.py 標好技能）
# ---------------------------------------------------------------------------

def test_competition_skills_are_vocab_name_zh():
    """競賽標到的技能也必須逐字命中詞彙表 name_zh（標不到的為空陣列，允許）。"""
    vocab = _vocab_names()
    offenders = {
        c["resourceId"]: [s for s in c["skills"] if s not in vocab]
        for c in _competitions_fixture()
        if any(s not in vocab for s in c["skills"])
    }
    assert not offenders, f"下列競賽的技能不在詞彙表 name_zh：{offenders}"


def test_competitions_present_and_some_tagged():
    comps = _competitions_fixture()
    assert comps, "competitions_v1.jsonl 不得為空"
    assert all(c["resourceId"] for c in comps), "每筆競賽都要有 resourceId（來自 sourceId）"
    assert any(c["skills"] for c in comps), "至少要有一筆競賽標到技能，否則推薦永遠空手"


def test_competition_deadline_is_date_or_empty():
    for c in _competitions_fixture():
        dl = c.get("deadline", "")
        if dl:
            assert _DATE_RE.match(dl), f"{c['resourceId']} deadline 非 YYYY-MM-DD：{dl}"
