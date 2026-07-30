"""C1 推薦管線測試——全假零件(alias 正規化+stub 檢索+FakeLLM),免錢免模型。"""
import json

from app.pipeline.normalize import VocabNormalizer
from app.pipeline.recommend import recommend
from app.pipeline.scorer import WeightedScorer
from app.providers.llm import FakeLLM
from app.schemas.api import CareerRecOut, ExperienceIn
from app.schemas.domain import KBEntry, RetrievedChunk

NORM = VocabNormalizer()                      # alias-only 模式
SCORER = WeightedScorer(NORM)                 # 覆蓋率單腿模式

CATALOG = [
    {"id": "data_analyst", "title": "資料分析師", "subtitleEn": "Data Analyst",
     "category": "數據", "isAcademic": False, "salary": "40-65k", "openings": "10",
     "requiredSkills": ["SQL", "Python", "統計"]},
    {"id": "pm", "title": "產品企劃／PM", "subtitleEn": "Product Planner",
     "category": "產品", "isAcademic": False, "salary": "34-45k", "openings": "172",
     "requiredSkills": ["使用者訪談", "PRD 撰寫"]},
]

EXPS = [ExperienceIn(id="e1", title="電商實習", category="工作",
                     timeRange="暑假", description="d", tags=["SQL", "Excel"])]


class StubRetriever:
    def __init__(self, cids=("data_analyst", "pm")):
        self._cids = cids

    def search(self, query, k=5):
        return [RetrievedChunk(score=0.9, entry=KBEntry(
            id=f"kb_{c}", type="job_skill", title=c, content=f"{c} 的知識",
            skills=[], metadata={"careerId": c, "url": "https://x/y"}))
            for c in self._cids]


def test_happy_path_llm_ranked_and_contract_shaped():
    llm = FakeLLM(json.dumps({"order": ["pm", "data_analyst"], "notes": {}}))
    recs = recommend("我想做產品", EXPS, normalizer=NORM, retriever=StubRetriever(),
                     scorer=SCORER, llm=llm, catalog=CATALOG, min_score=0)
    assert [r.id for r in recs][:2] == ["pm", "data_analyst"]   # LLM 的排序被採用
    assert recs[0].shortSubtitle == "產品 · 34-45k"
    CareerRecOut.model_validate(recs[0].model_dump())


def test_llm_garbage_falls_back_to_score_order():
    recs = recommend("我喜歡整理數據", EXPS, normalizer=NORM,
                     retriever=StubRetriever(), scorer=SCORER,
                     llm=FakeLLM("這不是 JSON"), catalog=CATALOG, min_score=0)
    assert recs and recs[0].id == "data_analyst"     # SQL 命中 → 分數排序勝出
    assert all(0 <= r.matchScore <= 100 for r in recs)


def test_graceful_exit_when_nothing_scores():
    recs = recommend("我想當太空人", [], normalizer=NORM, retriever=StubRetriever(()),
                     scorer=SCORER, llm=None, catalog=CATALOG, min_score=99)
    assert recs == []                                 # 寧可不推,不硬編


def test_zero_evidence_career_never_ships():
    """零證據不參賽:無技能骨架且無摘錄的職涯,不得靠中性分登頂誤導使用者。"""
    ghost = {"id": "ghost", "title": "幽靈職涯", "subtitleEn": "Ghost",
             "category": "數據", "isAcademic": False, "salary": "依市場",
             "openings": "—", "requiredSkills": []}
    recs = recommend("我喜歡整理數據", EXPS, normalizer=NORM,
                     retriever=StubRetriever(), scorer=SCORER,
                     llm=None, catalog=CATALOG + [ghost], min_score=0)
    assert "ghost" not in [r.id for r in recs]
    assert recs and recs[0].missingSkills != []      # 出貨的卡都有真差集
