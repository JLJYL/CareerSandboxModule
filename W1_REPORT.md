# W1 交付：技能詞彙表 v1 ＋ 種子知識庫 v1（成員 A）

> 產出日：2026-07-21。本份供 Day 1–2 合約審查會使用：所有需要 B 回簽的決定都標了【待審】。
> 資料來源：張的技能圖譜交接包（skills / occupations / occupation_skills）＋ JL 的爬蟲交接包（career_knowledge / jobs_all / salary_stats）。

## 一、交付物

| 檔案 | 內容 | 驗收 |
|---|---|---|
| `fixtures/vocab/skills_v1.json` | 110 條 CanonicalSkill | 80–120 ✓、id 唯一 ✓ |
| `fixtures/vocab/skills_v1.provenance.json` | 逐條血緣（層別、張圖譜比對、市場頻率）——非合約側檔 | — |
| `fixtures/kb_seed/kb_entries.v1.json` | 42 條 KBEntry（job_skill 22／career_path 13／industry 7，含原 4 條手寫種子） | 30–50 ✓、type 三值 ✓ |
| `app/pipeline/vocab.py` | 載入器＋alias 精確比對索引（W2 正規化器第一階段直接用） | 「可被程式載入」✓ |
| `tests/test_vocab.py` | 9 條驗收測試（併入 CI，`pytest` 全套 20 passed） | ✓ |
| `tools/build_vocab.py`、`tools/build_kb_seed.py` | 產生器；爬蟲資料增量後可重跑，輸出決定性 | — |

MockData 四段經歷 tags 覆蓋：**15/15 實例全數命中**（門檻 10/12）。命中依賴的正規化規則：NFKC、╱／統一為 /、去空白、小寫。

## 二、詞彙表構成（110 條）

| 層 | 條數 | 來源與取法 |
|---|---|---|
| L0 精選種子 | 22 | 保證 MockData 9 tag 與核心程式/資料技能（Python、SQL、機器學習…）必收，不靠頻率碰運氣 |
| L1 O\*NET | 35 | 張圖譜全部 35 條 O\*NET 可轉移技能，自帶 name_en 與 onet_code |
| L2 UCAN | 22 | 掛在 ITC×4／MKC-56·58／BAC-16 途徑上的 UCAN 職能，權重排序、濾掉句子型長名 |
| L3 市場 | 36 | 科技/數位 27 職類的 job_skill 百分比（≥20%）＋科技業職缺 requiredSkills 頻次（≥9），黑名單濾門市/物流/庶務 |

## 三、【待審】三個內嵌決定

1. **skill_id 策略**（Day 1–2 議題一的實作提案）：能與張圖譜精確比對者沿用權威 ID `sk:{hash}`（67 條），對不上者鑄 `skm:{sha1[:10]}`（43 條，決定性）。顯示名由我方定，張的原名進 aliases——ID 管跨組對齊，名稱管呈現。
2. **變體合併表**（`build_vocab.py` 的 `MERGE_DISPLAY`）：MySQL/PostgreSQL/MS SQL 併入 SQL、GitHub 併入 Git、Photoshop 併入 Adobe Photoshop 等。合併對差集計算有直接影響（會 MySQL 視同滿足「需要 SQL」），請逐條過。
3. **article 型 164 條刻意未轉**：type 枚舉未含 article（合約 #3，且是 Atlas filter 欄位）＋著作權限制（僅供檢索、生成須改寫附出處）。提案：Day 1–2 決議是否擴枚舉；若擴，W2 我再補 article 轉檔（含 url 保留進 metadata）。

## 四、已知限制與 W2 掛鉤

- `ucan_code` 全空：張的資料無逐技能 UCAN 代碼（代碼在途徑層），依 schema 註解逐步補。
- 概念粒度重疊未強行合併（如 溝通協調／溝通能力／口語表達 並存）——圖譜本身視為不同節點，W2 正規化上線後看殘留區再議。
- job_skill 條目樣本數小（部分職類 n=5–9），content 已如實揭露 jobCount；職缺增量後重跑 `build_kb_seed.py` 會自動更新。
- `FakeRetriever` 換餵 v1 檔只要改一行 seed_path，屬 B 的呼叫面，未經同意先不動。
- 薪資 industry 條目為在職者統計口徑，與職缺開價不同，content 內已註明（對應 JL 交接文件的提醒）。

## 五、重跑方式

```bash
python tools/build_vocab.py \
  --zhang-skills <path>/skills.jsonl \
  --zhang-occupations <path>/occupations.jsonl \
  --zhang-edges <path>/occupation_skills.jsonl \
  --career-knowledge <path>/career_knowledge.jsonl \
  --jobs <path>/jobs_all.jsonl

python tools/build_kb_seed.py \
  --career-knowledge <path>/career_knowledge.jsonl \
  --salary <path>/salary_stats.jsonl \
  --zhang-occupations <path>/occupations.jsonl \
  --zhang-edges <path>/occupation_skills.jsonl \
  --zhang-skills <path>/skills.jsonl

pytest tests/ -q   # 應為 20 passed
```
