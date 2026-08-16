"""客製化完整履歷組裝層(契約 v1)——純確定性,免 LLM 免模型。每條規則一鎖。"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.normalize import VocabNormalizer
from app.pipeline.resume_full import build_edu_line, customize_full, order_experiences, split_skills
from app.schemas.api import CustomizedItemOut, ExperienceIn, LanguageIn, ProfileIn

NORM = VocabNormalizer()
_FIRST_JOB_ID = json.loads((Path(__file__).resolve().parents[1] / "fixtures/jobs/jobs_v1.json")
                           .read_text(encoding="utf-8"))[0]["jobId"]      # 同煙霧測試慣例,不寫死 id
JOB = {"jobId": "fit_x", "title": "數據助理", "requiredSkills": ["SQL", "Excel", "報表彙整與管理"],
       "jd": "使用 SQL 與 Excel 產出報表,支援資料分析。"}
EXPS = [
    ExperienceIn(id="e1", title="系學會行銷組長", category="社團", timeRange="2024.09 - 2025.06",
                 description="把社團 IG 從零做到 1200 追蹤", tags=["社群媒體經營"]),
    ExperienceIn(id="e2", title="電商實習", category="工作", timeRange="2025.07 - 2025.09",
                 description="每週用 SQL 跟 Excel 拉數據做週報給業務", tags=["SQL", "Excel"]),
    ExperienceIn(id="e3", title="商業個案競賽", category="競賽", timeRange="2025.03",
                 description="四人組隊分析餐飲品牌轉型,獲佳作", tags=["簡報製作"]),
]
PROFILE = ProfileIn(name="Alex_test", school="NSYSU", department="MIS", year="大三",
                    email="test@gmail.com", phone="", linkedin="alex-lin", github="", portfolio="",
                    bio="資管系大三,想往 PM 發展。哈哈",
                    skillsHave=["數據分析", "SQL", "報表", "Excel", "專案管理"],
                    languages=[LanguageIn(language="英文", level="TOEIC 875")])


def test_experiences_ordered_strong_first_by_hits_then_weak_in_master_order():
    """契約規則 4:強化在前(命中多到少、平手母版序),弱化在後(母版序);弱化一律包含。"""
    items = [CustomizedItemOut(text="a", matchedKeywords=["SQL"], highlighted=True),
             CustomizedItemOut(text="b", matchedKeywords=[], highlighted=False),
             CustomizedItemOut(text="c", matchedKeywords=["SQL", "Excel"], highlighted=True),
             CustomizedItemOut(text="d", matchedKeywords=[], highlighted=False)]
    exps = [ExperienceIn(id=str(i), title=f"t{i}", category="x", timeRange=f"r{i}",
                         description="", tags=[]) for i in range(4)]
    out = order_experiences(exps, items)
    assert [o.title for o in out] == ["t2", "t0", "t1", "t3"]      # 2命中 > 1命中 > 弱化依原序
    assert len(out) == 4 and out[0].timeRange == "r2"              # 每條自帶標題時間、弱化都在


def test_skills_split_prioritized_by_covered_via_normalizer():
    """契約規則 3:職缺看重且已具備排前,其餘保母版序;比對過正規化。"""
    pri, oth = split_skills(["數據分析", "SQL", "報表", "Excel"], ["SQL", "Excel"], NORM)
    assert pri == ["SQL", "Excel"] and oth == ["數據分析", "報表"]


def test_contact_omits_empty_and_edu_line_display_ready():
    """契約規則 1、2:contact 空值省略鍵;eduLine 顯示就緒。"""
    r = customize_full(JOB, PROFILE, EXPS, normalizer=NORM, llm=None)
    assert r.contact == {"email": "test@gmail.com", "linkedin": "alex-lin"}   # phone/github/portfolio 缺鍵
    assert r.header.eduLine == "NSYSU · MIS · 大三"
    assert r.header.bio.endswith("哈哈")                                       # 原文照登,不改寫
    assert build_edu_line(ProfileIn(name="n", school="A", department="", year="")) == "A"


def test_full_pipeline_no_llm_is_deterministic_and_complete():
    """無 LLM 走確定性路徑:三條經歷都在、強化(SQL/Excel 那條)排最前、不帶 highlighted。"""
    r = customize_full(JOB, PROFILE, EXPS, normalizer=NORM, llm=None)
    assert len(r.experiences) == 3
    assert r.experiences[0].title == "電商實習"
    assert not hasattr(r.experiences[0], "highlighted")
    assert r.skills.languages[0].level == "TOEIC 875"


def test_route_smoke_and_404():
    c = TestClient(app, raise_server_exceptions=False)
    body = {"userId": "u", "jobId": _FIRST_JOB_ID, "profile": PROFILE.model_dump(),
            "experiences": [e.model_dump() for e in EXPS]}
    r = c.post("/resume/customize/full", json=body)
    assert r.status_code == 200 and set(r.json()) == {"header", "contact", "skills", "experiences"}
    assert c.post("/resume/customize/full", json={**body, "jobId": "nope"}).status_code == 404
