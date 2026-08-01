"""B2 適配管線測試——alias 正規化+覆蓋率單腿尺,免錢免模型。"""
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.jobs_fit import style_tag

client = TestClient(app, raise_server_exceptions=False)

EXP = {"id": "e1", "title": "電商實習", "category": "工作", "timeRange": "暑假",
       "description": "d", "tags": ["Excel", "中文打字", "顧客服務"]}
BODY = {"userId": "dev_user_001", "experiences": [EXP]}


def test_fit_all_scored_sorted_and_contract_shaped():
    r = client.post("/jobs/fit-all", json=BODY)
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert len(jobs) == 14
    scores = [j["matchScore"] for j in jobs]
    assert scores == sorted(scores, reverse=True)          # 最適配排最前
    assert all(0 <= s <= 100 for s in scores)
    assert all(j["styleTag"] for j in jobs)
    assert any(j["matchScore"] > 0 for j in jobs)          # Excel/打字對上行政類,不該全零


def test_single_fit_and_unknown_id():
    first = client.post("/jobs/fit-all", json=BODY).json()["jobs"][0]["jobId"]
    r = client.post(f"/jobs/{first}/fit", json=BODY)
    assert r.status_code == 200 and r.json()["jobId"] == first

    bad = client.post("/jobs/fit_ghost/fit", json=BODY)
    assert bad.status_code == 404
    assert bad.json()["error"]["code"] == "job_not_found"  # 統一錯誤格式


def test_style_tag_deterministic():
    assert style_tag(["SQL", "Python", "統計"]) == "數據導向型"
    assert style_tag(["顧客服務", "銷售話術", "團隊合作"]) == "溝通導向型"
    assert style_tag(["品牌行銷管理", "社群媒體經營管理", "Excel", "Word"]) == "創意行銷型"
    assert style_tag(["Excel", "Word", "PowerPoint", "Outlook"]) == "文書務實型"  # 萬用技能不投票
    assert style_tag([]) == "文書務實型"


def test_style_tag_reads_jd_text():
    """技能欄只有 Office 萬用技能時,標籤要聽 JD 內文的訊號。"""
    assert style_tag(["Excel", "Word"],
                     jd="負責電話客服,與客戶溝通並提供服務") == "溝通導向型"
    assert style_tag(["Excel"],
                     jd="社群經營與品牌行銷企劃,產出文案") == "創意行銷型"
    assert style_tag(["Excel", "Word"], jd="一般文書作業") == "文書務實型"


def test_fixture_display_sanity():
    """顯示值健檢:時薪不得偽裝成月薪 k(0-0k 案),標題不得斷在括號半空。"""
    import json
    from pathlib import Path
    fx = json.loads((Path(__file__).resolve().parents[1] /
                     "fixtures/jobs/jobs_v1.json").read_text(encoding="utf-8"))
    for j in fx:
        assert not j["salary"].startswith("0"), j["jobId"]
        assert not j["title"].endswith(("（", "(")), j["jobId"]


def test_split_title_generalizes_beyond_demos():
    """拆解器的泛化測試:全部用示範清單以外的結構,防過擬合。"""
    from tools.build_jobs import split_title
    assert split_title("【財務】資深預算專員")[0] == "資深預算專員"      # 前綴部門括號
    assert split_title("作業員【30670起】")[1] == []                     # 裸數字薪資丟棄
    assert split_title("工程師(日商)")[1] == ["日商"]                    # 認不出 → 保留
    name, badges = split_title("門市人員(月休8天,需輪班)")
    assert name == "門市人員"
    assert "需輪班" in badges and all("月休" not in b for b in badges)   # 話術丟/條件留
