"""職涯型錄生成器:從 KB 的 careerId 覆蓋 + 104 市場資料,長出 C1 的推薦宇宙。
A 每補標一條 careerId,重跑本腳本,型錄自動多一格——型錄是管線產物,不是手寫債。
用法: python tools/build_careers.py [--jobs path/to/jobs_all.jsonl]
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 呈現層(人工維護的唯一部分):KB 只給 id,這裡給顯示皮膚與市場關鍵字
DISPLAY = {
    "data_analyst": dict(title="資料分析師", subtitleEn="Data Analyst",
                         category="數據", isAcademic=False, market=r"資料分析|數據分析"),
    "data_engineer": dict(title="資料工程師", subtitleEn="Data Engineer",
                          category="數據", isAcademic=False, market=r"資料工程|數據工程"),
    "pm": dict(title="產品企劃／PM", subtitleEn="Product Planner",
               category="產品", isAcademic=False, market=r"產品經理|企劃"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="")
    args = ap.parse_args()

    kb = json.load(open(ROOT / "fixtures/kb_seed/kb_entries.v1.json", encoding="utf-8"))
    cids = sorted({e.get("metadata", {}).get("careerId") for e in kb} - {None})
    jobs = []
    if args.jobs and Path(args.jobs).exists():
        jobs = [json.loads(l) for l in open(args.jobs, encoding="utf-8") if l.strip()]

    catalog = []
    for cid in cids:
        disp = DISPLAY.get(cid)
        if not disp:
            print(f"[skip] {cid}: DISPLAY 未定義呈現皮膚,請補", file=sys.stderr)
            continue
        skills = sorted({s for e in kb
                         if e.get("metadata", {}).get("careerId") == cid
                         and e["type"] == "job_skill" for s in e.get("skills", [])})
        hit = [j for j in jobs if re.search(disp["market"],
               j.get("title", "") + (j.get("jobCategory") or [""])[0])]
        sal = sorted(j["salaryLow"] for j in hit if j.get("salaryLow"))
        salary = (f"{sal[len(sal)//4]//1000}-{sal[3*len(sal)//4]//1000}k"
                  if len(sal) >= 4 else "依市場")
        catalog.append({
            "id": cid, "title": disp["title"], "subtitleEn": disp["subtitleEn"],
            "category": disp["category"], "isAcademic": disp["isAcademic"],
            "salary": salary, "openings": f"{len(hit):,}" if hit else "—",
            "requiredSkills": skills,          # 內部用:Scorer 的差集原料,不出對外 API
        })
    out = ROOT / "fixtures/careers/careers_v1.json"
    json.dump(catalog, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"型錄 {len(catalog)} 格 → {out}")


if __name__ == "__main__":
    main()
