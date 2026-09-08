# 技能詞彙表

## 正本在這裡

`fixtures/vocab/skills_v1.json` 是產生物,**不要手動編輯**。

    產生器   tools/build_vocab.py
    正本     CareerSandboxModule（這個 repo）
    鏡射     CareerSandboxInterview/fixtures/vocab/skills_v1.json（唯讀）

★ 面試 repo 那份是**唯讀鏡射**,不是另一份資料。改詞彙表一律改這裡再同步過去。

為什麼要鏡射而不是讓面試 repo 引用:B 要覆核黃金集就得跑評測,跑評測就要
詞彙表。要求他 checkout 兩個 repo,那個覆核大概不會發生。代價是同步要靠人,
所以兩邊都要記得換。

## 重跑

    python tools/build_vocab.py \
      --zhang-skills data/zhang/skills_cleaned.jsonl \
      --zhang-occupations data/zhang/occupations.jsonl \
      --zhang-edges data/zhang/occupation_skills.jsonl \
      --career-knowledge <爬蟲repo>/data/clean/career_knowledge.jsonl \
      --jobs data/jobs_all.jsonl \
      --target 286 \
      --golden-skills data/golden_skill_keys.json \
      --out fixtures/vocab/skills_v1.json

`--out` 決定 provenance 的檔名(跟著走),改檔名時兩個要一起改。

### 輸入從哪來

    data/zhang/*.jsonl              已進版控（5.4MB，.gitignore 走白名單）
    data/jobs_all.jsonl             本機，未進版控（爬蟲產出）
    data/golden_skill_keys.json     面試黃金集的標記鍵清單，見下
    career_knowledge.jsonl          ★ 外部相依，在爬蟲 repo
                                      careersandbox-crawler/data/clean/

`golden_skill_keys.json` 可以從面試 repo 的黃金集重新產生:

    python -c "import json,glob;json.dump(sorted({k for f in glob.glob('<interview-repo>/fixtures/golden/interview/ivw-*.json') for k in json.load(open(f,encoding='utf-8'))['labels']['skills']}),open('data/golden_skill_keys.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)"

黃金集新增案例之後要重跑這行,不然 L5 覆蓋層會漏掉新標記鍵。

## 六個層別

    L0_curated              精選種子。保證 MockData 9 個 tag 命中
    L1_onet                 O*NET 可轉移技能（自帶 name_en + onet_skill_id）
    L2_ucan                 掛在目標職涯途徑（ITC/MKC/BAC）上的 UCAN 職能
    L3_market               科技職類 job_skill 聚合 + 科技業職缺 requiredSkills 頻次
    L4_merge_alias          合併表的鍵位補掛（Photoshop → Adobe Photoshop 之類）
    L5_interview_coverage   黃金集標到但排不進 L3 的長尾

`--target` 只放大 L3,前三層不動。實際產出會少於 target,因為 L3 的入場條件
(`pct >= 20`、`tech_freq >= 9`、`blocked()`)限住了候選池。

## 兩種過濾不要混

    BLOCK_KEYWORDS   「這個職能不在目標職涯」 → 產品範圍判斷，**只用於 L3**
    is_spec_entry    「這根本不是技能」       → 資料品質判斷，所有層適用

L5 曾經誤用 `BLOCK_KEYWORDS`,擋掉三個黃金集標記鍵(中文打字、
櫃檯門市接待與需求服務、電話接聽與人員接待事項)。後兩者是 104 上的真職能,
出現在黃金集是因為會計系履歷配到行政助理職缺——使用者真的會遇到這種 JD。

★ 混用的後果是一個壞性質:**黑名單越保守,指標看起來越好**。被擋的技能會從
計分裡排除,而被擋的往往是系統本來就處理得比較差的那一批。加一條黑名單關鍵字,
覆蓋率警告少一條、指標微微上升——那是難題被移出考卷,不是變好,而且它是沉默的。

## 改了詞彙表之後

1. 兩個 repo 都要換(正本 + 鏡射),`skills_v1.provenance.json` 一起換
2. `run_golden_pairs.py` 要過(推薦那條線的回歸)
3. 面試 repo 的 `tools/interview_eval.py` 要重跑,**baseline 要重凍**
4. commit 訊息寫明指標變化的成因。覆蓋率變動會讓計分範圍跟著變,
   不寫的話下次有人比對回歸會誤判成退步
