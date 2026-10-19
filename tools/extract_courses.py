"""課程技能標註（成員 A，受限選擇版）——讓 LLM 從詞彙表挑出每門課教的技能。

為什麼受限選擇而非自由抽取＋bge-m3：自由抽取出的詞（C++程式設計、資料探勘）與詞彙表
標準名的向量相似度在 0.74–0.83 之間，與錯誤配對（材料分析→資料分析 0.74）重疊，
沒有乾淨的門檻切得開。改讓 LLM 直接從詞彙表 234 個 name_zh 裡挑，輸出保證對齊、免正規化、
免殘留；LLM 的語意判斷也比 bge-m3 cosine 準。挑不到就空。

輸出 jsonl（可續跑），skills 欄已是詞彙表 name_zh；跑完自動彙整成 resources_v1.json
（去重、零技能剔除）。

用法：
  python tools/extract_courses.py --courses <courses_dedup.jsonl> \
      --school-match 中山 --school nsysu --provider 國立中山大學 \
      --out data/resources_raw_skills_llm.jsonl \
      --catalog fixtures/resources/resources_v1.json [--batch 8] [--limit N]
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


def _vocab_names() -> list[str]:
    return [e["name_zh"] for e in json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))]


def _system(vocab: list[str]) -> str:
    return ("你是課程分析助手。以下是一份「職能技能清單」。對每門課，從清單中挑出"
            "「修完這門課會真正具備」的技能。\n\n"
            "規則：\n"
            "1. 只能從清單挑，用清單上的原字，不可自創或改字。\n"
            "2. 要判斷課程內容是否真的訓練該技能，不要因課名有某字就硬挑。\n"
            "3. 一門課挑 0 到 5 個；挑不到相關技能（如純體育、純通識、純人文）就回空陣列 []。\n"
            "4. 嚴格按輸入順序，只回 JSON：{\"items\":[{\"skills\":[...]}, ...]}，筆數與輸入相同。\n\n"
            "技能清單：\n" + "、".join(vocab))


def _prompt(batch: list[dict]) -> str:
    lines = []
    for i, c in enumerate(batch, 1):
        outline = (c.get("outline") or "")[:400]
        lines.append(f"[{i}] 課名：{c['title']}\n    大綱：{outline}")
    return f"共 {len(batch)} 門課，請逐門從清單挑技能：\n\n" + "\n\n".join(lines)


def _parse(raw: str, n: int) -> list[list[str]]:
    try:
        items = json.loads(raw).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return [[] for _ in range(n)]
    out = [[str(s).strip() for s in (x.get("skills", []) if isinstance(x, dict) else [])
            if str(s).strip()] for x in items[:n]]
    out += [[] for _ in range(n - len(out))]
    return out


def _finalize(jsonl: Path, catalog: Path, vocab: set[str]) -> None:
    """jsonl → resources_v1.json：技能過濾成有效 name_zh、去重、零技能剔除。"""
    rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    out, dropped = [], 0
    for r in rows:
        skills = list(dict.fromkeys(s for s in r.get("rawSkills", []) if s in vocab))
        if not skills:
            dropped += 1
            continue
        out.append({"resourceId": r["resourceId"], "type": "course", "title": r["title"],
                    "provider": r.get("provider", ""), "providerKey": r.get("providerKey", ""),
                    "skills": skills, "description": r.get("description", ""),
                    "url": r.get("url", ""), "deadline": "", "sourceId": r.get("sourceId", "")})
    catalog.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"彙整課程目錄 {len(out)} 門（零技能剔除 {dropped}）→ {catalog}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--courses", required=True)
    ap.add_argument("--school-match", default="中山")
    ap.add_argument("--school", default="nsysu")
    ap.add_argument("--provider", default="國立中山大學")
    ap.add_argument("--out", default=str(REPO / "data" / "resources_raw_skills_llm.jsonl"))
    ap.add_argument("--catalog", default=str(REPO / "fixtures" / "resources" / "resources_v1.json"))
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--finalize-only", action="store_true", help="跳過 LLM，只把現有 jsonl 彙整成 catalog")
    args = ap.parse_args()

    vocab = _vocab_names()
    vocab_set = set(vocab)
    out = Path(args.out)

    if not args.finalize_only:
        rows = []
        for ln in Path(args.courses).read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if args.school_match and args.school_match not in (r.get("school") or ""):
                continue
            title = (r.get("course_name") or "").strip()
            if not title:
                continue
            dept = (r.get("department") or "").strip()
            rid = (r.get("row_id") or r.get("course_id") or title).split(":")[-1].strip()
            rows.append({
                "resourceId": f"crs_{args.school}_{rid}", "type": "course", "title": title,
                "provider": f"{args.provider} · {dept}" if dept else args.provider,
                "providerKey": args.school, "url": (r.get("course_url") or "").strip(),
                "deadline": "", "outline": (r.get("outline") or "").strip(),
                "description": (r.get("outline") or "").strip()[:300],
                "sourceId": r.get("row_id") or r.get("course_id") or rid,
            })
        if args.limit:
            rows = rows[: args.limit]

        out.parent.mkdir(parents=True, exist_ok=True)
        done = set()
        if out.exists():
            for ln in out.read_text(encoding="utf-8").splitlines():
                try:
                    done.add(json.loads(ln)["resourceId"])
                except Exception:
                    pass
        todo = [r for r in rows if r["resourceId"] not in done]
        print(f"{args.school_match} 課程 {len(rows)} 門；已完成 {len(done)}，待處理 {len(todo)}，批次 {args.batch}",
              flush=True)

        llm = OpenAICompatibleLLM()
        system = _system(vocab)
        with out.open("a", encoding="utf-8") as f:
            for start in range(0, len(todo), args.batch):
                batch = todo[start:start + args.batch]
                try:
                    picks = _parse(llm.complete(system, _prompt(batch), force_json=True), len(batch))
                except Exception as e:
                    print(f"  ! batch {start} 失敗：{e}", flush=True)
                    picks = [[] for _ in batch]
                for j, r in enumerate(batch):
                    r["rawSkills"] = [s for s in picks[j] if s in vocab_set]   # 防自創：只收有效 name_zh
                    r.pop("outline", None)
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                if (start // args.batch) % 10 == 0:
                    print(f"  +{min(start + args.batch, len(todo))}/{len(todo)}", flush=True)

    _finalize(out, Path(args.catalog), vocab_set)


if __name__ == "__main__":
    main()
