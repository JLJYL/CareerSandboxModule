"""把 persona「翻面」成口語自介測試樣本(+答案卡)。

用途:等待真人資料的空檔,製造刻意帶坑的野生化樣本;同時是之後回程評測的前半段。
用法:
  python scripts/make_synthetic_samples.py --n 3
  python scripts/make_synthetic_samples.py --n 1 --dry-run   # 只看生成 prompt,不花錢
產出:
  fixtures/samples/syn_01.txt          口語自介(拿去餵 try_extraction.py)
  fixtures/samples/syn_01.answer.json  標準答案(persona 原始經歷),之後自動對答案用
兩者都在 .gitignore 的 samples 規則下,不會進版控。
"""
import argparse
import datetime
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_GRADE = {"大一": 1, "大二": 2, "大三": 3, "大四": 4, "應屆畢業": 4, "碩一": 5, "碩二": 6}
_NAME = {1: "大一", 2: "大二", 3: "大三", 4: "大四", 5: "碩一", 6: "碩二"}


def _ay(y: int, m: int) -> int:
    """該日期屬於哪個學年(以 9 月為學年起點)。"""
    return y if m >= 9 else y - 1


def to_school_period(period: str, grade_str: str, today: datetime.date | None = None) -> str:
    """西元期間 → 就學階段說法(「大三下學期」「大二升大三的暑假」)。
    生成端做這個換算是合法的:我們握有年級+精確日期,用確定性程式算;
    擷取端做反向換算(模糊→年月)則是捏造。同一個動作,方向決定合法性。
    解析失敗一律原樣返回,不硬編。"""
    today = today or datetime.date.today()
    gnow = next((v for k, v in _GRADE.items() if k in (grade_str or "")), None)
    hits = re.findall(r"(\d{4})[./](\d{1,2})", period or "")
    if not gnow or not hits:
        return period or ""
    cur_ay = _ay(today.year, today.month)

    def grade_of(y: int, m: int) -> int:
        return gnow - (cur_ay - _ay(y, m))

    y1, m1 = map(int, hits[0])
    g1 = grade_of(y1, m1)
    if g1 not in _NAME:
        return period
    n1 = _NAME[g1]
    if len(hits) == 1:
        if m1 in (7, 8):
            n2 = _NAME.get(g1 + 1)
            return f"{n1}升{n2}的暑假" if n2 else f"{n1}那年的暑假"
        return f"{n1}{'上' if (m1 >= 9 or m1 == 1) else '下'}學期"
    y2, m2 = map(int, hits[1])
    g2 = grade_of(y2, m2)
    if g1 == g2:
        if (m1 >= 9 or m1 == 1) and 2 <= m2 <= 8:
            return f"{n1}那一年"
        return f"{n1}{'上' if (m1 >= 9 or m1 == 1) else '下'}學期"
    return f"{n1}到{_NAME[g2]}" if g2 in _NAME else period

# 四種刻意摻入的坑,對應真實資料預告過的野生菜色
STYLES = {
    "run_on": "整段不分段一路講下去,句子黏在一起像沒換氣",
    "filler": "夾大量口語填充詞:就是、然後那個、對啊、嗯",
    "no_time": "完全不提任何年份、年級、學期、季節等時間線索",
    "bullet": "用履歷式短語條列(可帶破折號),不是聊天語氣",
}

SYS = "你在扮演一位台灣大學生,用第一人稱介紹自己做過的事。只輸出自介本文,不要任何前後說明或標題。"


def build_prompt(p: dict, styles: list[str]) -> str:
    prof = p.get("profile", {})
    grade = prof.get("grade", "")
    lines = []
    for e in p.get("experiences", []):
        line = f"- {e.get('title', '')}({e.get('type', '')}):{e.get('description', '')}"
        if "no_time" not in styles:  # 防洩題:no_time 坑型連材料都不給日期
            spoken = to_school_period(e.get("period", ""), grade)
            if spoken:
                line += f" 時間說法:{spoken}"
        line += f" 角色:{e.get('role', '')}"
        lines.append(line)
    style_txt = ";".join(STYLES[s] for s in styles)
    time_rule = (
        "" if "no_time" in styles
        else "\n提到時間只能用上面給的「時間說法」原話,禁止換算成任何西元年月。"
    )
    return (
        f"你的身分:{prof.get('department', '大學生')} {grade}。\n"
        "你做過的事如下,必須全部講到,但要用你自己的話重新說,可打亂順序,不要逐字照抄:\n"
        + "\n".join(lines)
        + f"\n\n說話風格要求:{style_txt}。{time_rule}\n長度 120 到 250 字。"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--data", default=str(ROOT / "fixtures/eval/persona_150.jsonl"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    recs = [json.loads(l) for l in Path(args.data).read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = [(i, r) for i, r in enumerate(recs) if len(r.get("experiences", [])) >= 2]
    rng = random.Random(args.seed)
    picks = rng.sample(pool, min(args.n, len(pool)))

    out_dir = ROOT / "fixtures" / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = None
    if not args.dry_run:
        from app.providers.llm import LLMUnavailable, OpenAICompatibleLLM
        try:
            llm = OpenAICompatibleLLM()
        except LLMUnavailable as e:
            sys.exit(f"[X] {e}")

    for k, (idx, p) in enumerate(picks, 1):
        styles = rng.sample(list(STYLES), rng.choice([1, 2]))
        prompt = build_prompt(p, styles)
        txt_path = out_dir / f"syn_{k:02d}.txt"
        ans_path = out_dir / f"syn_{k:02d}.answer.json"
        print(f"\n=== syn_{k:02d} | persona #{idx} | 坑型: {styles} ===")
        if args.dry_run:
            print(prompt)
            print(f"(dry-run) 將寫入: {txt_path.name} / {ans_path.name}")
            continue
        text = llm.complete(SYS, prompt).strip()
        txt_path.write_text(text + "\n", encoding="utf-8")
        grade = p.get("profile", {}).get("grade", "")
        expected = [
            {**e, "spokenPeriod": ("" if "no_time" in styles
                                   else to_school_period(e.get("period", ""), grade))}
            for e in p.get("experiences", [])
        ]
        ans_path.write_text(json.dumps({
            "sourceIndex": idx,
            "styles": styles,
            "expectedExperiences": expected,
            "ownedSkills": p.get("skills", {}).get("owned", []),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(text[:80] + "…")
        print(f"已寫入 {txt_path.name}(考卷)與 {ans_path.name}(答案卡)")

    if not args.dry_run:
        print("\n下一步:逐份 python scripts/try_extraction.py fixtures/samples/syn_01.txt,"
              "對五項清單;對完可翻開 answer.json 比對有沒有漏卡或多卡。")


if __name__ == "__main__":
    main()