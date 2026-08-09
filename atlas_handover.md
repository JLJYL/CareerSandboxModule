# Atlas 向量知識庫交接（給成員 B 與後端組）

> 落地日期：2026-08-09
> 驗收紀錄：`docs/atlas_ingest_report.md`
> 匯入工具：`tools/ingest_atlas.py`

## 一、落地結果

| 項目 | 值 |
|---|---|
| Cluster | Atlas（MongoDB 8.0.29） |
| Database | `CareerSandboxDB` |
| Collection | `career_knowledge` |
| 文件數 | 587 |
| 向量索引 | `career_knowledge_vec_idx`（queryable） |
| Embedding | bge-m3，1024 維，cosine |
| 佔用空間 | 約 8.84 MB（其中文章全文約 8.26 MB） |

條目組成：

| type | 條數 | 來源 |
|---|---|---|
| `article` | 544 | 第三方文章切塊（104職場力、yourator） |
| `job_skill` | 23 | 策展種子 |
| `career_path` | 13 | 策展種子 |
| `industry` | 7 | 策展種子 |

註：舊文件寫的 586 是 W2 的數字。commit `0cf88d9` 補入 `kb_043`（資料工程師的核心技能）後，正確條數為 587。相關文件已一併更正。

## 二、文件結構

欄位對應依 `CONTRACTS.md` #3：

| 落地欄位 | 內部對應 | 說明 |
|---|---|---|
| `_id` | `KBEntry.id` | `kb_001` / `kb_a001` |
| `type` | `type` | job_skill / career_path / industry / article |
| `title` | `title` | 除錯與顯示用 |
| `text` | `content` | 條目原文 |
| `skills[]` | `skills` | 檢索 filter |
| `source` | `metadata.source` | 提到頂層 |
| `metadata` | `metadata` | 整包保留，含 industry / url / sourceId / part |
| `embedding[1024]` | 寫入時計算 | bge-m3 |
| `embeddingModel`、`embeddingDim` | — | 稽核用 |
| `createdAt`、`updatedAt` | — | 匯入時戳 |

## 三、查詢方式

```javascript
db.career_knowledge.aggregate([
  { $vectorSearch: {
      index: "career_knowledge_vec_idx",
      path: "embedding",
      queryVector: <bge-m3 算出的 1024 維向量>,
      numCandidates: 100,
      limit: 5,
      filter: { type: "job_skill" }        // 選用
  }},
  { $project: { _id: 1, type: 1, title: 1, text: 1,
                score: { $meta: "vectorSearchScore" } }}
])
```

索引宣告的 filter 欄位為 `type`、`skills`、`metadata.industry`。

## 四、後端組必須注意的五件事

### 1. 查詢向量必須用 bge-m3 算

換 embedding 模型屬合約變更（`CONTRACTS.md` #3）。用其他模型算查詢向量不會報錯，但分數會完全失效——這是最難察覺的錯誤模式。實作見 `app/providers/embeddings.py` 的 `BgeM3Embedding`（原生 torch + transformers，CLS pooling + L2 正規化）。

### 2. 文章有著作權限制

544 條 `article` 是第三方內容。依 W1／W2 決議：**僅供檢索，生成時必須改寫並附上 `metadata.url` 出處**，不可將 `text` 原文直接回傳給使用者。

### 3. 切塊會造成結果重複

544 塊來自 164 篇文章，平均 3.3 塊一篇，最多的一篇切成 8 塊。同一篇的多個切塊語意相近，會集體擠進 top-k。實測：

| 查詢 | top-5 實際涵蓋的文章數 |
|---|---|
| 轉職資料分析要準備什麼 | 3 篇 |
| 轉職準備（filter: article） | 3 篇 |

建議 API 層撈 `k * 3` 後依 `metadata.sourceId` 收斂，每篇只取最高分的一塊。

### 4. 有 28 塊 offtopic 資料

標記在 `metadata.offtopic`，內容與職涯無關（例如統一發票中獎號碼）。目前一併匯入以保持 Atlas 與本機索引一致。建議查詢時預設排除，或由團隊決議是否從資料層清除。

### 5. 文章型結果會壓過策展條目

544 / 587 = 93% 的語料是文章，無 filter 查詢幾乎必然由文章主導。需要策展內容時請明確帶 `filter: { type: "job_skill" }` 等條件。

## 五、驗證結果

### 向量沿用的正當性

586 條向量沿用自 W2 的既有快取，僅 `kb_043` 為新算。git 比對確認 commit `0cf88d9` 對既有條目的 `title` 與 `content` 皆未修改（文章僅變更 `metadata.careerId`，不影響 embedding 輸入）。匯入時抽驗三條既有條目重算比對：

```
kb_001   sim=1.000000 OK
kb_a154  sim=1.000000 OK
kb_a349  sim=1.000000 OK
```

### type filter 實測

```
查詢「資料分析師需要什麼技能」filter: job_skill
  0.886  [kb_001] 資料分析師的核心技能
  0.846  [kb_043] 資料工程師的核心技能
  0.794  [kb_021] 資訊助理的市場技能要求

查詢「轉職準備」filter: article
  0.836  [kb_a483] 我該轉職嗎？轉職準備怎麼做？
  0.824  [kb_a485] 我該轉職嗎？轉職準備怎麼做？
  0.815  [kb_a482] 我該轉職嗎？轉職準備怎麼做？
```

`kb_043` 在真實查詢中排名第二且語意位置合理，可佐證新算向量正確。

### 尚未驗證

`skills` 與 `metadata.industry` 兩個 filter 已宣告於索引但未實測。`skills` 為陣列欄位，行為與純量 filter 不同，首次使用前建議先驗。

## 六、重跑方式

匯入為冪等操作（依 `_id` upsert），重跑不會產生重複文件。

```
set HF_HUB_OFFLINE=1
python tools/ingest_atlas.py --check          # 唯讀，驗連線與現況
python tools/ingest_atlas.py --dry-run        # 不連線，驗資料
python tools/ingest_atlas.py --create-index   # 落地，索引已存在則跳過
```

前置條件：

- `.env` 需含 `MONGODB_URI`（範本見 `.env.example`）。此檔不進 Git。
- `data/kb_index.json` 需為 587 條的 bge-m3 快取。有此檔則不需要模型；無此檔需 `pip install -r requirements-ml.txt` 並下載約 2.3GB 的 bge-m3。
- KB 種子有增刪時，工具會自動補算缺少的條目並回寫快取。

## 七、待決事項

1. `career_knowledge` 與使用者資料同放 `CareerSandboxDB`。此為既有慣例（該 DB 已混放 users/experiences 與 courses/skills/occupations 等參考資料），但重灌向量庫時需注意勿誤對 database 層操作。
2. 後端若已有指向 `career_knowledge` 的 Mongoose model，其資料形狀與本次落地不同，需確認是否衝突。
3. offtopic 28 塊的去留。
4. `career_db_user` 目前具 `atlasAdmin` 權限，對應用層而言過大。建議降為 `readWrite@CareerSandboxDB`，另備管理帳號供匯入等維運作業使用。
