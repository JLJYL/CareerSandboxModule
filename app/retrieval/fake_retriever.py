"""FakeRetriever:成員 B 在 A 的真檢索完成前的替身。
讀 fixtures/kb_seed,以「查詢字串包含技能/標題關鍵字」的天真命中計分。
實作 Retriever Protocol → 第 2 週換 ChromaRetriever 時呼叫端零改動。"""
import json
from pathlib import Path
from app.schemas.domain import KBEntry, RetrievedChunk

_SEED = Path(__file__).resolve().parents[2] / "fixtures" / "kb_seed" / "kb_entries.sample.json"


class FakeRetriever:
    def __init__(self, seed_path: Path = _SEED):
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        self._entries = [KBEntry.model_validate(e) for e in raw]

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        scored = []
        for e in self._entries:
            hits = sum(1 for s in e.skills if s in query) + (1 if e.title in query else 0)
            if hits:
                scored.append(RetrievedChunk(entry=e, score=float(hits)))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:k] or [RetrievedChunk(entry=e, score=0.0) for e in self._entries[:k]]
