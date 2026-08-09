# Atlas 落地驗收紀錄

- 執行時間：2026-08-09T08:40:20.449905+00:00
- 連線：`mongodb+srv://<redacted>@<redacted>/CareerSandboxDB?appName=Cluster0`
- 目標：`CareerSandboxDB.career_knowledge`
- 種子檔條數：587
- 落地後文件數：587
- 新增／更新：0／587
- 向量：bge-m3，1024 維（快取沿用 586／新計算 1）
- 快取抽驗：kb_001 sim=1.000000 OK；kb_a154 sim=1.000000 OK；kb_a349 sim=1.000000 OK
- 索引：`career_knowledge_vec_idx`（existing）

## Smoke query

查詢：轉職資料分析要準備什麼

- 0.822  [kb_a483] (article) 我該轉職嗎？轉職準備怎麼做？ honestbee 台灣 Food GM 個人轉職
- 0.801  [kb_a485] (article) 我該轉職嗎？轉職準備怎麼做？ honestbee 台灣 Food GM 個人轉職
- 0.799  [kb_a442] (article) 【新創轉職攻略】我適合新創嗎？新創履歷撰寫、新創求職FAQ（1/3）
- 0.799  [kb_a535] (article) 數據分析師面試作品集準備 3 大原則，成為面試官眼中最亮眼的資料分析師！（3/3
- 0.785  [kb_a533] (article) 數據分析師面試作品集準備 3 大原則，成為面試官眼中最亮眼的資料分析師！（1/3

> 本檔不含任何連線字串或帳密。
