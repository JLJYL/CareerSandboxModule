# 黃金測試集（W3 合流交付）

本目錄以 `golden_pairs.v1.json` 保存經 A＋B 人工覆核定案的黃金測試集：

- 5 份去識別化履歷
- 3 份真實 JD
- 15 組履歷 × JD 配對
- 每組皆以 `verified: true` 標記覆核完成
- 每項 required skill 採 covered／missing 二值裁決

## 執行方式

流程驗證（Fake embedding）：

    python tools\run_golden_pairs.py

正式回歸（本機 bge-m3）：

    set HF_HUB_OFFLINE=1
    python tools\run_golden_pairs.py --real

兩種模式皆會輸出 `data\golden_pairs_report.md`。

正式驗收條件為 15/15 格通過、逐技能 75/75。正式回歸報告應複製到 `docs\golden_pairs_report.md`，作為 W3「差集結果人工覆核通過」的存證。

## 維護規則

修改詞彙表、正規化門檻、alias、合併規則或 matchScore 公式後，必須重新執行正式回歸。任何一格失敗時，`run_golden_pairs.py` 會以非零結束碼退出，並在報告中列出錯誤技能、預期裁決與正規化明細。