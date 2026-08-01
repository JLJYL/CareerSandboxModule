"""B2 職缺適配管線(成員 B)。
流程:輪廓(正規化) → 逐職缺 Scorer 計分(requiredSkills 覆蓋 + JD 全文語意) → 排序組裝。
鐵律:分數與差集只認 Scorer;styleTag 用確定性規則從技能組成推導,不靠 LLM。
"""
import json
from pathlib import Path

from app.schemas.api import ExperienceIn, JobFitOut
from app.schemas.domain import JobRequirement, UserProfile

_JOBS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "jobs" / "jobs_v1.json"

# 選舉法:萬用辦公三件套(Excel/Word/PPT/Outlook)不投票——它們在新鮮人職缺無處不在,
# 沒有鑑別力;調性由「特色技能」多數決,毫無特色者落「文書務實型」預設。
_DATA_KW = ("SQL", "Python", "統計", "資料", "數據", "分析", "程式", "Git", "ETL", "AI", "機器學習")
_PEOPLE_KW = ("溝通", "銷售", "服務", "接待", "客戶", "團隊", "協調", "解說", "話術", "客服")
_CREATIVE_KW = ("行銷", "企劃", "社群", "品牌", "文案", "編輯", "設計", "Photoshop", "Illustrator")


def load_jobs(path: Path = _JOBS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


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
        requiredSkills=job.get("requiredSkills", []))


def fit_all(profile: UserProfile, scorer, jobs: list[dict] | None = None) -> list[JobFitOut]:
    jobs = jobs if jobs is not None else load_jobs()
    out = [fit_one(profile, j, scorer) for j in jobs]
    out.sort(key=lambda j: -j.matchScore)     # 最適配的排最前,前端清單即戰力
    return out
