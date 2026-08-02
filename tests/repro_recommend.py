"""現場偵察器 v3:兩階段圍捕。
階段A:用煙霧測試一模一樣的 body 直打真管線。
階段B:完整模擬 pytest(清空 LLM 設定+TestClient+例外裸奔)打同一路由。
用法:放 repo 根目錄 → python repro_recommend.py → 全文貼回
"""
import sys
import traceback

sys.path.insert(0, ".")

EXP = {"id": "e2", "title": "電商公司資料分析實習", "category": "工作",
       "timeRange": "2025.07 - 2025.09",
       "description": "協助業務團隊整理銷售數據,用 SQL + Excel 產出週報。",
       "tags": ["數據分析", "SQL", "報表", "Excel"]}
BODY = {"userId": "dev_user_001", "query": "我喜歡整理數據", "experiences": [EXP]}

STAGE = "匯入"
try:
    from app.api.routes import _build_reco_deps
    from app.pipeline.recommend import recommend
    from app.schemas.api import ExperienceIn

    STAGE = "A. 建依賴"
    deps = _build_reco_deps()
    if deps is None:
        print("依賴建不起來,換平常那台機器跑")
        raise SystemExit
    retriever, scorer, normalizer = deps

    STAGE = "A. 煙霧同款 body 直打管線"
    out = recommend(BODY["query"], [ExperienceIn(**EXP)], normalizer=normalizer,
                    retriever=retriever, scorer=scorer, llm=None)
    print(f"階段A 沒炸,回 {len(out)} 筆:", [(c.id, c.matchScore) for c in out])

    STAGE = "B. 模擬 pytest 環境(清 LLM 設定)+TestClient"
    from app.config import settings
    settings.llm_base_url = ""
    settings.llm_api_key = ""
    settings.llm_model = ""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post("/career/recommend", json=BODY)
    print(f"階段B 沒炸,HTTP {r.status_code}:", r.text[:160])
except SystemExit:
    pass
except Exception:
    print(f"\n=== 在「{STAGE}」爆炸,完整病歷 ===")
    traceback.print_exc()
