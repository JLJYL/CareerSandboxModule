"""型錄生成器的市場骨架蒸餾——純函式,免資料檔。"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "build_careers", Path(__file__).resolve().parents[1] / "tools" / "build_careers.py")
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)


def test_market_skeleton_takes_frequent_skills():
    jobs = [{"requiredSkills": ["Excel", "Word", "溝通"]},
            {"requiredSkills": ["Excel", "Outlook"]},
            {"requiredSkills": ["Excel", "Word"]},
            {"requiredSkills": None}]
    out = bc.market_skeleton(jobs)
    assert out[0] == "Excel" and "Word" in out          # 頻率排序
    assert "溝通" not in out and "Outlook" not in out    # 只出現 1 次,未達門檻
    assert bc.market_skeleton([]) == []                  # 零職缺 → 空,交閘門
