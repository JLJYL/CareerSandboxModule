"""LLM provider 抽象。決策:一律走 OpenAI 相容介面,換供應商只換 base_url/model。"""
from typing import Protocol


class LLMProvider(Protocol):
    def complete(self, system: str, user: str, force_json: bool = False) -> str: ...


class FakeLLM:
    """骨架/測試用:回傳固定字串。成員 B 第 1 週以真 LLM 取代(實作同一介面)。"""
    def __init__(self, canned: str = "{}"):
        self.canned = canned

    def complete(self, system: str, user: str, force_json: bool = False) -> str:
        return self.canned


class OpenAICompatibleLLM:
    """真實作(Phase 1)。TODO(成員 B): 讀 config 的 LLM_BASE_URL/KEY/MODEL,
    帶 response_format=json 支援,失敗拋 LLMUnavailable 讓端點回統一錯誤格式。"""
    def complete(self, system: str, user: str, force_json: bool = False) -> str:
        raise NotImplementedError("Phase 1: 成員 B 實作")
