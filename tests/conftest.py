"""pytest 全域夾具:測試一律走 golden/Fake 模式——快、免費、確定性。
真 LLM 與真模型的驗證屬於 scripts/(try_extraction、batch_eval),不屬於 pytest。
效果:即使開發機 .env 有金鑰,pytest 也絕不打真 API、絕不載 bge-m3。"""
import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "")
