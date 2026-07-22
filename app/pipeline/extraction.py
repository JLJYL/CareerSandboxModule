"""經歷擷取（成員 B,第 1 週主戰場）。
TODO: 實作 LlmExtractor(Extractor Protocol):
  1. prompt 強制 JSON schema 輸出(ExtractedExperience 陣列)
  2. 用 fixtures/samples 的真實履歷迭代品質——這是全案品質上限
  3. category 先照 LLM 判斷,正規化階段對齊四類
"""
