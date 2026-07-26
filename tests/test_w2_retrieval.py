"""W2 驗收測試（成員 A）：ChromaRetriever／VocabNormalizer 第二段／matchScore v1。
04 文件的 W2 自檢在此變成可執行合約：檢索回傳合理、同輸入分數不漂移。
全程用 FakeEmbedding／StubEmbedding——CI 不需要模型；真 bge-m3 的煙霧測試
在本機跑 tools/build_kb_index.py --real。
"""
import json

import pytest

from app.pipeline.normalize import VocabNormalizer
from app.pipeline.scorer import WeightedScorer
from app.pipeline.vocab import VOCAB_PATH
from app.providers.embeddings import EMBEDDING_DIM, FakeEmbedding
from app.retrieval.vector_retriever import DEFAULT_SEEDS, VectorRetriever
from app.schemas.domain import JobRequirement, RetrievedChunk, SkillEvidence, UserProfile


def unit(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


class StubEmbedding:
    """測試用可控向量：指定字串給指定向量，其餘退回 FakeEmbedding。"""

    def __init__(self, mapping: dict[str, list[float]]):
        self._map = mapping
        self._fallback = FakeEmbedding()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._map.get(t) or self._fallback.embed([t])[0] for t in texts]


# ---------------------------------------------------------------- VectorRetriever

@pytest.fixture(scope="module")
def retriever() -> VectorRetriever:
    return VectorRetriever(FakeEmbedding())


def test_retriever_ingests_all_kb_files(retriever):
    expected = sum(len(json.loads(p.read_text(encoding="utf-8"))) for p in DEFAULT_SEEDS)
    assert retriever.count() == expected


def test_retriever_search_shape_and_order(retriever):
    out = retriever.search("資料分析 職涯 SQL", k=5)
    assert len(out) == 5
    assert all(isinstance(c, RetrievedChunk) for c in out)
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)


def test_retriever_type_filter(retriever):
    out = retriever.search("職涯 轉職", k=5, where={"type": "article"})
    assert out and all(c.entry.type == "article" for c in out)


def test_retriever_deterministic(retriever):
    a = [c.entry.id for c in retriever.search("產品經理 需要什麼技能", k=5)]
    b = [c.entry.id for c in retriever.search("產品經理 需要什麼技能", k=5)]
    assert a == b


# ---------------------------------------------------------------- Normalizer 第二段

def test_normalizer_stage1_exact():
    n = VocabNormalizer()                    # 無 embedding：只走第一段
    assert n.normalize("MySQL").name_zh == "SQL"
    assert n.normalize(" 數據分析 ").name_zh == "資料分析"


def test_normalizer_stage2_nearest_neighbor():
    stub = StubEmbedding({"資料視覺化": unit(0), "數據儀表板": unit(0)})
    n = VocabNormalizer(embedding=stub, threshold=0.62)
    hit = n.normalize("數據儀表板")          # 第一段必 miss，第二段餘弦=1.0
    assert hit is not None and hit.name_zh == "資料視覺化"


def test_normalizer_below_threshold_goes_residual():
    stub = StubEmbedding({"量子烹飪": unit(1)})   # 與所有表面形近乎正交
    n = VocabNormalizer(embedding=stub, threshold=0.62)
    assert n.normalize("量子烹飪") is None
    last = n.residuals()[-1]
    assert last["raw"] == "量子烹飪" and last["sim"] < 0.62 and last["best_id"]


# ---------------------------------------------------------------- Scorer

@pytest.fixture(scope="module")
def normalizer() -> VocabNormalizer:
    return VocabNormalizer()


def _profile(normalizer, *skill_names, raw_tags=(), weight=1.0):
    evid = [SkillEvidence(skill_id=normalizer.normalize(s).skill_id, weight=weight)
            for s in skill_names]
    return UserProfile(user_id="dev_user_001", skills=evid, raw_tags=list(raw_tags))


def test_scorer_deterministic(normalizer):
    scorer = WeightedScorer(normalizer, embedding=FakeEmbedding())
    p = _profile(normalizer, "SQL", "Excel")
    j = JobRequirement(job_id="j1", title="資料分析師",
                       required_skills=["SQL", "Python"],
                       jd_text="負責 SQL 報表、資料分析與儀表板維護")
    assert scorer.score(p, j) == scorer.score(p, j)


def test_scorer_monotonic_when_gap_filled(normalizer):
    scorer = WeightedScorer(normalizer, embedding=FakeEmbedding())
    j = JobRequirement(job_id="j1", title="資料分析師",
                       required_skills=["SQL", "Python"], jd_text="SQL 與 Python 資料分析")
    before = scorer.score(_profile(normalizer, "SQL"), j)
    after = scorer.score(_profile(normalizer, "SQL", "Python"), j)
    assert after.match_score >= before.match_score
    assert "Python" in after.covered_skills and "Python" in before.missing_skills


def test_scorer_coverage_only_without_embedding(normalizer):
    scorer = WeightedScorer(normalizer, embedding=None)
    j = JobRequirement(job_id="j1", title="BI 工程師", required_skills=["SQL", "Python"])
    r = scorer.score(_profile(normalizer, "SQL"), j)
    assert r.match_score == 50 and r.covered_skills == ["SQL"] and r.missing_skills == ["Python"]


def test_scorer_raw_tag_discount(normalizer):
    scorer = WeightedScorer(normalizer, embedding=None)
    j = JobRequirement(job_id="j1", title="神祕職缺", required_skills=["獨門祕技X"])
    r = scorer.score(_profile(normalizer, raw_tags=["獨門祕技X"]), j)
    assert r.match_score == 60 and r.covered_skills == ["獨門祕技X"]


def test_scorer_semantic_fallback_when_no_required(normalizer):
    scorer = WeightedScorer(normalizer, embedding=FakeEmbedding())
    j = JobRequirement(job_id="j1", title="數位行銷專員",
                       required_skills=[], jd_text="社群經營、內容行銷、成效分析")
    r = scorer.score(_profile(normalizer, "內容創作", "資料分析"), j)
    assert 0 <= r.match_score <= 100
    assert r.covered_skills == [] and r.missing_skills == []
