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

from app.schemas.api import (
    CareerRecommendRequest, CareerRecommendResponse,
    CustomizeRequest, CustomizeResponse,
    JobsFitRequest, JobFitOut, JobsFitAllResponse,
    MasterGenerateRequest, MasterGenerateResponse,
    OverviewRequest, OverviewResponse,
)

router = APIRouter()

_GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "golden"


def _golden(name: str) -> dict:
    return json.loads((_GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


@router.post("/resume/master/generate", response_model=MasterGenerateResponse)
def master_generate(req: MasterGenerateRequest) -> MasterGenerateResponse:
    # TODO(第 1 週, 成員 B): extractor.extract(req.narratives) → normalize → 組裝
    return MasterGenerateResponse.model_validate(_golden("resume_master_generate"))


@router.post("/career/recommend", response_model=CareerRecommendResponse)
def career_recommend(req: CareerRecommendRequest) -> CareerRecommendResponse:
    # TODO(第 2 週, 成員 B): retriever.search(req.query) → LLM 生成 → 差集用 Scorer
    return CareerRecommendResponse.model_validate(_golden("career_recommend"))


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
