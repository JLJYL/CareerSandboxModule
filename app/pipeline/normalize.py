"""職能標籤正規化（成員 A,第 2 週）。
TODO: 實作 VocabNormalizer(Normalizer Protocol):
  1. 詞彙表載入(第 1 週產出的 CanonicalSkill 清單)
  2. alias 精確比對 → embedding 最近鄰(門檻以下回 None)
  3. 低信心批次留給 LLM 覆核 hook
"""
