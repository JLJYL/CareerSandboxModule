"""W1 交付驗收測試（成員 A）：詞彙表 v1 ＋ 種子知識庫 v1。
04 文件的週五自檢標準在這裡變成可執行的合約：
  - 詞彙表可被程式載入、80–120 條、id 唯一
  - MockData 四段經歷的 tags 至少 10/12 對得上詞彙表
  - kb_seed 30–50 條、type 嚴守三值、驚嘆號鐵律（CONTRACTS #15）
"""
import json
from collections import Counter
from pathlib import Path

from app.pipeline.vocab import load_vocabulary, lookup
from app.schemas.domain import KBEntry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
KB_V1 = FIXTURES / "kb_seed" / "kb_entries.v1.json"

# MockData.kt 四段經歷的 tags 原文（含重複，共 15 個實例；驗收門檻 10/12 以實例計）
MOCKDATA_TAG_INSTANCES = [
    "領導", "內容創作", "數據分析", "簡報",          # e1 校內社團行銷組長
    "數據分析", "SQL", "報表", "Excel",              # e2 電商公司資料分析實習
    "數據分析", "策略", "簡報", "領導",              # e3 全國商業個案分析競賽
    "SQL", "全端", "Excel",                          # e4 資料庫系統課程專題
]


# ---------------------------------------------------------------- 詞彙表

def test_vocab_loads_and_size():
    vocab = load_vocabulary()
    assert 80 <= len(vocab) <= 120


def test_vocab_ids_unique():
    ids = [s.skill_id for s in load_vocabulary()]
    assert len(ids) == len(set(ids))


def test_vocab_covers_mockdata_tags():
    hits = [t for t in MOCKDATA_TAG_INSTANCES if lookup(t) is not None]
    assert len(hits) >= 10, f"僅命中 {len(hits)}/15：{Counter(hits)}"


def test_vocab_no_exclamation_marks():
    for s in load_vocabulary():
        for text in (s.name_zh, s.name_en, *s.aliases):
            assert "!" not in text and "！" not in text


# ---------------------------------------------------------------- kb_seed v1

def _kb_entries():
    return json.loads(KB_V1.read_text(encoding="utf-8"))


def test_kb_v1_size_and_schema():
    entries = _kb_entries()
    assert 30 <= len(entries) <= 50
    for e in entries:
        KBEntry.model_validate(e)


def test_kb_v1_ids_unique_and_prefixed():
    ids = [e["id"] for e in _kb_entries()]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("kb_") for i in ids)


def test_kb_v1_types_legal():
    for e in _kb_entries():
        assert e["type"] in {"job_skill", "career_path", "industry"}


def test_kb_v1_lists_never_null():
    for e in _kb_entries():
        assert isinstance(e["skills"], list)          # 合約 #2：List 永不為 null


def test_kb_v1_no_exclamation_marks():
    for e in _kb_entries():
        for text in (e["title"], e["content"], *e["skills"]):
            assert "!" not in text and "！" not in text, e["id"]
