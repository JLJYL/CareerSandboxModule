"""競賽技能標註（成員 A，受限選擇版）——讓 LLM 從詞彙表挑出每個競賽能練到的技能。

競賽交接文件（2026/10/18）指明模型組要幫競賽標對齊詞彙表的 skills，供「缺技能→推薦競賽」。
與課程同理：自由抽取＋bge-m3 門檻對不乾淨，改讓 LLM 直接從詞彙表 234 個 name_zh 裡挑，
輸出保證對齊、免正規化、免殘留。挑不到（純建築／藝術／數學競賽）就空陣列。

輸出 competitions_v1.jsonl：原始競賽欄位全留、多一個 `skills` 欄（已是 name_zh）。
兩用：交後端組匯入 Mongo `competitions`；也當 reinforce 讀不到 Mongo 時的 fallback。

用法：
  python tools/tag_competitions.py --in <competitions.jsonl> \
      --out fixtures/resources/competitions_v1.jsonl \
      --report docs/competitions_residuals_report.md [--batch 10] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.config import settings  # noqa: F401
from app.providers.llm import OpenAICompatibleLLM  # noqa: E402

_VOCAB_PATH = REPO / "fixtures" / "vocab" / "skills_v1.json"
_CATEGORY_ZH = {"HACKATHON": "黑客松／程式開發", "DESIGN": "設計",
                "RESEARCH": "研究／論文", "CASE": "商業個案分析", "PITCH": "提案／創業"}


def _vocab_names() -> list[str]:
    return [e["name_zh"] for e in json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))]


def _system(vocab: list[str]) -> str:
    return ("你是職涯輔導助手。以下是一份「職能技能清單」。每筆是一個學生競賽，"
            "請從清單中挑出「參賽者會實際練到或用到」的技能。\n\n"
            "規則：\n"
            "1. 只能從清單挑，用清單上的原字，不可自創或改字。\n"
            "2. 要判斷競賽內容是否真的練到該技能，不要只看關鍵字表面。\n"
            "3. 一筆挑 0 到 5 個；與可遷移職能關聯很弱（純建築、純藝術、純數學、純人文）就回空陣列 []。\n"
            "4. 嚴格按輸入順序，只回 JSON：{\"items\":[{\"skills\":[...]}, ...]}，筆數與輸入相同。\n\n"
            "技能清單：\n" + "、".join(vocab))


def _prompt(batch: list[dict]) -> str:
    lines = []
    for i, c in enumerate(batch, 1):
        cat = _CATEGORY_ZH.get(c.get("category", ""), c.get("category", ""))
        tags = "、".join(c.get("tags", []) or [])
        lines.append(f"[{i}] 標題：{c.get('title','')}\n    類別：{cat}\n    關鍵字：{tags}")
    return f"共 {len(batch)} 筆，請逐筆從清單挑技能：\n\n" + "\n\n".join(lines)


def _parse(raw: str, n: int) -> list[list[str]]:
    try:
        items = json.loads(raw).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return [[] for _ in range(n)]
    out = [[str(s).strip() for s in (x.get("skills", []) if isinstance(x, dict) else [])
            if str(s).strip()] for x in items[:n]]
    out += [[] for _ in range(n - len(out))]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", default=str(REPO / "fixtures/resources/competitions_v1.jsonl"))
    ap.add_argument("--report", default=str(REPO / "docs/competitions_residuals_report.md"))
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    vocab = _vocab_names()
    vocab_set = set(vocab)
    comps = [json.loads(ln) for ln in Path(args.inp).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if args.limit:
        comps = comps[: args.limit]
    print(f"讀入 {len(comps)} 筆競賽", flush=True)

    llm = OpenAICompatibleLLM()
    system = _system(vocab)
    picks: dict[int, list[str]] = {}
    for start in range(0, len(comps), args.batch):
        batch = comps[start:start + args.batch]
        sel = _parse(llm.complete(system, _prompt(batch), force_json=True), len(batch))
        for j, s in enumerate(sel):
            picks[start + j] = [x for x in s if x in vocab_set]     # 防自創
        print(f"  已標 {min(start + args.batch, len(comps))}/{len(comps)}", flush=True)

    enriched, empties = [], []
    for i, c in enumerate(comps):
        skills = list(dict.fromkeys(picks.get(i, [])))
        if not skills:
            empties.append(c.get("title", c.get("sourceId", "")))
        enriched.append({**c, "skills": skills})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in enriched:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"寫出 {len(enriched)} 筆（{len(enriched) - len(empties)} 筆有技能）→ {out}", flush=True)

    lines = ["# 競賽技能標註報告（給成員 B 覆核）", "",
             "受限選擇版：LLM 直接從詞彙表 name_zh 挑，輸出保證對齊，無正規化殘留。", "",
             f"- 競賽總數：{len(enriched)}",
             f"- 標到技能：{len(enriched) - len(empties)}",
             f"- 標不到（純建築／藝術／數學等，與職能詞表關聯弱，屬正常）：{len(empties)}", ""]
    if empties:
        lines += ["## 標不到技能的競賽", ""] + [f"- {t}" for t in empties] + [""]
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"報告 → {args.report}", flush=True)


if __name__ == "__main__":
    main()
