"""六支端點（骨架階段：回傳 golden JSON，並強制通過凍結 schema 驗證後才出門）。

替換節奏：
  第 1 週  /resume/master/generate → 接真擷取管線（成員 B）
  第 2 週  /career/recommend、/jobs/* → 接真檢索與評分（A 供料、B 接線）
  第 3 週  /resume/customize → 真客製；/resume/overview 行有餘力
骨架期的價值：前端與測試從 Day 2 起就能對著「正確形狀」開發。

職缺來源（後端組接線後）：/jobs/{id}/fit、/resume/customize、/resume/customize/full
的 jobId 改經 jobs_fit.get_job() 解析——先查 CareerSandboxDB.jobs（_id 或 sourceId），
查不到再退回 fixtures，既有測試與舊版 fit_<sourceId> 格式不受影響。
/jobs/fit-all 仍走 fixtures（對整批爬蟲職缺計分成本過高，另案處理）。
"""
import json
import logging
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
    CustomizeFullRequest, CustomizeFullResponse, CustomizeRequest, CustomizeResponse,
    DraftExperience,
    JobsFitRequest, JobFitOut, JobsFitAllResponse,
    MasterGenerateRequest, MasterGenerateResponse,
    OverviewRequest, OverviewResponse,
    ReinforceRequest, ReinforceResponse,
)

router = APIRouter()

_GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "golden"


def _golden(name: str) -> dict:
    return json.loads((_GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


_log = logging.getLogger("careersandbox.ai")

_NORMALIZER: VocabNormalizer | None = None
_EMBEDDING = None            # shared bge-m3 instance (normalizer + scorer); None = degraded
_EMBEDDING_ERROR: str | None = None   # why the embedding failed to load, for /health
_EMBEDDING_TRIED = False


def _get_embedding():
    """Lazy singleton for bge-m3. Failing to load is a silent degradation (alias-only
    normalizer, coverage-only scorer), which cost the backend a day to diagnose on
    2026-10-21 — so the failure is now logged loudly once and exposed on /health."""
    global _EMBEDDING, _EMBEDDING_ERROR, _EMBEDDING_TRIED
    if _EMBEDDING_TRIED:
        return _EMBEDDING
    _EMBEDDING_TRIED = True
    try:
        from app.providers.embeddings import BgeM3Embedding
        _EMBEDDING = BgeM3Embedding()
        _log.info("bge-m3 embedding loaded; normalizer and scorer run with the semantic leg.")
    except Exception as e:  # noqa: BLE001 - any failure degrades, but must be visible
        _EMBEDDING = None
        _EMBEDDING_ERROR = f"{type(e).__name__}: {e}"
        _log.warning(
            "bge-m3 embedding NOT loaded (%s). Running DEGRADED: normalizer is alias-only, "
            "scorer is coverage-only, semantic similarity is skipped. "
            "Check torch/transformers and the HF cache (snapshots/*/pytorch_model.bin must be ~2.2GB).",
            _EMBEDDING_ERROR)
    return _EMBEDDING


def _get_normalizer() -> VocabNormalizer:
    """懶載單例:有 torch+模型 → 三段全開(alias→向量最近鄰→殘留);
    沒有(CI、乾淨環境)→ alias-only 降級——同一個介面,能力降級不缺席。"""
    global _NORMALIZER
    if _NORMALIZER is None:
        emb = _get_embedding()
        _NORMALIZER = VocabNormalizer(embedding=emb) if emb is not None else VocabNormalizer()
    return _NORMALIZER


_SCORER = None


def _get_scorer():
    """懶載單例:有模型 → 覆蓋+語意雙腿;沒有(CI)→ 覆蓋率單腿,仍為確定性分數。"""
    global _SCORER
    if _SCORER is None:
        from app.pipeline.scorer import WeightedScorer
        norm = _get_normalizer()
        emb = _get_embedding()
        _SCORER = WeightedScorer(norm, embedding=emb) if emb is not None else WeightedScorer(norm)
    return _SCORER


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
    emb = _get_embedding()          # shared instance: never load the 2.2GB model twice
    if emb is None:
        return None
    try:
        from app.retrieval.vector_retriever import VectorRetriever
        norm = _get_normalizer()
        return (VectorRetriever(embedding=emb,
                                persist_path=Path("data/kb_index.json")),
                _get_scorer(), norm)
    except Exception as e:  # noqa: BLE001
        _log.warning("career/recommend retriever unavailable (%s); endpoint returns golden.", e)
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
    from app.pipeline.jobs_fit import fit_all
    from app.pipeline.recommend import profile_from_experiences
    normalizer = _get_normalizer()
    profile = profile_from_experiences(req.userId, req.experiences, normalizer)
    return JobsFitAllResponse(jobs=fit_all(profile, _get_scorer()))


@router.post("/jobs/{job_id}/fit", response_model=JobFitOut,
             responses={404: {"description": "jobId 不存在,統一錯誤格式"}})
def job_fit(job_id: str, req: JobsFitRequest):
    from app.pipeline.jobs_fit import fit_one, get_job
    from app.pipeline.recommend import profile_from_experiences
    job = get_job(job_id)                 # DB (_id / sourceId) → fixtures
    if job is None:
        return _error(404, "job_not_found", f"查無職缺 {job_id}")
    normalizer = _get_normalizer()
    profile = profile_from_experiences(req.userId, req.experiences, normalizer)
    return fit_one(profile, job, _get_scorer())


@router.post("/resume/customize", response_model=CustomizeResponse,
             responses={404: {"description": "jobId 不存在,統一錯誤格式"}})
def resume_customize(req: CustomizeRequest):
    from app.pipeline.customize import customize
    from app.pipeline.jobs_fit import get_job
    job = get_job(req.jobId)              # DB (_id / sourceId) → fixtures
    if job is None:
        return _error(404, "job_not_found", f"查無職缺 {req.jobId}")
    try:
        llm = OpenAICompatibleLLM()      # 生成任務,吃全域預設模型
    except LLMUnavailable:
        llm = None                        # 無金鑰 → 確定性輸出(原文+標記)照樣出貨
    return customize(job, req.experiences, normalizer=_get_normalizer(), llm=llm)


@router.post("/resume/customize/full", response_model=CustomizeFullResponse,
             responses={404: {"description": "jobId 不存在,統一錯誤格式"}})
def resume_customize_full(req: CustomizeFullRequest):
    """契約 v1:回傳組裝完成、依顯示順序排列的客製履歷,前端由上往下渲染即可。"""
    from app.pipeline.jobs_fit import get_job
    from app.pipeline.resume_full import customize_full
    job = get_job(req.jobId)              # DB (_id / sourceId) → fixtures
    if job is None:
        return _error(404, "job_not_found", f"查無職缺 {req.jobId}")
    try:
        llm = OpenAICompatibleLLM()
    except LLMUnavailable:
        llm = None
    return customize_full(job, req.profile, req.experiences, normalizer=_get_normalizer(), llm=llm)


@router.post("/skills/reinforce", response_model=ReinforceResponse)
def skills_reinforce(req: ReinforceRequest) -> ReinforceResponse:
    """技能補強:對 missingSkills 配對課程與競賽。配對確定性,LLM 只寫 note。
    無金鑰 → note 全空照樣回 200(bge-m3 只在正規化器第二段,_get_normalizer 已處理)。"""
    from app.pipeline.reinforce import reinforce
    try:
        llm = OpenAICompatibleLLM()
    except LLMUnavailable:
        llm = None
    return reinforce(req.missingSkills, normalizer=_get_normalizer(),
                     school=req.school, llm=llm)


@router.post("/resume/overview", response_model=OverviewResponse)
def resume_overview(req: OverviewRequest) -> OverviewResponse:
    # TODO(第 3 週, 行有餘力; 合約為 PROPOSAL 待怡君回簽)
    return OverviewResponse.model_validate(_golden("resume_overview"))


@router.get("/health")
def health(deep: bool = False) -> dict:
    """Liveness plus the embedding state. `embedding` is true/false once the model has
    been tried, null if nothing has triggered the lazy load yet; `?deep=1` forces the
    load (first call may take 10-30 s) so a deploy check can confirm the semantic leg."""
    if deep:
        _get_embedding()
    loaded = None if not _EMBEDDING_TRIED else (_EMBEDDING is not None)
    out: dict = {"status": "ok", "embedding": loaded}
    if _EMBEDDING_ERROR:
        out["embeddingError"] = _EMBEDDING_ERROR
    return out