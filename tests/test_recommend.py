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


def test_offtopic_chunks_filtered():
    """A 標註的民生新聞雜訊(offtopic=true)不得進入推薦流程。"""
    from app.pipeline.recommend import _usable_chunks
    noise = RetrievedChunk(score=0.9, entry=KBEntry(
        id="kb_noise", type="article", title="發票開獎", content="x", skills=[],
        metadata={"careerId": "pm", "offtopic": True, "sourceId": "s9"}))
    keep = RetrievedChunk(score=0.8, entry=KBEntry(
        id="kb_ok", type="article", title="正常文章", content="y", skills=[],
        metadata={"sourceId": "s1"}))
    assert [c.entry.id for c in _usable_chunks([noise, keep])] == ["kb_ok"]


def test_career_category_accepts_market_buckets():
    """合約變更回歸鎖:market 定案後 category 為開放字串,新桶名(人資等)不得再炸 500。"""
    from app.schemas.api import CareerRecOut
    card = CareerRecOut(id="hr", title="人力資源", subtitleEn="HR Specialist",
                        shortSubtitle="人資 · 33-40k", salary="33-40k", openings="1,022",
                        matchScore=41, missingSkills=[], category="人資",
                        isAcademic=False, academicNote="")
    assert card.category == "人資"


def test_rank_prompt_shows_covered_skills():
    """排序官必須看得到命中訊號——家族平分局的關鍵證據。"""
    from app.prompts.recommend import build_rank_prompt
    cand = [{"id": "admin", "title": "行政／總務", "matchScore": 40,
             "covered": ["Excel", "Word"], "missing": ["Outlook"], "snippets": []}]
    p = build_rank_prompt("我喜歡整理文件", ["Excel", "Word"], cand)
    assert "命中:Excel、Word" in p and "尚缺:Outlook" in p


# ---- 2026-10-22: profile from experiences without tags ----------------------------------

def test_profile_without_tags_scans_description_and_fills_narrative():
    """Issue 5 (backend report): chat-created experiences carry no tags. The profile must
    still get skills (vocabulary scan of title + description) and a narrative for the
    semantic leg, so such users do not score 0 against every job."""
    from app.pipeline.normalize import VocabNormalizer
    from app.pipeline.recommend import profile_from_experiences
    from app.schemas.api import ExperienceIn
    norm = VocabNormalizer()
    exps = [ExperienceIn(id="e1", title="電商公司資料分析實習", category="工作", timeRange="",
                         description="協助業務團隊整理銷售數據。運用 SQL + Excel 穩定產出業務週報。",
                         tags=[])]
    p = profile_from_experiences("u", exps, norm)
    names = {norm.display_name(s.skill_id) for s in p.skills}
    assert {"SQL", "Excel"} <= names
    assert all(ev.startswith("scan:") for s in p.skills for ev in s.evidence)
    assert "業務週報" in p.narrative and "電商公司資料分析實習" in p.narrative


def test_profile_with_tags_does_not_scan():
    """Tagged experiences keep the original behaviour: tags are the only skill source."""
    from app.pipeline.normalize import VocabNormalizer
    from app.pipeline.recommend import profile_from_experiences
    from app.schemas.api import ExperienceIn
    norm = VocabNormalizer()
    exps = [ExperienceIn(id="e1", title="實習", category="工作", timeRange="",
                         description="運用 SQL + Excel 產出週報。", tags=["Python"])]
    p = profile_from_experiences("u", exps, norm)
    names = {norm.display_name(s.skill_id) for s in p.skills}
    assert "SQL" not in names and "Excel" not in names


def test_returns_at_most_five_careers():
    """2026-10-24: the cap moved from 3 to 5. Seven careers all pass the score threshold;
    the service must return exactly five, in score order when no LLM is available."""
    catalog = [{"id": f"c{i}", "title": f"職涯{i}", "subtitleEn": f"C{i}", "category": "數據",
                "isAcademic": False, "salary": "40-65k", "openings": "10",
                "requiredSkills": ["SQL"] if i % 2 else ["SQL", "Excel"]} for i in range(7)]
    recs = recommend("我喜歡整理數據", EXPS, normalizer=NORM,
                     retriever=StubRetriever(cids=tuple(c["id"] for c in catalog)),
                     scorer=SCORER, llm=None, catalog=catalog)
    assert len(recs) == 5
    scores = [r.matchScore for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_fewer_than_five_when_fewer_pass_threshold():
    """The cap is a maximum, not a quota: only careers scoring >= 30 are returned."""
    recs = recommend("我想做產品", EXPS, normalizer=NORM, retriever=StubRetriever(),
                     scorer=SCORER, llm=None, catalog=CATALOG)
    assert 0 < len(recs) < 5
    

def test_career_without_snippets_keeps_semantic_leg():
    """2026-10-26: a marketing user got an empty list because careers with no retrieved KB
    snippet were scored on coverage alone (2 of 8 skills = 25 < 30). The catalog entry must
    stand in as the career text so the semantic leg still runs."""
    from app.pipeline.recommend import career_text
    from app.providers.embeddings import FakeEmbedding
    from app.schemas.domain import JobRequirement
    career = {"id": "content_creator", "title": "數位內容製作", "subtitleEn": "Content Creator",
              "requiredSkills": ["Adobe Photoshop", "Excel", "Premiere", "短影音"]}
    text = career_text(career, [])
    assert "數位內容製作" in text and "Premiere" in text
    assert career_text(career, [{"text": "摘錄A", "url": ""}, {"text": "摘錄B", "url": ""}]) == "摘錄A 摘錄B"
    profile = __import__("app.pipeline.recommend", fromlist=["x"]).profile_from_experiences(
        "u", EXPS, NORM)
    fit = WeightedScorer(NORM, embedding=FakeEmbedding()).score(profile, JobRequirement(
        job_id="content_creator", title=career["title"], required_skills=career["requiredSkills"],
        jd_text=text))
    assert fit.score_basis == "both"
    
    

def test_scan_ascii_aliases_need_word_boundaries():
    """2026-10-26 review of /jobs/extract-skills: its no-key fallback stores scan results, and
    substring matching misfired on ordinary English words inside JDs."""
    from app.pipeline.recommend import scan_skills_in_text
    def names(t):
        return {s.name_zh for s in scan_skills_in_text(t)}
    assert "機器學習" not in names("履歷請寄 email 至 hr@abc.com")
    assert "Git" not in names("digital marketing")
    assert "Excel" not in names("excellent communication skills")
    assert "Word" not in names("keyword research and password policy")
    assert "MES" not in names("work times are flexible")
    assert {"Excel", "Git", "SQL"} <= names("熟悉 Excel、Git 與 SQL")   # standalone and next to CJK
    assert "Adobe Photoshop" in names("熟悉Photoshop")
    assert "機器學習" in names("具 machine learning 專案經驗")             # multi-word alias with spaces