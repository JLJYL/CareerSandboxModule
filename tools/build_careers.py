"""職涯型錄生成器 v2:以 A 的 30 職涯定義檔為宇宙,證據(KB 技能骨架/已標文章)決定入列,
市場資料(jobs_all)供薪資與缺量。分類決定(四類 vs 全市場)只影響 category 欄與入列範圍,
故做成雙模式——決定拍板當天,跑一次對應模式即完工。

用法:
  python tools/build_careers.py --mode four   [--jobs jobs_all.jsonl] [--out 路徑]
  python tools/build_careers.py --mode market [--jobs jobs_all.jsonl] [--out 路徑]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# category 對照表。四類=合約現值;其餘為「暫定桶名」草案,採全市場時由 A+怡君定名,改字即可。
CATEGORY_MAP = {
    "data_analyst": "數據", "ai_data_engineer": "數據", "pm": "產品",
    "graphic_designer": "設計", "uiux_designer": "設計", "content_creator": "設計",
    # ---- 以下為全市場模式的暫定桶名(草案,待定名) ----
    "frontend_engineer": "工程", "software_engineer": "工程", "fullstack_engineer": "工程",
    "qa_engineer": "工程", "network_engineer": "工程", "it_support": "工程",
    "marketing": "行銷", "sales": "業務", "customer_service": "客服",
    "hr": "人資", "finance_accounting": "財會", "procurement": "採購",
    "logistics": "物流", "admin": "行政", "operations_mgmt": "營運",
    "reception": "服務", "beauty": "服務", "food_service": "服務",
    "driver": "運輸", "technician": "技術", "travel": "服務",
    "legal": "法務", "public_sector": "公職", "healthcare": "醫護",
}
FOUR = {"數據", "產品", "設計", "學術"}
_EN = {"ai_data_engineer": "AI/Data Engineer", "pm": "Product Planner",
       "hr": "HR Specialist", "uiux_designer": "UI/UX Designer", "it_support": "IT Support"}


def _subtitle_en(cid: str) -> str:
    if cid in _EN:
        return _EN[cid]
    return " ".join(w.upper() if w in ("ai", "it", "qa", "pm", "hr") else w.capitalize()
                    for w in cid.split("_"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["four", "market"], required=True)
    ap.add_argument("--jobs", default="")
    ap.add_argument("--out", default=str(ROOT / "fixtures/careers/careers_v1.json"))
    args = ap.parse_args()

    tax = json.load(open(ROOT / "fixtures/careers/careers.v1.json", encoding="utf-8"))["careers"]
    kb = json.load(open(ROOT / "fixtures/kb_seed/kb_entries.v1.json", encoding="utf-8"))
    arts = json.load(open(ROOT / "fixtures/kb_seed/kb_entries.articles.v1.json", encoding="utf-8"))

    skills_by = {}
    for e in kb:
        cid = e.get("metadata", {}).get("careerId")
        if cid and e["type"] == "job_skill":
            skills_by.setdefault(cid, set()).update(e.get("skills", []))
    art_count = {}
    for e in arts:
        m = e.get("metadata", {})
        if m.get("careerId") and not m.get("offtopic"):
            art_count[m["careerId"]] = art_count.get(m["careerId"], 0) + 1

    jobs = []
    if args.jobs and Path(args.jobs).exists():
        jobs = [json.loads(l) for l in open(args.jobs, encoding="utf-8") if l.strip()]

    catalog, skipped = [], []
    for c in tax:
        cid = c["careerId"]
        skills = sorted(skills_by.get(cid, set()))
        n_art = art_count.get(cid, 0)
        if not skills and n_art == 0:
            skipped.append((cid, "零證據"))
            continue                     # 無技能骨架也無文章 → 不入列(A 補證據即自動入列)
        cat = CATEGORY_MAP.get(cid, "其他")
        if args.mode == "four" and cat not in FOUR:
            skipped.append((cid, f"四類外({cat})"))
            continue
        pat = "|".join(map(re.escape, c["aliases"] + [c["name"]]))
        hit = [j for j in jobs if re.search(pat, j.get("title", "") +
               (j.get("jobCategory") or [""])[0])]
        sal = sorted(j["salaryLow"] for j in hit if j.get("salaryLow"))
        catalog.append({
            "id": cid, "title": c["name"], "subtitleEn": _subtitle_en(cid),
            "category": cat, "isAcademic": False,
            "salary": (f"{sal[len(sal)//4]//1000}-{sal[3*len(sal)//4]//1000}k"
                       if len(sal) >= 4 else "依市場"),
            "openings": f"{len(hit):,}" if hit else "—",
            "requiredSkills": skills,
            "evidence": {"jobSkillEntries": len(skills) > 0, "taggedArticles": n_art},
        })
    Path(args.out).write_text(json.dumps(catalog, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"[{args.mode}] 入列 {len(catalog)} 格 → {args.out}")
    for cid, why in skipped:
        print(f"  跳過 {cid}: {why}", file=sys.stderr)


if __name__ == "__main__":
    main()
