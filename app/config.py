"""設定。附極簡 .env 載入(無第三方依賴):存在 .env 就逐行讀 KEY=VALUE。"""
import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.split("#")[0].strip())


class Settings:
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")                 # 全域預設(建議 gpt-4o-mini)
    llm_model_extract: str = os.getenv("LLM_MODEL_EXTRACT", "")  # 擷取專用(建議 gpt-4o;空=用預設)
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "bge-m3")


settings = Settings()
