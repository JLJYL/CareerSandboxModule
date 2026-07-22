"""Embedding provider 抽象。決策:bge-m3,1024 維——此數字之後寫進 Atlas 向量索引。"""
from typing import Protocol

EMBEDDING_DIM = 1024  # bge-m3;換模型必須同步改這裡與 Atlas index,屬合約變更


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedding:
    """確定性假向量(hash-based),讓檢索層可以在沒有模型時被測試。"""
    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = abs(hash(t))
            out.append([((h >> (i % 32)) % 997) / 997.0 for i in range(EMBEDDING_DIM)])
        return out


class BgeM3Embedding:
    """真實作(Phase 2)。TODO(成員 A): FlagEmbedding 載入 bge-m3。"""
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Phase 2: 成員 A 實作")
