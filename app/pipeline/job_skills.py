"""職缺 JD 技能抽取核心（成員 A）——tools/build_job_skills.py 的批次跑與 /jobs/extract-skills
端點共用的「單一真相」。prompt、解析、詞彙表過濾都在這裡，兩邊不會分叉。

受限選擇：LLM 從詞彙表 name_zh 直接挑（保證對齊計分器同一套詞彙、免正規化、免殘留）。
無金鑰（或 LLM 呼叫失敗）時退回 recommend.scan_skills_in_text 的字面掃描——不回 golden
範例，因為後端分不出真假會把範例當真的存（master/generate 踩過，見交接）。

回傳 requiredSkillsSource 標示抽取路徑，與 writeback 寫進 jobs 的欄位同名：
  llm_extract  受限選擇抽的
  vocab_scan   無金鑰退回字面掃描抽的（有金鑰後只重抽這批即可）
otherSkills：JD 有寫、但不在詞彙表的技能。v1 先回空陣列（受限選擇只挑表內字）；
  要填得有意義需另一條自由抽取，屬後續，合約先把欄位留好不用再改。
"""
from __future__ import annotations

import json

from app.pipeline.vocab import VOCAB_PATH

# 單筆 JD 餵給 LLM 的字數上限。舊批次版只取 900 字、且公司介紹在前，常把條件切掉；
# 拉高到 4000 讓條件段落進得來（端點與批次共用；批次 8 筆/次仍在 gpt-4o-mini 脈絡內）。
_MAX_JD = 4000

# 格式壞掉時回饋給模型、重試一次用（照 extraction/customize 的做法）。
_RETRY_HINT = ("\n\n上一次輸出不是合法 JSON 或缺 items 陣列。"
               "這次只輸出 {\"items\":[{\"skills\":[...]}]}，不要任何其他文字。")


def vocab_names() -> list[str]:
    return [e["name_zh"] for e in json.loads(VOCAB_PATH.read_text(encoding="utf-8"))]


def build_system(vocab: list[str]) -> str:
    """受限選擇的 system prompt（調過的措辭；端點與批次逐字共用）。"""
    return ("你是職缺分析助手。以下是一份「職能技能清單」。對每個職缺，從清單中挑出"
            "「做這份工作明確需要具備」的技能與證照。\n\n"
            "規則：\n"
            "1. 只能從清單挑，用清單上的原字，不可自創或改字。\n"
            "2. 只挑 JD 明確要求或強烈隱含的；不要沾邊就挑。不抽福利、公司介紹、年資、學歷。\n"
            "3. 優先挑『具體的專業／技術／工具／領域技能』（例如 SQL、Excel、顧客關係管理、"
            "財務報表製作、品質管理、故障排除、文書處理軟體操作、會計核算和帳務處理）。\n"
            "4. 通用軟實力（溝通能力、溝通協調、時間管理、主動學習、持續學習、問題分析與解決能力、"
            "組織能力、團隊合作、協調合作、服務導向、學習能力、批判性思考）不要拿來灌水：有具體技能時"
            "最多搭配 1 個。但若這份工作本質就是靠這些軟實力（客服、門市、接待、業務），真的沒有具體"
            "技能可挑，就挑最關鍵的 1 到 2 個——優先具體，但別因為排斥軟實力而把該有技能的職缺變成空的。\n"
            "5. 一筆挑 2 到 6 個；只有 JD 太短或全是公司介紹、看不出任何技能，才回空陣列 []。\n"
            "6. 嚴格按輸入順序，只回 JSON：{\"items\":[{\"skills\":[...]}, ...]}，筆數與輸入相同。\n\n"
            "技能清單：\n" + "、".join(vocab))


def format_jobs(jobs: list[dict], max_jd: int = _MAX_JD) -> str:
    """把一批 {title, jd}（jd 已由呼叫端組好）組成 user prompt。批次傳多筆、端點傳一筆。"""
    lines = []
    for i, j in enumerate(jobs, 1):
        jd = (j.get("jd") or "")[:max_jd]
        lines.append(f"[{i}] 職稱：{j.get('title', '')}\n    JD：{jd}")
    return f"共 {len(jobs)} 筆職缺，請逐筆從清單挑技能：\n\n" + "\n\n".join(lines)


def parse_items(raw: str, n: int) -> list[list[str]]:
    """LLM 輸出 {"items":[{"skills":[...]}, ...]} → 每筆的技能字串清單；筆數不足補空。"""
    try:
        items = json.loads(raw).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return [[] for _ in range(n)]
    out = [[str(s).strip() for s in (x.get("skills", []) if isinstance(x, dict) else [])
            if str(s).strip()] for x in items[:n]]
    out += [[] for _ in range(n - len(out))]
    return out


def parse_items_strict(raw: str, n: int) -> list[list[str]]:
    """嚴格解析：JSON 壞、非物件、items 不是 list、或筆數不足都丟 ValueError。

    為什麼要分嚴格版：parse_items 把解析失敗吞成空陣列，和「模型正常回了空技能」
    （{"items":[{"skills":[]}]}）結果一樣，呼叫端分不出「壞格式」與「真的沒技能」——
    壞格式會被當成抽完的空清單存進 DB、永不重抽（B 2026-10-26 review 抓到）。嚴格版
    讓端點能對壞格式重試／退 vocab_scan，對真空清單維持 llm_extract。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"非合法 JSON：{e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("缺 items 陣列或 items 不是 list")
    items = data["items"]
    if len(items) < n:
        raise ValueError(f"items 筆數不足：{len(items)} < {n}")
    return [[str(s).strip() for s in (x.get("skills", []) if isinstance(x, dict) else [])
             if str(s).strip()] for x in items[:n]]


def filter_vocab(picks: list[str], vocab_set: set[str]) -> list[str]:
    """防自創：只收詞彙表內的 name_zh，去重保序。"""
    return list(dict.fromkeys(s for s in picks if s in vocab_set))


def scan_skills(text: str) -> list[str]:
    """無金鑰退路：對文字做確定性字面掃描（詞彙表名稱／別名逐字命中）→ name_zh 去重。"""
    from app.pipeline.recommend import scan_skills_in_text
    return list(dict.fromkeys(s.name_zh for s in scan_skills_in_text(text)))


def extract_job_skills(title: str, jd_text: str, *, llm=None) -> dict:
    """單筆職缺 → {requiredSkills, requiredSkillsSource, otherSkills}。

    llm 有且呼叫成功 → 受限選擇（source=llm_extract）；
    llm 為 None 或呼叫失敗 → 字面掃描 title+JD（source=vocab_scan，不回 golden）。
    """
    vocab = vocab_names()
    vocab_set = set(vocab)
    if llm is not None:
        system = build_system(vocab)
        user = format_jobs([{"title": title, "jd": jd_text}])
        err: Exception | None = None
        for attempt in range(2):            # 原始一次 ＋ 壞格式／呼叫失敗時重試一次
            prompt = user if attempt == 0 else user + _RETRY_HINT + f"\n上次的具體問題：{err}"
            try:
                raw = llm.complete(system, prompt, force_json=True)
                picks = parse_items_strict(raw, 1)[0]     # 壞格式丟 ValueError → 重試／退路
                return {"requiredSkills": filter_vocab(picks, vocab_set),
                        "requiredSkillsSource": "llm_extract", "otherSkills": []}
            except Exception as e:           # complete() 失敗 或 解析失敗：記下原因再重試
                err = e
        # 原始＋重試都失敗 → 退字面掃描；不把壞格式當成「抽完的空清單」存起來（之後有金鑰再重抽）
    return {"requiredSkills": scan_skills(f"{title} {jd_text}"),
            "requiredSkillsSource": "vocab_scan", "otherSkills": []}
