# 交接：careerId 標註 + data_engineer 技能條目

**作者**：成員 A ｜ **對象**：成員 B ｜ **狀態**：完成，`pytest tests/ -q` 47 passed

回應模型組回饋的兩項：文章補標 careerId、補 data_engineer 技能條目。以下是做了什麼、你（B）要知道什麼。

---

## 一、新增職涯定義檔 `fixtures/careers/careers.v1.json`（⚠ 這是給你 C1 用的）

**這是本次最重要的產出**，因為 C1 推薦要用它提名候選職涯。

- **30 個職涯大類**，由 `fixtures/eval/occupations_harvest.csv` 的 95 個真實職業歸併而成（全職業，非限科技業）。
- 每個職涯含：`careerId`（小寫英文+底線，沿用原種子 `data_analyst`/`pm` 風格）、`name`（中文名）、`aliases`（標註比對關鍵字）、`includes`（對齊的原始細分職業名）。
- **careerId 是新的跨組共享識別碼**。C1 提名候選職涯時請從這 30 個取用；前端若要 ID→中文顯示，用 `name` 欄。這份是 v1，要增修職涯請跟我開口（我維護 kb_seed / careers 定義）。

30 個職涯：software_engineer、frontend_engineer、fullstack_engineer、ai_data_engineer、qa_engineer、network_engineer、it_support、data_analyst、pm、uiux_designer、graphic_designer、content_creator、marketing、sales、customer_service、hr、finance_accounting、procurement、logistics、admin、operations_mgmt、reception、beauty、food_service、driver、technician、travel、legal、public_sector、healthcare。

---

## 二、文章補標 careerId（`fixtures/kb_seed/kb_entries.articles.v1.json`）

544 篇文章段落，用 `tools/annotate_career_id.py` 標註，原則是模型組要求的「確定才標、不確定留空、標錯比不標更糟」：

| 結果 | 篇數 | 說明 |
|---|---|---|
| 已標 careerId | **84** | 標題明確唯一命中某職涯 aliases（高信心） |
| 標為 offtopic | 28 | 發票/颱風/放假等民生新聞雜訊，標 `metadata.offtopic=true` |
| 留空（多重命中） | 3 | 標題命中多個職涯，模稜兩可 |
| 留空（無命中） | 429 | 泛用職場文（如「怎麼談薪水」），不屬單一職涯 |

**⚠ 你（B）在 C1 / 計分時要注意的**：

1. **只有 84 篇有 careerId，這是刻意的保守標註**。大量留空不是遺漏——泛用文章本來就不該綁定職涯。提名候選職涯時，只有帶 careerId 的文章能歸給特定職涯；留空的仍可被語意檢索到，只是不參與「以文章提名職涯」。
2. **標註只認標題、不認內文**。內文順帶提及某職業不算（避免誤標）。所以標得準但覆蓋窄，這是「標錯比不標更糟」的取捨。
3. **`metadata.offtopic=true` 的 28 篇建議在檢索/生成時過濾掉**——它們是發票中獎號碼這類民生新聞，被爬蟲誤收，對職涯問答是雜訊。
4. **標註可重跑**：`python tools/annotate_career_id.py --dry-run` 先看統計，去掉 --dry-run 寫入。之後職涯池增修或文章增量，重跑即更新。

**踩過的坑（供你參考）**：短英文 alias 會子字串誤命中——`OP`（旅行社）曾誤命中 "Lo**op**"、"**Op**en House"、"meepSh**op**"，把 18 篇科技新創文誤標成 travel。已移除所有 ≤3 字母的純英文 alias（OP/ISO/ERP）。你若之後擴 aliases，避免加短英文縮寫。

---

## 三、新增 data_engineer 技能條目（`fixtures/kb_seed/kb_entries.v1.json`）

- 原本 data_engineer 只有 1 條 **career_path** 型（講職涯路徑），**缺 job_skill 型技能清單**——這是回饋說「data_engineer 沒有技能清單」的實情。
- 新增 `kb_043`（job_skill）「資料工程師的核心技能」，格式對齊 data_analyst 的 `kb_001`。
- skills：Python、SQL、ETL、Airflow、Spark、資料倉儲、資料建模、雲端平台、Docker、Linux（取自回饋附的 15 筆 JD 高頻技能 + 資料工程標配）。
- 內容口吻已過「無驚嘆號、去 AI 味」關（本組鐵則）。

---

## 動了哪些檔（都在成員 A 地盤，未碰凍結區）

```
新增  fixtures/careers/careers.v1.json          職涯定義（30 類）
新增  tools/annotate_career_id.py               標註腳本（可重跑）
改動  fixtures/kb_seed/kb_entries.articles.v1.json   544 篇補 metadata（84 標 careerId / 28 offtopic）
改動  fixtures/kb_seed/kb_entries.v1.json        新增 kb_043 data_engineer job_skill
新增  HANDOVER_careerId_dataeng.md              本文件
```

- **未動凍結區**（schemas / contracts / golden 皆未改）。careerId 一直是 `metadata` 內的自由欄位（schema domain.py 第 46 行註解本就列出 careerId），故不需改 schema、不需開合約會。
- **`pytest tests/ -q` → 47 passed**。
- 建議走 `feat/a-careerid-annotation` 分支開 PR，CI 綠燈後 squash merge。

## 尚未處理（留給後續，非本次範圍）

- 模型組回饋的 Scorer 三件（空輸入 55 分、向量首次建表慢、進度訊息干擾）——那是 scorer.py / normalize.py 的事，本次未動，另議。
- 429 篇留空的泛用文章：若之後想提高職涯覆蓋，可考慮從內文（非只標題）做更寬鬆標註，但需權衡誤標風險。
