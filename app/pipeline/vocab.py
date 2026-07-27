"""詞彙表載入（成員 A）。W1 驗收點：「詞彙表可被程式載入」。
W2 的 VocabNormalizer 直接吃這裡的 alias 索引做第一階段精確比對。
"""
from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

from app.schemas.domain import CanonicalSkill

VOCAB_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "vocab" / "skills_v1.json"


def norm_key(s: str) -> str:
    """alias 比對鍵：NFKC → 斜線變體統一 → 去空白 → 小寫。
    與 tools/build_vocab.py 的 norm() 同義，兩邊要一起改。"""
    s = unicodedata.normalize("NFKC", s or "")
    for ch in ("╱", "／", "\\"):
        s = s.replace(ch, "/")
    return "".join(s.split()).lower()


@lru_cache(maxsize=1)
def load_vocabulary(path: Path = VOCAB_PATH) -> tuple[CanonicalSkill, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(CanonicalSkill.model_validate(e) for e in raw)


@lru_cache(maxsize=1)
def alias_index(path: Path = VOCAB_PATH) -> dict[str, CanonicalSkill]:
    """norm_key(名稱或任一別名) → CanonicalSkill。W2 正規化第一階段用。"""
    index: dict[str, CanonicalSkill] = {}
    for skill in load_vocabulary(path):
        for name in (skill.name_zh, skill.name_en, *skill.aliases):
            if name:
                index.setdefault(norm_key(name), skill)
    return index


def lookup(raw_skill: str, path: Path = VOCAB_PATH) -> CanonicalSkill | None:
    """精確比對（正規化後）。對不上回 None——W2 起交給 embedding 最近鄰接手。"""
    return alias_index(path).get(norm_key(raw_skill))
