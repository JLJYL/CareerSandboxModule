"""職能標籤正規化(成員 A,W2)。實作 Normalizer Protocol,三段式:
  1. alias 精確比對(app/pipeline/vocab.py 的索引,W1 已就位)
  2. embedding 最近鄰:對詞彙表所有表面形(名稱+別名,約 500 個)找餘弦最近鄰,
     門檻以上採納、以下進殘留區。門檻預設 0.62,需在真 bge-m3 上以殘留樣本校準。
  3. 殘留區 = LLM 批次覆核 hook:B 週期性拉 residuals() 做覆核,
     確認的對應補進詞彙表 aliases(改產生器常數重跑),殘留隨版本收斂。
"""
from __future__ import annotations

from pathlib import Path

from app.pipeline.vocab import VOCAB_PATH, alias_index, load_vocabulary, norm_key
from app.providers.embeddings import EmbeddingProvider
from app.schemas.domain import CanonicalSkill


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


class VocabNormalizer:
    def __init__(self, embedding: EmbeddingProvider | None = None,
                 vocab_path: Path = VOCAB_PATH, threshold: float = 0.62):
        self._vocab = load_vocabulary(vocab_path)
        self._alias = alias_index(vocab_path)
        self._by_id = {s.skill_id: s for s in self._vocab}
        self._embedding = embedding
        self._threshold = threshold
        self._surfaces: list[tuple[str, CanonicalSkill]] = []
        self._surface_vecs: list[list[float]] | None = None
        self._residuals: list[dict] = []

    # ------------------------------------------------ Normalizer Protocol
    def normalize(self, raw_skill: str) -> CanonicalSkill | None:
        raw = (raw_skill or "").strip()
        if not raw:
            return None
        hit = self._alias.get(norm_key(raw))                 # 第一段
        if hit:
            return hit
        if self._embedding is None:                          # 無模型:直接殘留
            self._residuals.append(dict(raw=raw, best_id=None, sim=0.0))
            return None
        self._ensure_vectors()                               # 第二段
        qv = self._embedding.embed([raw])[0]
        best_i, best_sim = max(
            ((i, cosine(qv, v)) for i, v in enumerate(self._surface_vecs)),
            key=lambda t: t[1])
        surface, skill = self._surfaces[best_i]
        if best_sim >= self._threshold:
            return skill
        self._residuals.append(dict(raw=raw, best_id=skill.skill_id,   # 第三段
                                    best_surface=surface, sim=round(best_sim, 4)))
        return None

    # ------------------------------------------------ 公用
    def display_name(self, skill_id: str) -> str:
        s = self._by_id.get(skill_id)
        return s.name_zh if s else skill_id

    def residuals(self) -> list[dict]:
        """LLM 覆核 hook 的批次來源(唯讀副本)。"""
        return list(self._residuals)

    def clear_residuals(self) -> None:
        self._residuals.clear()

    def _ensure_vectors(self) -> None:
        if self._surface_vecs is not None:
            return
        for s in self._vocab:
            for name in dict.fromkeys([s.name_zh, s.name_en, *s.aliases]):
                if name:
                    self._surfaces.append((name, s))
        self._surface_vecs = self._embedding.embed([n for n, _ in self._surfaces])
