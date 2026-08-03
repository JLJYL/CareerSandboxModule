# 黃金測試集（W3 合流交付）

5 份真實履歷 × 3 個 JD。填法：

**profiles/**：每份履歷一個 JSON。從 `fixtures/samples/` 的去識別化履歷**人工**抽出技能字串
（照履歷原文寫法抄，別先翻成標準名——正規化是被測物之一）。B 的擷取器上線後改由它產出，格式不變。

```json
{"profile_id": "p1", "label": "履歷1_商管數據背景", "skills": ["Excel", "數據分析", "簡報", "SQL"]}
```

**jds/**：從 jobs_all.jsonl 挑 3 筆真職缺（建議：一筆有結構化 requiredSkills 的 104 職缺、
一筆只有 jd_text 的其他源職缺——退化路徑也要覆核、一筆與多數 profile 不對盤的當對照組）。

```json
{"job_id": "fit_001", "title": "資料分析師", "required_skills": ["SQL", "Python"], "jd_text": "（貼 JD 原文）"}
```

檔名任意（`_` 開頭的會被跳過，範本檔因此不進跑分）。跑法見 tools/run_golden_set.py 檔頭。
覆核簽收後，這組 profile×jd 連同人工判定入庫成回歸基準——之後任何 prompt 或公式改動都拿它回歸。
