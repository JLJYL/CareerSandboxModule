"""艦隊評測器的核心邏輯測試——persona 轉換與命中判定,免模型免 LLM。"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "fleet_eval", Path(__file__).resolve().parents[1] / "scripts" / "fleet_eval.py")
fleet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fleet)

PERSONA = {
    "personaId": "p001", "aboutMe": "我喜歡整理資料,想找可以分析數字的工作",
    "targetOccupation": "資料分析師",
    "skills": {"owned": ["Excel", "SQL"]},
    "experiences": [
        {"type": "part_time", "title": "門市打工", "period": "2025.07 - 2025.08"},
        {"type": "project", "title": "統計課專題", "period": ""},
    ],
}


def test_persona_to_request_shape():
    query, exps = fleet.persona_to_request(PERSONA)
    assert query == PERSONA["aboutMe"]                      # aboutMe 就是那句人話
    assert [e.category for e in exps] == ["工作", "學業"]    # type 對照表生效
    assert "Excel" in exps[0].tags and "SQL" in exps[0].tags  # owned 技能掛首段經歷


def test_target_reachability_and_hit():
    ids = {"data_analyst", "pm"}                                    # 測試自帶型錄,環境無關
    assert fleet.target_to_career("資料分析師") == "data_analyst"    # 第一層:對到定義
    assert fleet.target_reachable("資料分析師", ids) == "data_analyst"  # 第二層:且在型錄
    assert fleet.target_to_career("調酒師／吧台人員") is not None    # 定義蓋得到全市場
    assert fleet.target_reachable("調酒師／吧台人員", ids) is None   # 但不在型錄=不可及
    assert fleet.is_hit(["pm", "data_analyst"], "資料分析師")
    assert not fleet.is_hit(["pm"], "資料分析師")
