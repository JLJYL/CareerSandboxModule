"""展示文字鐵律(01 文件 D12):禁驚嘆號、去 AI 味。
sanitize 用在 LLM 產出的「展示」欄位;source_quote 是逐字證據,絕不清洗。"""
import re

_BANNED_PATTERNS = [r"致力於", r"豐富的經驗", r"積極(?:主動)?地"]


def sanitize_display_text(text: str) -> str:
    """驚嘆號硬移除(全形換句號、半形換句點),樣板詞不硬改但可偵測。"""
    return text.replace("！", "。").replace("!", ".")


def ai_flavor_hits(text: str) -> list[str]:
    """回傳命中的樣板詞——開發腳本用來提醒 B 調 prompt,不在 runtime 硬擋。"""
    return [p for p in _BANNED_PATTERNS if re.search(p, text)]
