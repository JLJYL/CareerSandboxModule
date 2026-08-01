"""六支端點（骨架階段：回傳 golden JSON，並強制通過凍結 schema 驗證後才出門）。

替換節奏：
  第 1 週  /resume/master/generate → 接真擷取管線（成員 B）
  第 2 週  /career/recommend、/jobs/* → 接真檢索與評分（A 供料、B 接線）
  第 3 週  /resume/customize → 真客製；/resume/overview 行有餘力
骨架期的價值：前端與測試從 Day 2 起就能對著「正確形狀」開發。
"""
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.pipeline.extraction import ExtractionError, LlmExtractor
from app.pipeline.normalize import VocabNormalizer
from app.pipeline.profile import aggregate_display_skills, build_profile
from app.providers.llm import LLMUnavailable, OpenAICompatibleLLM
from app.schemas.api import (
    CareerRecommendRequest, CareerRecommendResponse,
    CustomizeRequest, CustomizeResponse,
    DraftExperience,
    JobsFitRequest, JobFitOut, JobsFitAllResponse,
    MasterGenerateRequest, MasterGenerateResponse,
    OverviewRequest, OverviewResponse,
)

router = APIRouter()

_GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "golden"


def _golden(name: str) -> dict:
    return json.loads((_GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


_NORMALIZER: VocabNormalizer | None = None


def _get_normalizer() -> VocabNormalizer:
    """懶載單例:有 torch+模型 → 三段全開(alias→向量最近鄰→殘留);
    沒有(CI、乾淨環境)→ alias-only 降級——同一個介面,能力降級不缺席。"""
    global _NORMALIZER
    if _NORMALIZER is None:
        try:
            from app.providers.embeddings import BgeM3Embedding
            _NORMALIZER = VocabNormalizer(embedding=BgeM3Embedding())
        except Exception:
            _NORMALIZER = VocabNormalizer()
    return _NORMALIZER


def _build_extractor() -> LlmExtractor | None:
    """LLM 有設定 → 真擷取;沒設定(本地無 .env、CI)→ None,端點退 golden。"""
    try:
        return LlmExtractor(OpenAICompatibleLLM(model=settings.llm_model_extract or None))
    except LLMUnavailable:
        return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


@router.post("/resume/master/generate", response_model=MasterGenerateResponse,
             responses={502: {"description": "LLM 或擷取失敗,統一錯誤格式"}})
def master_generate(req: MasterGenerateRequest):
    extractor = _build_extractor()
    if extractor is None:
        # golden 模式:讓前端/CI 在沒有金鑰時仍拿到正確形狀
        return MasterGenerateResponse.model_validate(_golden("resume_master_generate"))
    try:
        drafts = extractor.extract(req.narratives)
    except LLMUnavailable as e:
        return _error(502, "llm_unavailable", str(e))
    except ExtractionError as e:
        return _error(502, "extraction_failed", str(e))

    normalizer = _get_normalizer()          # W2:A 的正規化器正式上線
    profile = build_profile(req.userId, drafts, normalizer=normalizer)
    return MasterGenerateResponse(
        draftExperiences=[
            DraftExperience(
                id=f"e_ai_{i}", title=d.title, category=d.category,
                timeRange=d.time_range, description=d.description,
                tags=d.raw_skills, sourceQuote=d.source_quote,
                confidence=d.confidence,
            )
            for i, d in enumerate(drafts, 1)
        ],
        skills=aggregate_display_skills(profile, name_of=normalizer.display_name),
    )


def _build_reco_deps():
    """真檢索+真尺(要 torch+模型);建不起來(CI/乾淨機)→ None → 端點退 golden。"""
    try:
        from app.pipeline.scorer import WeightedScorer
        from app.providers.embeddings import BgeM3Embedding
        from app.retrieval.vector_retriever import VectorRetriever
        emb = BgeM3Embedding()
        norm = _get_normalizer()
        return (VectorRetriever(embedding=emb,
                                persist_path=Path("data/kb_index.json")),
                WeightedScorer(norm, embedding=emb), norm)
    except Exception:
        return None


@router.post("/career/recommend", response_model=CareerRecommendResponse)
def career_recommend(req: CareerRecommendRequest) -> CareerRecommendResponse:
    deps = _build_reco_deps()
    if deps is None:
        return CareerRecommendResponse.model_validate(_golden("career_recommend"))
    retriever, scorer, normalizer = deps
    try:
        llm = OpenAICompatibleLLM()          # 生成任務吃全域預設(建議 gpt-4o-mini)
    except LLMUnavailable:
        llm = None                            # 沒金鑰 → 純分數排序,C1 照樣出貨
    from app.pipeline.recommend import recommend
    recs = recommend(req.query, req.experiences, normalizer=normalizer,
                     retriever=retriever, scorer=scorer, llm=llm)
    return CareerRecommendResponse(recommendations=recs)


@router.post("/jobs/fit-all", response_model=JobsFitAllResponse)
def jobs_fit_all(req: JobsFitRequest) -> JobsFitAllResponse:
    # TODO(第 2 週): 對知識庫內每個職缺跑 Scorer
    return JobsFitAllResponse.model_validate(_golden("jobs_fit_all"))


@router.post("/jobs/{job_id}/fit", response_model=JobFitOut)
def job_fit(job_id: str, req: JobsFitRequest) -> JobFitOut:
    # TODO(第 2 週): 依 job_id 取 JD → Scorer → 回填真分數與差距
    return JobFitOut.model_validate(_golden("job_fit"))


@router.post("/resume/customize", response_model=CustomizeResponse)
def resume_customize(req: CustomizeRequest) -> CustomizeResponse:
    # TODO(第 3 週, 成員 B): 依 jobId 取 jdKeywords → 逐條經歷比對 → 證據約束改寫
    return CustomizeResponse.model_validate(_golden("resume_customize"))


@router.post("/resume/overview", response_model=OverviewResponse)
def resume_overview(req: OverviewRequest) -> OverviewResponse:
    # TODO(第 3 週, 行有餘力; 合約為 PROPOSAL 待怡君回簽)
    return OverviewResponse.model_validate(_golden("resume_overview"))


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
