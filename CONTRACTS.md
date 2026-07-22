# CONTRACTS.md — 資料合約決策紀錄

> 凍結日：Day 1–2（由 Claude 依 `alexlin8888/CareerSandbox@main` 原始碼產出初版，待兩位成員審查定案）
> 「凍結」的意思：改動從默默發生變成明確事件。變更流程見文末。

## 0. 事實來源優先序

**前端程式碼 > 交接文件 > 本文件的假設。** 已知文件與程式碼的出入：
`CareerRec` 實際多了 `icon: ImageVector` 與 `academicNote`（以程式碼為準）。

## 1. 對外合約（前端 ↔ FastAPI）

實體定義：`app/schemas/api.py`（每欄位含決策註解）。範例：`fixtures/golden/*.json`。

| # | 決策 | 依據 |
|---|------|------|
| 1 | 欄位名 camelCase，逐字鏡射 Kotlin data class | 前端 org.json 按名取值；Real service 越薄越好 |
| 2 | List 永不為 null，空值回 `[]` | Kotlin 宣告非空 List，null 會 crash |
| 3 | `matchScore` 為 0–100 整數 | 前端現值 65–92 全為 Int |
| 4 | CareerRec `category` ∈ {數據, 產品, 設計, 學術}；「全部」僅為 UI 篩選器 | CareerExplorationScreen.kt L83–141 |
| 5 | 經歷 `category` ∈ {社團, 工作, 競賽, 學業}（輸出嚴格；輸入收 str） | MockData.kt L56–67 |
| 6 | **`icon` 不進 API**（ImageVector 不可序列化）；前端以 category→icon 對照表本地補 | CareerRec 定義；→ 給怡君 D11 |
| 7 | id 命名照前端現存風格：career 純 slug（`data_analyst`）、job `fit_*`、KB `kb_*`、AI 草稿經歷 `e_ai_{n}` | 各檔現值 |
| 8 | 顯示字串照 MockData 風格：salary `"45-65k"`、deadline `"11/02 截止"`、openings `"1,240"`（千分位字串）、shortSubtitle `"數據 · 45-65k"` | MockData / CareerExplorationScreen |
| 9 | **B2、C1 用 POST 帶 `experiences`**（非 GET）：Kotlin 介面無使用者參數，個人化資料由 Real service 從本地母版（ResumeHierarchyProvider）取得放入 body | FitAnalysisService.kt 簽章 |
| 10 | B1 response 含 `jdKeywords` + `coveredKeywords`（前端目前掛在 Mock 物件上、不在 interface，抽 provider 時對齊） | JdCustomizer.kt |
| 11 | 錯誤統一 `{"error": {"code", "message"}}`；連線失敗／非 2xx／解析失敗 → 前端退回 Mock（保險絲已內建於 RemoteSandboxChatEngine 模式） | RemoteSandboxChatEngine.kt L42 |
| 12 | `userId` 一律先填 `"dev_user_001"`；帳號系統上線後**只換值、不改形狀** | accounts 未建 |
| 13 | 母版生成回「**草稿**」：`sourceQuote`（證據句）+ `confidence`，使用者在前端確認後定稿——不捏造的執行點 | 計畫書 human-in-the-loop |
| 14 | 母版生成與 B3 overview 為**我方主筆 PROPOSAL**，待怡君回簽。母版生成已錨定現成 UX：ExperienceEditScreen 的「AI 對話訪談（7 題 → 經驗卡 → 存母版）」，本端點即其**生成步驟**（7 題腳本先留前端） | 01 文件履歷頁清單 |
| 15 | **生成文字風格鐵律**：所有展示文字禁用驚嘆號（! / ！）、口吻去 AI 味（不生硬、不樣板、慎用引號）。已寫進合約測試 `test_no_exclamation_marks_anywhere`，之後真 LLM 輸出也要過這關 | 01 文件 D12——核心用研洞察，全 app 現況 0 違規 |

## 2. 內部合約（成員 A ↔ 成員 B）

實體定義：`app/contracts/protocols.py`、`app/schemas/domain.py`（snake_case）。

- `Extractor`（B）／`Normalizer`、`Retriever`、`Scorer`（A）
- B 在 A 交付前一律接 `FakeRetriever`／`FakeEmbedding`；換真實作時呼叫端零改動
- 分數是確定性公式（Scorer），LLM 只寫解釋不給分——可追溯性要求

## 3. 落地合約（FastAPI ↔ MongoDB Atlas）——已依 03 文件補齊

**向量知識庫 = collection `career_knowledge`**（03 Part 2-14：資料庫組 host 並開索引，內容由我們＋爬蟲組供給、我們直接讀寫）：

| 落地欄位 | 內部對應（domain.KBEntry） | 說明 |
|---|---|---|
| `_id` | `id` | `kb_{n}` |
| `type` | `type` | 對齊 03 的值：`job_skill` / `career_path` / `industry`（kb_seed 已同步） |
| `text` | `content` | 條目原文；欄位名差異在 repository 層轉換 |
| `title`、`skills[]` | `title`、`skills` | 03 草案沒有、**我方新增**：title 供除錯呈現，skills 是檢索 filter |
| `embedding[1024]` | —（寫入時計算） | bge-m3；維度寫死於索引，換模型＝合約變更 |
| `source`、`metadata.industry` | `metadata.*` | filter 欄位 |

**索引定義已生成 → `fixtures/atlas/vector_index.json`**（cosine、1024 維、filter：type / skills / metadata.industry），對齊會直接交給資料庫組。

**使用者資料（Node 唯一寫入，我們只算不存）**：母版草稿經使用者確認 → `experiences`（欄位與 ExperienceIn 一致）＋彙整技能寫回 `users.skillsHave`（03：「母版 = experiences + users.skills」）；B1 存版本 → `job_targets.versions`（新模型、`SubmissionStatus` 六態；舊 `JobApplication` 不建）；C1 推薦**不落地**（03 明示；使用者的排除偏好可選存 `career_exclusions`）。

## 4. 給怡君的三件事

1. **D11／D14**：抽 CareerRec 與 overview 的 provider；CareerRec 前端補 category→icon 對照表（API 不送 icon）
2. 把 `fixtures/golden/*.json` 貼進 Kotlin 反序列化單元測試（十行，合約雙向上鎖）
3. 回簽兩份 PROPOSAL：`/resume/master/generate`、`/resume/overview` 的形狀

## 5. 變更流程

任何 schema 變更 = ① 兩位成員同意 → ② 同步改 golden JSON → ③ `pytest tests/` 全綠 → ④ 動到對外層則通知怡君。三週的專案不是被改需求搞死的，是被沒人知道的悄悄改搞死的。

## 6. 開放決定

1. **B1 客製結果存哪？** 03 的 `job_targets.versions` 只有 `label / status / submittedDate / note`，**沒有內容欄位**——客製後的段落（CustomizedItem）目前無處落地，重開版本就看不到內容。兩個選項：(a) versions 加 `items[]` 內嵌；(b) 不存、每次依 jdKeywords 重新生成（省空間但耗 LLM 且結果會漂移）。**需資料庫組＋怡君三方定案**，傾向 (a)。
