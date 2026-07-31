"""B1 客製管線測試——確定性規則+假 LLM,免錢免模型。"""
import json

from app.pipeline.customize import customize
from app.pipeline.normalize import VocabNormalizer
from app.providers.llm import FakeLLM
from app.schemas.api import ExperienceIn

NORM = VocabNormalizer()

JOB = {"jobId": "fit_x", "title": "數據助理", "requiredSkills": ["SQL", "Excel", "報表彙整與管理"],
       "jd": "使用 SQL 與 Excel 產出報表,支援資料分析。"}

EXPS = [
    ExperienceIn(id="e1", title="電商實習", category="工作", timeRange="暑假",
                 description="每週用 SQL 跟 Excel 拉數據做週報給業務", tags=["SQL", "Excel"]),
    ExperienceIn(id="e2", title="系學會行銷組長", category="社團", timeRange="大二",
                 description="把社團 IG 從零做到 1200 追蹤", tags=["社群媒體經營"]),
]


class SeqLLM:
    def __init__(self, replies):
        self._r = list(replies)

    def complete(self, *a, **k):
        return self._r.pop(0)


def test_deterministic_without_llm():
    r = customize(JOB, EXPS, normalizer=NORM, llm=None)
    assert r.jdKeywords[:3] == ["SQL", "Excel", "報表彙整與管理"]
    assert "SQL" in r.coveredKeywords and "Excel" in r.coveredKeywords
    assert len(r.items) == 2
    assert r.items[0].highlighted and not r.items[1].highlighted   # 2 命中強化,0 命中弱化
    assert r.items[0].text == EXPS[0].description                  # 無 LLM → 原文出貨


def test_llm_rewrite_accepted_when_grounded():
    good = json.dumps({"items": [
        {"text": "以 SQL 與 Excel 進行資料處理,每週產出報表支援業務。"},
        {"text": "曾任系學會行銷組長,經營社群帳號累積 1200 追蹤。"}]}, ensure_ascii=False)
    r = customize(JOB, EXPS, normalizer=NORM, llm=FakeLLM(good))
    assert "報表" in r.items[0].text and r.items[0].text != EXPS[0].description


def test_fabricated_number_falls_back_to_original():
    bad = json.dumps({"items": [
        {"text": "獨立完成 20 份報表。"},                     # 20 是原文沒有的數字
        {"text": "經營社群累積 1200 追蹤。"}]}, ensure_ascii=False)
    r = customize(JOB, EXPS, normalizer=NORM, llm=SeqLLM([bad, bad]))
    assert r.items[0].text == EXPS[0].description               # 違規條退回原文
    assert "1200" in r.items[1].text                            # 合規條保留改寫
