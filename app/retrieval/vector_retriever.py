"""VectorRetriever（成員 A，W2）：零原生依賴的精確向量檢索，換掉 FakeRetriever。

原規劃用 Chroma；其 1.x 的 Rust 核心在 Windows + Python 3.13 觸發 access violation
（原生層崩潰，非本專案邏輯問題）。凍結的是 Retriever Protocol，不是廠牌——
在 587 條這個規模，暴力精確餘弦本來就優於 HNSW 近似（精確、決定性、零依賴），
而正式店面 W3 落 MongoDB Atlas Vector Search，本地索引只是過渡期鷹架。

效能：有 numpy 走矩陣運算（毫秒級）；沒有退純 Python（單查詢數十毫秒）——
CI 與任何平台都跑得動。持久化存 JSON，內含 provider 名與 id 清單，
換 embedding 實作或 KB 內容變動（id 集合改變）會自動重建。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.providers.embeddings import EmbeddingProvider
from app.schemas.domain import KBEntry, RetrievedChunk

try:  # numpy 有就加速，沒有也能活——刻意不進 requirements
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

_KB_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "kb_seed"
DEFAULT_SEEDS = (_KB_DIR / "kb_entries.v1.json",
                 _KB_DIR / "kb_entries.articles.v1.json")


class VectorRetriever:
    def __init__(self, embedding: EmbeddingProvider,
                 seed_paths=DEFAULT_SEEDS,
                 persist_path: Path | None = None,
                 rebuild: bool = False):
        self._embedding = embedding
        self._entries: dict[str, KBEntry] = {}
        for p in seed_paths:
            for raw in json.loads(Path(p).read_text(encoding="utf-8")):
                e = KBEntry.model_validate(raw)
                self._entries[e.id] = e
        self._ids = sorted(self._entries)              # 固定順序 ⇒ 決定性

        self._vecs: list[list[float]] | None = None
        if persist_path and Path(persist_path).exists() and not rebuild:
            cached = json.loads(Path(persist_path).read_text(encoding="utf-8"))
            if (cached.get("provider") == type(embedding).__name__
                    and cached.get("ids") == self._ids):
                self._vecs = cached["vectors"]
        if self._vecs is None:
            docs = [f"{self._entries[i].title}\n{self._entries[i].content}"
                    for i in self._ids]
            self._vecs = []
            for s in range(0, len(docs), 128):
                self._vecs.extend(self._embedding.embed(docs[s:s + 128]))
            if persist_path:
                p = Path(persist_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(dict(
                    provider=type(embedding).__name__, ids=self._ids,
                    vectors=[[round(x, 6) for x in v] for v in self._vecs])),
                    encoding="utf-8")

        if _np is not None:
            self._mat = _np.asarray(self._vecs, dtype=_np.float32)
            norms = _np.linalg.norm(self._mat, axis=1)
            norms[norms == 0] = 1.0
            self._mat_norms = norms
        else:  # pragma: no cover
            self._norms = [(sum(x * x for x in v) ** 0.5) or 1.0 for v in self._vecs]

    # ------------------------------------------------ Retriever Protocol
    # where 為擴充參數：{"type": "article"} 或 metadata 的 source / industry 等值過濾。
    def search(self, query: str, k: int = 5,
               where: dict | None = None) -> list[RetrievedChunk]:
        sims = self._similarities(self._embedding.embed([query])[0])
        idxs = range(len(self._ids))
        if where:
            idxs = [i for i in idxs
                    if self._match(self._entries[self._ids[i]], where)]
        ranked = sorted(idxs, key=lambda i: (-float(sims[i]), self._ids[i]))[:k]
        return [RetrievedChunk(entry=self._entries[self._ids[i]],
                               score=float(sims[i])) for i in ranked]

    def count(self) -> int:
        return len(self._ids)

    # ------------------------------------------------ 內部
    def _similarities(self, qv: list[float]):
        if _np is not None:
            q = _np.asarray(qv, dtype=_np.float32)
            qn = float(_np.linalg.norm(q)) or 1.0
            return (self._mat @ q) / (self._mat_norms * qn)
        qn = (sum(x * x for x in qv) ** 0.5) or 1.0  # pragma: no cover
        return [sum(a * b for a, b in zip(v, qv)) / (n * qn)
                for v, n in zip(self._vecs, self._norms)]

    @staticmethod
    def _match(e: KBEntry, where: dict) -> bool:
        for field, want in where.items():
            val = e.type if field == "type" else str(e.metadata.get(field, ""))
            if str(val) != str(want):
                return False
        return True
