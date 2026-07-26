"""LLM provider 抽象。決策:一律走 OpenAI 相容介面,換供應商只換 base_url/model。"""
import json
import urllib.error
import urllib.request
from typing import Protocol

from app.config import settings


class LLMUnavailable(Exception):
    """LLM 呼叫失敗(網路/金鑰/配額)。endpoint 轉統一錯誤格式,前端保險絲據此退 Mock。"""


class LLMProvider(Protocol):
    def complete(self, system: str, user: str, force_json: bool = False) -> str: ...


class FakeLLM:
    """骨架/測試用:回傳固定字串。"""
    def __init__(self, canned: str = "{}"):
        self.canned = canned

    def complete(self, system: str, user: str, force_json: bool = False) -> str:
        return self.canned


class OpenAICompatibleLLM:
    """真實作:純標準庫打 {base_url}/chat/completions,零額外依賴。
    設定來源 .env:LLM_BASE_URL(如 https://api.openai.com/v1)/LLM_API_KEY/LLM_MODEL。"""

    def __init__(self, timeout_s: int = 60):
        if not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
            raise LLMUnavailable("LLM 未設定:請在 .env 填 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL")
        self._url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout_s

    def complete(self, system: str, user: str, force_json: bool = False) -> str:
        body = {
            "model": settings.llm_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.2,
        }
        if force_json:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {settings.llm_api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as e:
            raise LLMUnavailable(f"LLM 呼叫失敗: {e}") from e
