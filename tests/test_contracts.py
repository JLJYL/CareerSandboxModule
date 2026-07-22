"""合約測試:每份 golden JSON 必須通過對應凍結 schema。
誰改壞合約(schema 或 golden 任一邊),這裡當場變紅。"""
import json
from pathlib import Path

import pytest

from app.schemas.api import (
    CareerRecommendResponse, CustomizeResponse, JobFitOut,
    JobsFitAllResponse, MasterGenerateResponse, OverviewResponse,
)

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden"

CASES = [
    ("resume_master_generate", MasterGenerateResponse),
    ("career_recommend", CareerRecommendResponse),
    ("jobs_fit_all", JobsFitAllResponse),
    ("job_fit", JobFitOut),
    ("resume_customize", CustomizeResponse),
    ("resume_overview", OverviewResponse),
]


@pytest.mark.parametrize("name,model", CASES)
def test_golden_matches_schema(name, model):
    data = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    model.model_validate(data)


def test_career_category_legal_values():
    data = json.loads((GOLDEN / "career_recommend.json").read_text(encoding="utf-8"))
    for rec in data["recommendations"]:
        assert rec["category"] in {"數據", "產品", "設計", "學術"}
        assert isinstance(rec["matchScore"], int) and 0 <= rec["matchScore"] <= 100


def _all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _all_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_strings(v)


def test_no_exclamation_marks_anywhere():
    """01 文件 D12 反焦慮鐵律:全 app 展示文字禁用驚嘆號(目前 0 違規,守住)。
    任何進入 golden 的生成文字若帶 ! 或 ！,這裡直接紅燈。"""
    for f in GOLDEN.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for s in _all_strings(data):
            assert "!" not in s and "！" not in s, f"{f.name} 含驚嘆號: {s[:40]}"
