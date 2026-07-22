# CareerSandbox AI Service（能力建模骨架）

Day 1–2 凍結產出：全假零件、端到端會跑。三週工作 = 把假零件逐一換真，任何時刻都能 demo。

## 快速開始
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000/docs 有互動文件
pytest tests/ -q                        # 合約測試,改壞任何一邊立刻變紅
```
Android 模擬器打 `http://10.0.2.2:8000`;實機用電腦區網 IP。

## 試打一發
```bash
curl -X POST localhost:8000/career/recommend -H 'Content-Type: application/json' \
  -d '{"userId":"dev_user_001","query":"我喜歡整理數據","experiences":[]}'
```

## 地圖（誰的地盤）
```
app/schemas/api.py        對外合約(camelCase,鏡射 Kotlin)——凍結層
app/schemas/domain.py     內部領域模型(snake_case)
app/contracts/protocols.py 兩人國界:Extractor(B) / Normalizer·Retriever·Scorer(A)
app/pipeline/extraction.py  ← 成員 B 第 1 週主戰場
app/pipeline/normalize.py   ← 成員 A 第 2 週
app/pipeline/profile.py     ← 成員 B 第 1 週末
app/retrieval/fake_retriever.py  B 的替身檢索;A 第 2 週交 ChromaRetriever 換掉
app/providers/            LLM / embedding 抽象(bge-m3, 1024 維)
fixtures/golden/          六份 golden JSON = 對外合約的活範例
fixtures/kb_seed/         知識庫格式範本;成員 A 第 1 週擴到 30–50 條
fixtures/samples/         真實履歷+JD 放這裡(Day 3 前,去識別化)
CONTRACTS.md              所有決策與變更流程——先讀這份
```
