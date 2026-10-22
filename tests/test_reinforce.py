"""技能補強配對管線測試（成員 A）——確定性配對 + 假 LLM，免錢免模型。

多數案例用「自備小目錄」隔離測試，不隨正式目錄增刪而壞；最後一條對真目錄煙霧測試。
配對規則（交接四第六節）：本校課優先 → 他校課 → 競賽；過期競賽剔除；每技能最多 3 筆；
LLM 只寫 note，數字／誇飾詞超出原文一律退空。
"""
import json
from datetime import date

from app.pipeline.normalize import VocabNormalizer
from app.pipeline.reinforce import _from_comp_doc, reinforce
from app.providers.llm import FakeLLM

NORM = VocabNormalizer()                       # 降級（alias-only）即可：技能用 name_zh 逐字命中
TODAY = date(2026, 10, 17)

# 自備小目錄：技能一律用詞彙表 name_zh，normalize 才對得上
CATALOG = [
    {"resourceId": "crs_own", "type": "course", "title": "資料分析（本校）",
     "provider": "本校 · 資管", "providerKey": "nsysu", "skills": ["資料分析"],
     "description": "資料清理與視覺化。", "url": "", "deadline": ""},
    {"resourceId": "crs_other", "type": "course", "title": "資料分析（他校）",
     "provider": "他校", "providerKey": "other", "skills": ["資料分析"],
     "description": "統計與報表。", "url": "", "deadline": ""},
    {"resourceId": "cmp_live", "type": "competition", "title": "資料分析競賽",
     "provider": "某平台", "providerKey": "open", "skills": ["資料分析"],
     "description": "資料建模實戰。", "url": "", "deadline": "2027-05-31"},
    {"resourceId": "cmp_dead", "type": "competition", "title": "已過期競賽",
     "provider": "某平台", "providerKey": "open", "skills": ["資料分析"],
     "description": "去年的賽事。", "url": "", "deadline": "2025-01-01"},
]


def test_echoes_every_skill_in_order_even_when_unmatched():
    """輸入幾個技能就回幾個 item，順序一致；對不上的（職缺原字）回空清單但不消失。"""
    r = reinforce(["資料分析", "完全不存在的技能xyz"], normalizer=NORM,
                  catalog=CATALOG, today=TODAY, llm=None)
    assert [it.skill for it in r.items] == ["資料分析", "完全不存在的技能xyz"]
    assert r.items[1].resources == []          # 正規化對不上 → 空，不報錯


def test_no_llm_returns_resources_with_empty_notes():
    r = reinforce(["資料分析"], normalizer=NORM, catalog=CATALOG, today=TODAY, llm=None)
    res = r.items[0].resources
    assert res, "無金鑰也要回配對結果"
    assert all(x.note == "" for x in res)      # 無 LLM → note 全空，但資源照給


def test_ranking_own_school_then_other_then_competition():
    r = reinforce(["資料分析"], normalizer=NORM, school="nsysu",
                  catalog=CATALOG, today=TODAY, llm=None)
    ids = [x.resourceId for x in r.items[0].resources]
    assert ids == ["crs_own", "crs_other", "cmp_live"]   # 本校課→他校課→競賽；過期競賽不在內


def test_expired_competition_filtered_out():
    r = reinforce(["資料分析"], normalizer=NORM, catalog=CATALOG, today=TODAY, llm=None)
    ids = [x.resourceId for x in r.items[0].resources]
    assert "cmp_dead" not in ids               # 2025-01-01 早於 today → 剔除


def test_cap_three_per_skill():
    many = [{"resourceId": f"crs_{i}", "type": "course", "title": f"課{i}",
             "provider": "x", "providerKey": "nsysu", "skills": ["機器學習"],
             "description": "", "url": "", "deadline": ""} for i in range(5)]
    r = reinforce(["機器學習"], normalizer=NORM, catalog=many, today=TODAY, llm=None)
    assert len(r.items[0].resources) == 3      # 5 筆命中 → 上限 3


def test_courses_and_competitions_each_get_slots():
    """課程量大時競賽仍要出現：4 課 + 3 競賽 → 3 課在前、2 競賽在後。"""
    cat = [{"resourceId": f"crs_{i}", "type": "course", "title": f"課{i}",
            "provider": "x", "providerKey": "nsysu", "skills": ["資料分析"],
            "description": "", "url": "", "deadline": ""} for i in range(4)]
    cat += [_from_comp_doc({"sourceId": f"cmp{i}", "title": f"賽{i}", "organizer": "o",
                            "deadlineIso": f"2027-0{i+1}-01T00:00:00+08:00",
                            "skills": ["資料分析"]}) for i in range(3)]
    r = reinforce(["資料分析"], normalizer=NORM, school="nsysu", catalog=cat, today=TODAY, llm=None)
    types = [x.type for x in r.items[0].resources]
    assert types == ["course", "course", "course", "competition", "competition"]


def test_llm_note_grounded_is_kept():
    solo = [CATALOG[0]]                         # 只有 crs_own 一筆 → pairs 長度 1
    good = json.dumps({"notes": ["這門課帶你做資料清理與視覺化，正好補上資料分析的實作。"]},
                      ensure_ascii=False)
    r = reinforce(["資料分析"], normalizer=NORM, catalog=solo, today=TODAY, llm=FakeLLM(good))
    assert r.items[0].resources[0].note.startswith("這門課帶你做資料清理")


def test_llm_fabricated_number_dropped_to_empty():
    solo = [CATALOG[0]]                         # description 無數字
    bad = json.dumps({"notes": ["這門課有 300 小時實作。"]}, ensure_ascii=False)
    r = reinforce(["資料分析"], normalizer=NORM, catalog=solo, today=TODAY, llm=FakeLLM(bad))
    assert r.items[0].resources[0].note == ""  # 300 原文沒有 → 重試仍違規 → 退空


def test_real_catalog_smoke():
    """對真正進 repo 的目錄跑一次：常見缺口技能應配得到課程。"""
    r = reinforce(["資料分析"], normalizer=NORM, school="nsysu", today=TODAY, llm=None)
    res = r.items[0].resources
    assert res, "真目錄對『資料分析』應至少配到一筆"
    assert res[0].type == "course"             # 有本校課時，課程排在競賽之前


def test_from_comp_doc_maps_crawler_fields():
    """爬蟲競賽文件 → 資源形狀：resourceId 取 sourceId，deadline 取 ISO 的日期部分。"""
    doc = {"sourceId": "devpost-1", "title": "X Hack", "organizer": "Y",
           "category": "HACKATHON", "sourceUrl": "https://x",
           "deadlineIso": "2027-05-31T23:59:59+08:00", "skills": ["機器學習"]}
    r = _from_comp_doc(doc)
    assert r["resourceId"] == "devpost-1" and r["type"] == "competition"
    assert r["provider"] == "Y" and r["url"] == "https://x"
    assert r["deadline"] == "2027-05-31"       # ISO 截到日期，給 _expired 比
    assert r["skills"] == ["機器學習"]


def test_competition_recommended_when_only_source():
    """某技能只有競賽覆蓋時，應回競賽（驗證競賽文件能進配對）。"""
    cat = [_from_comp_doc({"sourceId": "cmp1", "title": "ML 挑戰賽", "organizer": "O",
                           "deadlineIso": "2027-05-31T00:00:00+08:00", "skills": ["機器學習"]})]
    r = reinforce(["機器學習"], normalizer=NORM, catalog=cat, today=TODAY, llm=None)
    res = r.items[0].resources
    assert [x.resourceId for x in res] == ["cmp1"]
    assert res[0].type == "competition"
