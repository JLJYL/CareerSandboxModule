"""B2 職缺適配管線(成員 B)。
流程:輪廓(正規化) → 逐職缺 Scorer 計分(requiredSkills 覆蓋 + JD 全文語意) → 排序組裝。
鐵律:分數與差集只認 Scorer;styleTag 用確定性規則從技能組成推導,不靠 LLM。

職缺來源:get_job() 依序查 CareerSandboxDB.jobs(後端組的 104 爬蟲資料)、
CareerSandboxDB.job_targets(使用者自行貼 JD 建立的求職目標),都查不到才退回
fixtures/jobs/jobs_v1.json。load_jobs()/fit_all() 仍只讀 fixtures,既有測試不受影響。
"""
from app.config import settings  # noqa: F401  (ensures .env is loaded before any DB lookup)

import json
import os
from pathlib import Path

from bson import ObjectId
from bson.errors import InvalidId

from app.schemas.api import ExperienceIn, JobFitOut
from app.schemas.domain import JobRequirement, UserProfile

_JOBS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "jobs" / "jobs_v1.json"

# 選法:萬用辦公三件套(Excel/Word/PPT/Outlook)不投票——它們在新鮮人職缺無處不在,
# 沒有鑑別力;調性由「特色技能」多數決,毫無特色者落「文書務實型」預設。
_DATA_KW = ("SQL", "Python", "統計", "資料", "數據", "分析", "程式", "Git", "ETL", "AI", "機器學習")
_PEOPLE_KW = ("溝通", "銷售", "服務", "接待", "客戶", "團隊", "協調", "解說", "話術", "客服")
_CREATIVE_KW = ("行銷", "企劃", "社群", "品牌", "文案", "編輯", "設計", "Photoshop", "Illustrator")


def load_jobs(path: Path = _JOBS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# DB-backed job lookup (backend team's collections)
# ---------------------------------------------------------------------------

_mongo_client = None


def _db():
    """Lazy pymongo handle to CareerSandboxDB.
    Returns None when MONGODB_URI is not configured so callers fall back to fixtures."""
    global _mongo_client
    uri = os.getenv("MONGODB_URI")
    if not uri:
        return None
    if _mongo_client is None:
        from pymongo import MongoClient
        _mongo_client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    return _mongo_client[os.getenv("MONGODB_DB", "CareerSandboxDB")]


def _from_db_doc(doc: dict) -> dict:
    """Map a crawled 104 job document (collection `jobs`) to the pipeline shape.

    Field mapping:
      jobId          <- str(_id)
      title/company  <- same name
      requiredSkills <- same name (often empty in crawled data)
      jd             <- description + conditionOther (requirements live in conditionOther)
      tags           <- jobCategory (fixtures' tags are job categories, not perks)
      salary         <- salaryRaw, else "low-high", else 面議
      deadline       <- not crawled; fixed 長期招募
    """
    jd = "\n".join(p for p in (doc.get("description"), doc.get("conditionOther")) if p)
    # salaryRaw is a string on 104 / taiwanjobs but a dict on cake
    salary = doc.get("salaryRaw")
    if isinstance(salary, dict):
        unit = "時薪" if salary.get("type") == "per_hour" else "月薪"
        rng = "~".join(str(v) for v in (salary.get("min"), salary.get("max")) if v)
        salary = f"{unit} {rng}" if rng else None
    if not salary and (doc.get("salaryLow") or doc.get("salaryHigh")):
        salary = f"{doc.get('salaryLow') or ''}-{doc.get('salaryHigh') or ''}"
    return {
        "jobId": str(doc["_id"]),
        "title": doc.get("title", ""),
        "company": doc.get("company", ""),
        "tags": doc.get("jobCategory") or [],
        "salary": salary or "面議",
        "deadline": "長期招募",
        "requiredSkills": doc.get("requiredSkills") or [],
        "jd": jd,
        "sourceUrl": doc.get("url", ""),
    }


def _from_target_doc(doc: dict) -> dict:
    """Map a user-created JobTarget (collection `job_targets`: pasted JD, no crawled
    source) to the pipeline shape. jdKeywords, if already extracted, double as
    requiredSkills so coverage scoring has something to work with."""
    return {
        "jobId": str(doc["_id"]),
        "title": doc.get("title", ""),
        "company": doc.get("company", ""),
        "tags": [],
        "salary": "面議",
        "deadline": "長期招募",
        "requiredSkills": doc.get("jdKeywords") or [],
        "jd": doc.get("jdSnapshot", ""),
        "sourceUrl": "",
    }


def _object_id(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def get_job(job_id: str) -> dict | None:
    """Resolve one job by id.

    Order:
      1. `jobs` by _id
      2. `jobs` by sourceId (accepts the legacy `fit_<sourceId>` form)
      3. `job_targets` by _id (user-created target with a pasted JD)
      4. fixtures

    The returned jobId always echoes the id the caller used (contract: jobId in == jobId out).
    Any DB failure (no URI, unreachable) silently falls through to fixtures."""
    try:
        db = _db()
    except Exception:
        db = None
    if db is not None:
        try:
            oid = _object_id(job_id)
            doc = db["jobs"].find_one({"_id": oid}) if oid is not None else None
            if doc is None:
                source_id = job_id[4:] if job_id.startswith("fit_") else job_id
                doc = db["jobs"].find_one({"sourceId": source_id})
            if doc is not None:
                job = _from_db_doc(doc)
                job["jobId"] = job_id
                return job

            if oid is not None:
                tdoc = db["job_targets"].find_one({"_id": oid})
                if tdoc is not None:
                    # A target picked from the crawled list carries the job's sourceId:
                    # prefer the full crawled record (conditionOther, requiredSkills) over
                    # the snapshot. A typed-in target has no sourceId and uses jdSnapshot.
                    src = tdoc.get("jobId") or ""
                    jdoc = db["jobs"].find_one({"sourceId": src}) if src else None
                    job = _from_db_doc(jdoc) if jdoc is not None else _from_target_doc(tdoc)
                    if not job.get("requiredSkills") and tdoc.get("jdKeywords"):
                        job["requiredSkills"] = tdoc["jdKeywords"]
                    job["jobId"] = job_id
                    return job
        except Exception:
            pass  # DB unreachable: fall through to fixtures
    return next((j for j in load_jobs() if j["jobId"] == job_id), None)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def style_tag(required_skills: list[str], jd: str = "") -> str:
    """確定性風格標籤:技能欄+JD 全文一起看的多數決,平手歸均衡。
    (104 的結構化技能欄清一色 Office 三寶,溝通/數據訊號多半藏在 JD 內文)"""
    text = " ".join(required_skills) + " " + jd
    scores = {
        "數據導向型": sum(1 for k in _DATA_KW if k in text),
        "溝通導向型": sum(1 for k in _PEOPLE_KW if k in text),
        "創意行銷型": sum(1 for k in _CREATIVE_KW if k in text),
    }
    best = max(scores.values())
    winners = [k for k, v in scores.items() if v == best]
    if best == 0:
        return "文書務實型"                      # 只有萬用技能 → 務實預設
    return winners[0] if len(winners) == 1 else "均衡發展型"


def fit_one(profile: UserProfile, job: dict, scorer) -> JobFitOut:
    fit = scorer.score(profile, JobRequirement(
        job_id=job["jobId"], title=job["title"],
        required_skills=job.get("requiredSkills", []),
        jd_text=job.get("jd", "")))
    return JobFitOut(
        jobId=job["jobId"], title=job["title"], company=job["company"],
        tags=job.get("tags", []), salary=job["salary"], deadline=job["deadline"],
        matchScore=fit.match_score, styleTag=style_tag(job.get("requiredSkills", []), job.get("jd", "")),
        requiredSkills=job.get("requiredSkills", []),
        scoreBasis=getattr(fit, "score_basis", ""))   # set by A's scorer branch; "" until merged


def fit_all(profile: UserProfile, scorer, jobs: list[dict] | None = None) -> list[JobFitOut]:
    jobs = jobs if jobs is not None else load_jobs()
    out = [fit_one(profile, j, scorer) for j in jobs]
    out.sort(key=lambda j: -j.matchScore)     # 最適配的排最前,前端清單即戰力
    return out