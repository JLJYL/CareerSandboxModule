"""/jobs/extract-skills 與共用抽取模組（成員 A）。

覆蓋：受限選擇（fake LLM）、無金鑰退回 vocab_scan、otherSkills v1 空、
端點 422（jdText 空）、端點兩條路徑、_from_target_doc 不再吃 jdKeywords。
"""
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.job_skills import extract_job_skills
from app.pipeline.jobs_fit import _from_target_doc
from app.providers.llm import LLMUnavailable

c = TestClient(app)


class _FakeLLM:
    def __init__(self, payload: str):
        self._payload = payload

    def complete(self, system: str, user: str, force_json: bool = False) -> str:
        return self._payload


class _SeqLLM:
    """每次 complete 回下一個 payload（測重試：先壞後好）。"""
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self._i = 0

    def complete(self, system: str, user: str, force_json: bool = False) -> str:
        v = self._payloads[min(self._i, len(self._payloads) - 1)]
        self._i += 1
        return v


# --------------------------------------------------------------- 共用函式（單元）

def test_extract_llm_path_filters_non_vocab():
    llm = _FakeLLM('{"items":[{"skills":["機器學習","資料分析","不存在的技能XYZ"]}]}')
    r = extract_job_skills("資料分析師", "需要建模與分析", llm=llm)
    assert r["requiredSkillsSource"] == "llm_extract"
    assert "機器學習" in r["requiredSkills"] and "資料分析" in r["requiredSkills"]
    assert "不存在的技能XYZ" not in r["requiredSkills"]          # 防自創
    assert r["otherSkills"] == []                                 # v1 先空


def test_extract_without_llm_falls_back_to_vocab_scan():
    r = extract_job_skills("資料分析師", "熟 SQL 與 資料分析，會 Excel", llm=None)
    assert r["requiredSkillsSource"] == "vocab_scan"             # 不回 golden
    assert "資料分析" in r["requiredSkills"]                      # 字面命中詞彙表


def test_extract_llm_failure_degrades_to_scan():
    class _BoomLLM:
        def complete(self, *a, **k):
            raise RuntimeError("network down")
    r = extract_job_skills("資料分析師", "熟 資料分析", llm=_BoomLLM())
    assert r["requiredSkillsSource"] == "vocab_scan"            # 失敗不卡使用者新增


def test_extract_not_json_falls_back_to_scan():
    # 壞格式不能被當成「抽完的空清單」存成 llm_extract（B review）
    r = extract_job_skills("資料分析師", "熟 資料分析", llm=_FakeLLM("這不是 JSON"))
    assert r["requiredSkillsSource"] == "vocab_scan"


def test_extract_wrong_key_falls_back_to_scan():
    r = extract_job_skills("資料分析師", "熟 資料分析",
                           llm=_FakeLLM('{"data":[{"skills":["機器學習"]}]}'))
    assert r["requiredSkillsSource"] == "vocab_scan"


def test_extract_genuine_empty_stays_llm_extract():
    # 結構合法、技能真的空 → 維持 llm_extract（不該退 vocab_scan、不該重抽）
    r = extract_job_skills("x", "y", llm=_FakeLLM('{"items":[{"skills":[]}]}'))
    assert r["requiredSkillsSource"] == "llm_extract"
    assert r["requiredSkills"] == []


def test_extract_retries_then_succeeds():
    # 第一次壞、重試一次拿到合法 → llm_extract（不白白退成 vocab_scan）
    llm = _SeqLLM(["壞掉的輸出", '{"items":[{"skills":["機器學習"]}]}'])
    r = extract_job_skills("x", "y", llm=llm)
    assert r["requiredSkillsSource"] == "llm_extract"
    assert r["requiredSkills"] == ["機器學習"]


# --------------------------------------------------------------- 端點

def test_endpoint_empty_jd_returns_422():
    resp = c.post("/jobs/extract-skills", json={"title": "x", "jdText": ""})
    assert resp.status_code == 422                               # 合約：jdText 空 → 422


def test_endpoint_missing_fields_return_422():
    assert c.post("/jobs/extract-skills", json={"title": "x"}).status_code == 422
    assert c.post("/jobs/extract-skills", json={"jdText": "abc"}).status_code == 422


def test_endpoint_llm_path(monkeypatch):
    monkeypatch.setattr("app.api.routes.OpenAICompatibleLLM",
                        lambda *a, **k: _FakeLLM('{"items":[{"skills":["機器學習","資料分析"]}]}'))
    resp = c.post("/jobs/extract-skills", json={"title": "資料分析師", "jdText": "建模"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["requiredSkillsSource"] == "llm_extract"
    assert set(body["requiredSkills"]) == {"機器學習", "資料分析"}
    assert body["otherSkills"] == []


def test_endpoint_vocab_scan_when_no_key(monkeypatch):
    def _raise(*a, **k):
        raise LLMUnavailable("no key")
    monkeypatch.setattr("app.api.routes.OpenAICompatibleLLM", _raise)
    resp = c.post("/jobs/extract-skills", json={"title": "資料分析師", "jdText": "熟 資料分析"})
    assert resp.status_code == 200
    assert resp.json()["requiredSkillsSource"] == "vocab_scan"


# --------------------------------------------------------------- jobs_fit 修正

def test_target_doc_ignores_jdKeywords():
    """jdKeywords 被客製化汙染，不能再當 requiredSkills：只認 requiredSkills 欄位。"""
    only_kw = _from_target_doc({"_id": "t1", "title": "x", "jdKeywords": ["SQL", "Excel"]})
    assert only_kw["requiredSkills"] == []                       # 不吃 jdKeywords
    with_req = _from_target_doc({"_id": "t2", "title": "x",
                                 "requiredSkills": ["SQL"], "jdKeywords": ["Excel"]})
    assert with_req["requiredSkills"] == ["SQL"]                 # 只認 requiredSkills
