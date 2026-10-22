# 課程目錄建置報告（成員 A）

`fixtures/resources/resources_v1.json`（reinforce 的課程來源）的建置方式與現況。

## 建置方式（2026-10-19，受限選擇版）

來源：爬蟲組 `courses_dedup.jsonl`（全國 13.8 萬門課，篩中山 4983 門）。
管線：`tools/extract_courses.py` → LLM 從詞彙表 234 個 `name_zh` **直接挑**每門課教到的技能
（受限選擇，非自由抽取），輸出過濾成有效 `name_zh` 後彙整成目錄。

**為什麼不用 bge-m3 正規化**：先試過「LLM 自由抽取 → bge-m3 最近鄰（門檻 0.88）」，
只救回 143 門；且正確配對（C++程式設計→C++ 0.83）與錯誤配對（材料分析→資料分析 0.74）
相似度重疊，沒有乾淨門檻。改受限選擇後，輸出保證對齊詞彙表、**無正規化殘留**、
LLM 語意判斷也較準。故本檔不再有「對不上」的殘留清單。

## 現況

- 中山課程 4983 門 → **入目錄 1533 門**（有 ≥1 項職能技能）；3450 門零技能剔除
  （純理工實驗、人文、通識、體育等，與職能詞表無關，屬正常）。
- 技能標註 2366 個，平均每門 1.5 個；涵蓋 77 個不重複技能；**無效技能 0**。
- 最常見技能：資料分析(287)、問題分析與解決能力(244)、溝通能力(169)、統計分析(165)、
  書面表達(111)、口語表達(100)、需求分析(69)、程式設計相關知識(64)、簡報表達(55)。

## 給成員 B 的覆核點

- 通用軟實力（問題分析與解決能力、溝通能力、書面／口語表達、批判性思考）佔比偏高。
  這些本就在詞彙表內、是合法職能，reinforce 也用得到；但若覺得推薦時雜訊太多，
  可在 `extract_courses.py` 的 system prompt 加一條「少挑通用軟實力」，重跑即可。
- 競賽技能標註另見 `competitions_residuals_report.md`。

## 重建指令

```
python tools/extract_courses.py --courses data/courses_dedup.jsonl \
    --school-match 中山 --school nsysu --provider 國立中山大學 \
    --out data/resources_raw_skills_llm.jsonl \
    --catalog fixtures/resources/resources_v1.json
# 已有中間檔、只想重新彙整：加 --finalize-only
```
