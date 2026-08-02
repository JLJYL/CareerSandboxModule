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


def test_single_best_match_rescued_as_highlighted():
    """相對救援條款:全員不足絕對門檻時,命中最高且至少 1 的條目仍標強化。"""
    job = {"jobId": "fit_y", "title": "社群企劃",
           "requiredSkills": ["品牌行銷管理", "文案撰寫", "Adobe Photoshop"], "jd": ""}
    exps = [ExperienceIn(id="e1", title="社團社群", category="社團", timeRange="",
                         description="經營 IG", tags=["文案撰寫"]),
            ExperienceIn(id="e2", title="資料課", category="學業", timeRange="",
                         description="", tags=["SQL"])]
    r = customize(job, exps, normalizer=NORM, llm=None)
    assert r.items[0].highlighted            # 唯一有命中者被救援
    assert not r.items[1].highlighted        # 零命中維持弱化


def test_embellishment_word_falls_back_to_original():
    """評價詞防線:原文沒有的「成功/精通」等詞,重試仍違規則該條退回原文。"""
    bad = json.dumps({"items": [
        {"text": "成功以 SQL 產出週報,支援業務。"},          # 「成功」原文沒有
        {"text": "經營社團 IG 累積 1200 追蹤。"}]}, ensure_ascii=False)
    r = customize(JOB, EXPS, normalizer=NORM, llm=SeqLLM([bad, bad]))
    assert r.items[0].text == EXPS[0].description           # 違規條退回原文
    assert "1200" in r.items[1].text                        # 合規條保留改寫


def test_halfwidth_period_normalized_to_fullwidth():
    """中文句尾半形句點自動轉全形;英文結尾不動。"""
    good = json.dumps({"items": [
        {"text": "以 SQL 與 Excel 產出週報,支援業務決策."},
        {"text": "經營社團 IG 累積 1200 追蹤."}]}, ensure_ascii=False)
    r = customize(JOB, EXPS, normalizer=NORM, llm=FakeLLM(good))
    assert r.items[0].text.endswith("。") and r.items[1].text.endswith("。")
