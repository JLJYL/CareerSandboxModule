"""回程評測器:一個指令跑全部樣本、自動改考卷、輸出通過率。

把 W1 手動的「跑 → 翻答案卡」壓成批次:
  python scripts/batch_eval.py                 # 掃 fixtures/samples/*.txt
  python scripts/batch_eval.py --limit 3       # 只跑前 N 份(省錢抽查)
有 .answer.json 的樣本做全套評分(硬指標),沒有的只做機械檢查(擷取成功+至少一卡)。
硬指標任一失敗 → exit code 1,可直接當回歸閘門(改 prompt 後跑一次,紅了就是退步)。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.extraction import ExtractionError, LlmExtractor  # noqa: E402
from app.providers.llm import LLMUnavailable, OpenAICompatibleLLM  # noqa: E402

# persona 經歷 type → 我方四類。volunteer→社團、exchange→學業 為暫定決議(04 文件小本本)。
TYPE_TO_CATEGORY = {
    "part_time": "工作", "internship": "工作",
    "campus": "社團", "volunteer": "社團",
    "project": "學業", "exchange": "學業",
    "competition": "競賽",
}


def _time_match(extracted: str, spoken: str) -> bool:
    """時間逐字保留的寬鬆版:允許無損縮寫(大四下學期↔大四下),空對空。"""
    if spoken == "":
        return extracted == ""
    return extracted != "" and (extracted in spoken or spoken in extracted)


def grade_sample(drafts, answer: dict) -> dict:
    """純函式,可測。回傳各硬指標布林與軟指標數值。"""
    expected = answer.get("expectedExperiences", [])
    exp_cats = sorted(TYPE_TO_CATEGORY.get(e.get("type", ""), "?") for e in expected)
    got_cats = sorted(d.category for d in drafts)

    spoken = [e.get("spokenPeriod", "") for e in expected]
    times = [d.time_range for d in drafts]
    remaining = list(times)
    time_ok = True
    for s in spoken:
        hit = next((t for t in remaining if _time_match(t, s)), None)
        if hit is None:
            time_ok = False
            break
        remaining.remove(hit)

    owned = answer.get("ownedSkills", [])
    raw_union = [s for d in drafts for s in d.raw_skills]
    covered = sum(1 for k in owned if any(k in r or r in k for r in raw_union))

    return {
        "card_count_ok": len(drafts) == len(expected),
        "categories_ok": got_cats == exp_cats,
        "time_ok": time_ok,
        "skills_recall": (covered / len(owned)) if owned else None,
        "detail": f"卡 {len(drafts)}/{len(expected)} 類 {got_cats}vs{exp_cats}",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "fixtures" / "samples"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    txts = sorted(p for p in Path(args.dir).glob("*.txt"))
    if args.limit:
        txts = txts[: args.limit]
    if not txts:
        sys.exit(f"[X] {args.dir} 沒有任何 .txt 樣本")

    try:
        extractor = LlmExtractor(OpenAICompatibleLLM())
    except LLMUnavailable as e:
        sys.exit(f"[X] {e}")

    hard_fail = 0
    graded = passed = 0
    for txt in txts:
        ans_path = txt.with_suffix("").with_suffix(".answer.json") \
            if txt.name.endswith(".answer.txt") else txt.parent / (txt.stem + ".answer.json")
        try:
            drafts = extractor.extract([txt.read_text(encoding="utf-8")])
        except ExtractionError as e:
            print(f"[FAIL] {txt.name}  品管未過:{str(e)[:60]}")
            hard_fail += 1
            continue

        if ans_path.exists():
            g = grade_sample(drafts, json.loads(ans_path.read_text(encoding="utf-8")))
            graded += 1
            ok = g["card_count_ok"] and g["categories_ok"] and g["time_ok"]
            passed += ok
            hard_fail += 0 if ok else 1
            recall = f" 技能召回 {g['skills_recall']:.0%}" if g["skills_recall"] is not None else ""
            print(f"[{'PASS' if ok else 'FAIL'}] {txt.name}  {g['detail']}"
                  f" 時間{'✓' if g['time_ok'] else '✗'}{recall}")
        else:
            print(f"[ok  ] {txt.name}  無答案卡,機械檢查過({len(drafts)} 卡)——人工照五項清單改")

    print(f"\n總結:{len(txts)} 份;有答案卡 {graded} 份,全過 {passed} 份"
          f"({(passed / graded):.0%})" if graded else "\n總結:全為無答案卡樣本")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
