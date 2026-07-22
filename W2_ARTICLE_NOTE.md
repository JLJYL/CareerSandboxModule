# W2 增量：article 入庫（決議通知 §一-5 的落地）

> 2026-07-22。本包是 article 擴枚舉決議的程式面落地。生效前提：決議通知的異議窗口（7/24 18:00）內無人反對；先 commit 上分支沒有問題，合併時點自行掌握。

## 包內三個檔（覆蓋兩個、新增一個）

| 檔案 | 動作 | 內容 |
|---|---|---|
| `tools/build_kb_seed.py` | 覆蓋 | 新增文章切塊轉檔：164 篇 → 544 塊，每塊約 900 字、於段落與句號邊界切分；輸出獨立檔案，種子庫 42 條完全不動 |
| `fixtures/kb_seed/kb_entries.articles.v1.json` | 新增 | 544 條 `article` 型 KBEntry，ID 用 `kb_a{n}` 前綴與種子庫脫鉤；每塊 metadata 帶 `url / source / sourceId / part / parts / tags` |
| `tests/test_vocab.py` | 覆蓋 | type 白名單擴為四值＋新增 4 條 article 驗收測試；全套應為 **24 passed** |

## 還要手動改一處：CONTRACTS.md 第 3 節

type 那一列，改前：

> 對齊 03 的值：`job_skill` / `career_path` / `industry`（kb_seed 已同步）

改後：

> 四值：`job_skill` / `career_path` / `industry` / `article`（article 為 W2 決議擴充：第三方文章僅供檢索，生成引用必改寫並附 `metadata.url` 出處）

## 套用步驟

```bash
git checkout main && git pull
git checkout -b feat/a-articles        # 若 W1 的 PR 還沒合併，直接沿用原分支也行
# 覆蓋兩檔、放入新檔、改 CONTRACTS.md 那一列
pytest tests/ -q                        # 24 passed
git add -A && git commit -m "feat(a): article 入庫（164 篇切 544 塊）＋type 枚舉擴為四值"
git push -u origin feat/a-articles
```

## 設計決定備忘（PR 描述可直接抄）

- **獨立檔案、獨立前綴**：article 不混進 42 條種子庫，`kb_a` 編號與 `kb_` 脫鉤——種子庫重生成不會讓文章 ID 飄移，W1 的驗收測試一條不用改。
- **切塊理由**：文章中位 2,435 字、最長 7,224 字，整篇一個向量檢索粒度太粗；切成約 900 字塊（塊長中位 847、上限驗證 ≤1,400），一篇多塊以 `part/parts` 標序。
- **驚嘆號鐵律的邊界**：該鐵律管的是我們生成的展示文字；article 是來源語料（標題本來就有驚嘆號），豁免，測試註解已寫明。
- **著作權鐵律**（給 B 的 prompt 必須掛死）：檢索到 `type=article` 的內容，生成時必須改寫、必須附 `metadata.url` 出處，禁止原文照貼。
- **已知現況**：104 職場力有少量離題文章（如統一發票號碼），未過濾——語意檢索自然不會撈到它們，之後要清再依 tags 加黑名單。
- **通知資料庫組**：type 正式定為四值（決議通知已預告過），Atlas 索引定義不用改。
- **W2 銜接**：這 544 塊就是 bge-m3 embedding 的主要輸入，寫入 Atlas 時與種子庫 42 條同批算向量。
