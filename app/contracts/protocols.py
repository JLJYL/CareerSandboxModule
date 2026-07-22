"""兩人之間的國界：B 的程式碼只透過這些介面呼叫 A 的東西。
Day 1 下午凍結;改動 = 兩人同意 + 改 fixtures + 跑合約測試。

分工:
  Extractor            → 成員 B(LLM 擷取)
  Normalizer / Retriever / Scorer → 成員 A(資料與檢索)
"""
from typing import Protocol
from app.schemas.domain import (
    CanonicalSkill, ExtractedExperience, FitResult, JobRequirement,
    RetrievedChunk, UserProfile,
)


class Extractor(Protocol):
    def extract(self, narratives: list[str]) -> list[ExtractedExperience]:
        """口語敘述 → 結構化經歷草稿（含證據句）。強制 JSON schema 輸出。"""
        ...


class Normalizer(Protocol):
    def normalize(self, raw_skill: str) -> CanonicalSkill | None:
        """原始技能字串 → 標準詞彙。對不上回 None（進 profile.raw_tags 殘留區）。"""
        ...


class Retriever(Protocol):
    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        """語意檢索知識庫。第 2 週前用 FakeRetriever 頂著。"""
        ...


class Scorer(Protocol):
    def score(self, profile: UserProfile, job: JobRequirement) -> FitResult:
        """確定性適配分數：標籤覆蓋率加權 + 語意相似度。LLM 只寫解釋，不給分。"""
        ...
