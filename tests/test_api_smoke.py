"""煙霧測試:端點起得來、吃合法請求回 200、吃壞請求回統一錯誤格式。"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

EXP = {"id": "e2", "title": "電商公司資料分析實習", "category": "工作",
       "timeRange": "2025.07 - 2025.09",
       "description": "協助業務團隊整理銷售數據,用 SQL + Excel 產出週報。",
       "tags": ["數據分析", "SQL", "報表", "Excel"]}


def test_all_endpoints_return_valid_shape():
    calls = [
        ("/resume/master/generate", {"userId": "dev_user_001", "narratives": ["我在社團當行銷組長"]}),
        ("/career/recommend", {"userId": "dev_user_001", "query": "我喜歡整理數據", "experiences": [EXP]}),
        ("/jobs/fit-all", {"userId": "dev_user_001", "experiences": [EXP]}),
        ("/jobs/fit_da/fit", {"userId": "dev_user_001", "experiences": [EXP]}),
        ("/resume/customize", {"userId": "dev_user_001", "jobId": "fit_da", "experiences": [EXP]}),
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
