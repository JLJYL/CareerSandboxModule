# W2 交付：檢索與計分（成員 A）— 收官版

> 2026-07-26。取代先前所有 W2 note。W2 三塊全數交付並在 A 本機以真模型驗收：
> `pytest` **36 passed**；bge-m3 真索引 587 條建置 9 分鐘、查詢秒回；
> 檢索 top-5 人工覆核合理（驗收紀錄見文末）。

## 三個工程決定（實戰換來的，PR 描述照抄）

1. **檢索引擎：Chroma → 自製 `VectorRetriever`。** chromadb 1.x 的 Rust 核心在 Windows + Py3.13 觸發 access violation。凍結的是 Retriever Protocol 不是廠牌；587 條規模用零依賴精確餘弦（numpy 可選加速），比 HNSW 近似更精確、決定性、跨平台。W3 正式店面照舊 Atlas Vector Search，`fixtures/atlas/vector_index.json` 不受影響。
2. **移除 sentencepiece。** 其原生擴充在 Windows + Py3.13 匯入即 access violation；bge-m3 的 tokenizer 走 Rust 快速版（吃 `tokenizer.json`）即可，sentencepiece 純屬多餘的雷。**已裝者必須 `pip uninstall sentencepiece -y`。**
3. **embedding：FlagEmbedding → 原生 transformers。** FlagEmbedding 新版與 transformers 4.x 隔著 `torch_dtype→dtype` 改名互踩（TypeError），依賴樹又大。dense 向量本體只是「XLM-R 編碼 → 取 CLS → L2 正規化」，`BgeM3Embedding` 直接用 torch + transformers 實作二十行。全系統所有向量（KB、查詢、未來 Atlas 寫入）出自同一實作，內部一致性完整。

## 目前狀態的檔案

| 檔案 | 內容 |
|---|---|
| `app/providers/embeddings.py` | `FakeEmbedding`（hashlib 決定性，測試/CI 用）＋ `BgeM3Embedding`（transformers 原生：CLS pooling + L2 normalize，CUDA 自動 fp16、CPU fp32，批次進度輸出） |
| `app/pipeline/normalize.py` | `VocabNormalizer` 三段式：alias 精確比對 → embedding 最近鄰（門檻 0.62）→ `residuals()` 殘留區＝LLM 批次覆核 hook |
| `app/retrieval/vector_retriever.py` | Retriever Protocol 實作；587 條 KB、type/source/industry 等值過濾、JSON 持久化（含 provider 名，換實作或 KB 變動自動重建；快取為整包重算，KB 長大時重跑一次 `--rebuild` 即可） |
| `app/pipeline/scorer.py` | `WeightedScorer`：覆蓋率加權 0.65＋語意 0.35；raw_tag 折扣 0.6；JD 無 required_skills 退化純語意 |
| `tests/test_w2_retrieval.py` | 12 條驗收（CI 用 Fake，不需模型） |
| `tools/build_kb_index.py` | 本機建索引＋煙霧查詢；索引存 `data/kb_index.json`（`.gitignore` 需含 `data/`） |
| `requirements.txt` | 無新增依賴 |
| `requirements-ml.txt` | `torch>=2.2`、`transformers>=4.44,<5`、`huggingface_hub<1.0`——**不含** FlagEmbedding 與 sentencepiece（見決定 2、3） |

## 環境安裝指南（給 B——照走十分鐘，別重演 A 的三天）

**最快路徑（強烈建議）**：跟 A 拿模型快取。把 A 機器的
`C:\Users\<A>\.cache\huggingface\hub\models--BAAI--bge-m3` 整個資料夾壓縮傳給你，
解到你機器**同層路徑**（`C:\Users\<你>\.cache\huggingface\hub\`），下載這關直接跳過。

自行下載才照下面走（A 的網路實測 2.3GB 約一小時、會反覆斷線續傳）：

1. Windows 設定 → 開發人員專用 → **開發人員模式開啟**（否則 symlink 會炸 WinError 1314）。
2. `pip install -r requirements.txt -r requirements-ml.txt`，然後 **`pip uninstall sentencepiece -y`**（transformers 可能連帶裝了它）。
3. 同一個 cmd 視窗：

```bat
set HF_HUB_DISABLE_XET=1
huggingface-cli download BAAI/bge-m3 pytorch_model.bin sparse_linear.pt sentencepiece.bpe.model tokenizer.json special_tokens_map.json 1_Pooling/config.json config.json tokenizer_config.json modules.json config_sentence_transformers.json colbert_linear.pt
```

（指名檔案、**不要用萬用字元**——`--exclude` 接多個樣式會被解析成別的意思，A 已替大家踩過。紅色 retry 訊息可無視，進度條有動就好；行程死了重跑同一行續傳。）

4. 執行時一律帶 `set HF_HUB_OFFLINE=1`，只吃本機快取、不碰網路。

Python 3.13 在上述組合下**可用**（A 機實證）；仍出原生崩潰再退 3.12 venv。

## 本機驗收（04 文件 W2 自檢）——A 已完成

```bat
pytest tests/ -q                                    :: 36 passed
set HF_HUB_OFFLINE=1
python tools\build_kb_index.py --real --rebuild     :: 587 條 / 534s
python tools\build_kb_index.py --real --query "..." :: top-5 人工覆核
```

驗收紀錄（2026-07-26，查詢「資料分析師需要什麼技能」）：top1 `kb_001 資料分析師的核心技能`（0.773）；top2–4 為「數據分析師面試作品集」同篇文章三個切塊連號命中（0.674／0.641／0.634）；top5 相鄰職類資訊助理（0.589）。切塊＋檢索鏈如設計運作。

## 給 B 的兩個接點

1. **換注入點**（W2 週中交棒）：把建構 `FakeRetriever()` 的那行換成
   `VectorRetriever(embedding=BgeM3Embedding(), persist_path=Path("data/kb_index.json"))`，
   呼叫端零改動。文章切塊會以 `（i/n）` 連號出現在檢索結果，生成端請以
   `metadata.sourceId` 去重、同篇只引一次並附 `metadata.url` 出處。
2. **殘留區**：`normalizer.residuals()` 是你的 LLM 批次覆核資料源，
   覆核確認的對應回填詞彙表 aliases（改 build_vocab 常數重跑），殘留逐版收斂。

## 三個【待校準】參數（W3 黃金測試集回歸定案）

正規化門檻 `0.62`、計分權重 `0.65/0.35`、raw_tag 折扣 `0.6`。校準素材：
跑一批 jobs_all 的 requiredSkills 過正規化器，看 `residuals()` 裡 sim 落在
0.5–0.62 的樣本該不該收。
