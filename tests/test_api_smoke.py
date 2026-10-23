"""煙霧測試:端點起得來、吃合法請求回 200、吃壞請求回統一錯誤格式。"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

import json as _json
from pathlib import Path as _Path
_FIRST_JOB_ID = _json.loads(
    (_Path(__file__).resolve().parents[1] / "fixtures/jobs/jobs_v1.json"
     ).read_text(encoding="utf-8"))[0]["jobId"]

EXP = {"id": "e2", "title": "電商公司資料分析實習", "category": "工作",
       "timeRange": "2025.07 - 2025.09",
       "description": "協助業務團隊整理銷售數據,用 SQL + Excel 產出週報。",
       "tags": ["數據分析", "SQL", "報表", "Excel"]}


def test_all_endpoints_return_valid_shape():
    calls = [
        ("/resume/master/generate", {"userId": "dev_user_001", "narratives": ["我在社團當行銷組長"]}),
        ("/career/recommend", {"userId": "dev_user_001", "query": "我喜歡整理數據", "experiences": [EXP]}),
        ("/jobs/fit-all", {"userId": "dev_user_001", "experiences": [EXP]}),
        (f"/jobs/{_FIRST_JOB_ID}/fit", {"userId": "dev_user_001", "experiences": [EXP]}),
        (f"/resume/customize", {"userId": "dev_user_001", "jobId": _FIRST_JOB_ID, "experiences": [EXP]}),
        ("/resume/overview", {"userId": "dev_user_001", "experiences": [EXP], "jobTargets": []}),
    ]
    for path, body in calls:
        r = client.post(path, json=body)
        assert r.status_code == 200, f"{path}: {r.text[:200]}"


def test_bad_request_returns_unified_error_shape():
    r = client.post("/career/recommend", json={"userId": "dev_user_001"})  # 缺 query
    assert r.status_code == 422
    assert "error" in r.json() and "code" in r.json()["error"]


def test_fake_retriever_wires():
    from app.retrieval.fake_retriever import FakeRetriever
    chunks = FakeRetriever().search("我對 SQL 和報表有興趣", k=3)
    assert chunks and chunks[0].entry.id.startswith("kb_")


def test_health_reports_embedding_state():
    """2026-10-22: /health exposes whether bge-m3 loaded so a degraded deploy is visible.
    ?deep=1 forces the lazy load; in CI (no torch) that yields embedding=false plus the error."""
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    base = c.get("/health").json()
    assert base["status"] == "ok" and "embedding" in base
    deep = c.get("/health?deep=1").json()
    assert deep["embedding"] in (True, False)
    if deep["embedding"] is False:
        assert deep["embeddingError"]


def test_job_fit_carries_score_basis_and_customize_items_carry_ids():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    exps = [{"id": "x1", "title": "電商實習", "category": "工作", "timeRange": "",
             "description": "每週用 SQL 跟 Excel 做週報", "tags": ["SQL", "Excel"]}]
    fit = c.post("/jobs/fit_93bo9/fit", json={"userId": "u", "experiences": exps}).json()
    assert "scoreBasis" in fit
    cz = c.post("/resume/customize", json={"userId": "u", "jobId": "fit_93bo9",
                                           "experiences": exps}).json()
    assert cz["items"][0]["id"] == "x1" and "matchedTags" in cz["items"][0]
