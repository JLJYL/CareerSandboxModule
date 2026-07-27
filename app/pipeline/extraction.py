"""經歷擷取（成員 B 第 1 週主戰場）——LlmExtractor 實作 Extractor Protocol。

流程：SYSTEM_PROMPT + 敘述 → LLM(force_json) → 解析驗證 → 失敗重試一次 → 清洗鐵律。
品質責任分工：本檔管「機械正確」（合法 JSON、欄位齊、證據句真的在原文裡）；
「內容好不好」靠 prompts/extraction.py 的迭代——那是你這週的工作。
"""
import json
import re

from app.pipeline.textrules import sanitize_display_text
from app.prompts.extraction import RETRY_SUFFIX, SYSTEM_PROMPT, build_user_prompt
from app.providers.llm import LLMProvider
from app.schemas.domain import ExtractedExperience

_LEGAL_CATEGORIES = {"社團", "工作", "競賽", "學業"}

_WS = re.compile(r"\s+")


def _squash_ws(s: str) -> str:
    """去除所有空白(半形/全形/換行)。引句比對只在「有內容的字元」上逐字嚴格:
    條列輸入的隱形行尾空白與換行不該誤殺誠實的引句;
    但任何字元級改寫(兩→2、增刪標點、縫合時補逗號)仍一律退稿。"""
    return _WS.sub("", s)


class ExtractionError(Exception):
    """擷取徹底失敗（重試後仍不合規）。endpoint 會轉成統一錯誤格式。"""


def _parse_payload(raw: str, full_input: str) -> list[ExtractedExperience]:
    """把 LLM 輸出變成領域模型；任何不合規都拋 ValueError 讓上層決定重試。"""
    text = raw.strip()
    if text.startswith("```"):  # 防 markdown 圍欄（prompt 已禁，但 LLM 偶爾手滑）
        text = text.strip("`")
        text = text[text.find("{"):]
    data = json.loads(text)
    items = data.get("experiences")
    if not isinstance(items, list) or not items:
        raise ValueError("缺 experiences 陣列或為空")

    out: list[ExtractedExperience] = []
    for it in items:
        exp = ExtractedExperience.model_validate(it)
        if exp.category not in _LEGAL_CATEGORIES:
            raise ValueError(f"category 不合法: {exp.category}")
        if _squash_ws(exp.source_quote) not in _squash_ws(full_input):
            # 鐵則 2：證據句必須逐字存在於輸入——防捏造的機械防線
            raise ValueError(f"source_quote 不是輸入子字串: {exp.source_quote[:30]}")
        exp.title = sanitize_display_text(exp.title)
        exp.description = sanitize_display_text(exp.description)
        exp.raw_skills = [sanitize_display_text(s) for s in exp.raw_skills]
        out.append(exp)
    return out


class LlmExtractor:
    """實作 contracts.protocols.Extractor。"""

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    def extract(self, narratives: list[str]) -> list[ExtractedExperience]:
        user_prompt = build_user_prompt(narratives)
        full_input = "\n".join(narratives)

        raw = self._llm.complete(SYSTEM_PROMPT, user_prompt, force_json=True)
        try:
            return _parse_payload(raw, full_input)
        except (ValueError, json.JSONDecodeError) as first_err:
            # 重試一次：把失敗原因回饋給模型
            raw2 = self._llm.complete(
                SYSTEM_PROMPT,
                user_prompt + RETRY_SUFFIX + f"\n上次的具體問題:{first_err}",
                force_json=True,
            )
            try:
                return _parse_payload(raw2, full_input)
            except (ValueError, json.JSONDecodeError) as second_err:
                raise ExtractionError(
                    f"重試後仍不合規: {second_err}（首次: {first_err}）"
                ) from second_err