"""職缺 JD 技能抽取（成員 A，交接文件四 §12）——補 jobs 裡 requiredSkills 為空的職缺。

背景：CareerSandboxDB.jobs 4125 筆只有 24.5% 有 requiredSkills（全來自 104）；
yourator / taiwanjobs / cake 全空。計分器對空 requiredSkills 的職缺算不出 missingSkills，
使用者看不到自己缺什麼（技能補強也就無料可補）。這支把缺的補起來。

三段，各自可單獨重跑（中間檔落地）：
  extract   讀 requiredSkills 為空的職缺 → 抽技能 → data/job_skills_raw.jsonl
            - cake：技能在 tags（Word/Photoshop…），不動 LLM，收 tags（method=tags_mapped）
            - 其餘（yourator/taiwanjobs/104 空的）：LLM 讀 description+conditionOther
              「受限選擇」——從詞彙表 name_zh 直接挑（method=llm_extract）
  normalize data/job_skills_raw.jsonl → 對齊詞彙表 → data/job_skills_normalized.jsonl
            + 殘留 data/job_skills_residuals.json
  writeback 把 requiredSkills 寫回 Atlas（+ requiredSkillsSource / requiredSkillsExtractedAt）
            預設 --dry-run，要真的寫加 --apply；只動本來就空的那筆，不覆蓋 104。

為什麼用「受限選擇」而非交接文件寫的「自由抽取→normalize(0.88)」：課程那邊實測
自由抽取＋bge-m3 0.88 召回很差（4983→143），正確／錯誤配對相似度重疊無乾淨門檻；
受限選擇輸出保證對齊詞彙表、召回好、且 requiredSkills 必須跟計分器同一套詞彙表才有意義。
（此為對 §12 的偏離，已在 PR 說明，請 B 覆核。）

Atlas 連線沿用 tools/ingest_atlas.py；URI 從 .env 的 MONGODB_URI 讀，不走命令列。

用法：
  # 測試（不碰 Atlas，讀本地樣本）
  python tools/build_job_skills.py extract --jobs-file <local.jsonl> --limit 50
  python tools/build_job_skills.py normalize
  python tools/build_job_skills.py writeback --dry-run

  # 正式（需 .env 有 readWrite 的 MONGODB_URI）
  python tools/build_job_skills.py extract
  python tools/build_job_skills.py normalize
  python tools/build_job_skills.py writeback --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.config import settings  # noqa: E402,F401  副作用:載入 .env
from app.pipeline.normalize import VocabNormalizer  # noqa: E402
from app.pipeline.vocab import VOCAB_PATH, load_vocabulary  # noqa: E402

_RAW = REPO / "data" / "job_skills_raw.jsonl"
_NORM = REPO / "data" / "job_skills_normalized.jsonl"
_RESID = REPO / "data" / "job_skills_residuals.json"
_COLL = "jobs"
_EMPTY_QUERY = {"$or": [{"requiredSkills": {"$exists": False}},
                       {"requiredSkills": None}, {"requiredSkills": []}]}


def _vocab_names() -> list[str]:
    return [e["name_zh"] for e in json.loads(VOCAB_PATH.read_text(encoding="utf-8"))]


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def _system(vocab: list[str]) -> str:
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


def _prompt(batch: list[dict]) -> str:
    lines = []
    for i, j in enumerate(batch, 1):
        jd = ("\n".join(p for p in (j.get("description"), j.get("conditionOther")) if p))[:900]
        lines.append(f"[{i}] 職稱：{j.get('title', '')}\n    JD：{jd}")
    return f"共 {len(batch)} 筆職缺，請逐筆從清單挑技能：\n\n" + "\n\n".join(lines)


def _parse(raw: str, n: int) -> list[list[str]]:
    try:
        items = json.loads(raw).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return [[] for _ in range(n)]
    out = [[str(s).strip() for s in (x.get("skills", []) if isinstance(x, dict) else [])
            if str(s).strip()] for x in items[:n]]
    out += [[] for _ in range(n - len(out))]
    return out


def _iter_jobs(args):
    """讀 requiredSkills 為空的職缺：本地 --jobs-file（測試）或 Atlas。"""
    if args.jobs_file:
        for ln in Path(args.jobs_file).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                rs = d.get("requiredSkills")
                if not rs:                                  # 只收空的
                    yield d
    else:
        from tools.ingest_atlas import make_client, resolve_db, resolve_uri, mask_uri
        uri = resolve_uri(None)
        db = resolve_db(args.db, uri)
        print(f"連線 {mask_uri(uri)} / {db}", flush=True)
        client = make_client(uri, appname="build_job_skills")
        coll = client[db][_COLL]
        proj = {"source": 1, "title": 1, "description": 1, "conditionOther": 1, "tags": 1}
        for d in coll.find(_EMPTY_QUERY, proj):
            yield d


def cmd_extract(args) -> None:
    vocab = _vocab_names()
    vocab_set = set(vocab)
    jobs = list(_iter_jobs(args))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"requiredSkills 為空的職缺 {len(jobs)} 筆", flush=True)

    cake = [j for j in jobs if (j.get("source") or "").lower() == "cake"]
    llm_jobs = [j for j in jobs if (j.get("source") or "").lower() != "cake"]
    print(f"  cake（tags 直接對）：{len(cake)}；其餘（LLM 抽取）：{len(llm_jobs)}", flush=True)

    _RAW.parent.mkdir(parents=True, exist_ok=True)
    with _RAW.open("w", encoding="utf-8") as f:
        # cake：收 tags，不動 LLM
        for j in cake:
            f.write(json.dumps({"_id": str(j.get("_id", "")), "source": "cake",
                                "method": "tags_mapped", "title": j.get("title", ""),
                                "rawTags": [str(t).strip() for t in (j.get("tags") or []) if str(t).strip()]},
                               ensure_ascii=False) + "\n")
        # 其餘：LLM 受限選擇
        if llm_jobs:
            from app.providers.llm import OpenAICompatibleLLM
            llm = OpenAICompatibleLLM()
            system = _system(vocab)
            for start in range(0, len(llm_jobs), args.batch):
                batch = llm_jobs[start:start + args.batch]
                try:
                    picks = _parse(llm.complete(system, _prompt(batch), force_json=True), len(batch))
                except Exception as e:
                    print(f"  ! batch {start} 失敗：{e}", flush=True)
                    picks = [[] for _ in batch]
                for k, j in enumerate(batch):
                    valid = [s for s in picks[k] if s in vocab_set]   # 防自創
                    f.write(json.dumps({"_id": str(j.get("_id", "")),
                                        "source": (j.get("source") or "").lower() or "unknown",
                                        "method": "llm_extract", "title": j.get("title", ""),
                                        "picked": valid}, ensure_ascii=False) + "\n")
                if (start // args.batch) % 10 == 0:
                    print(f"  LLM +{min(start + args.batch, len(llm_jobs))}/{len(llm_jobs)}", flush=True)
    print(f"寫出中間檔 → {_RAW}", flush=True)


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def cmd_normalize(args) -> None:
    vocab_set = set(_vocab_names())
    norm = VocabNormalizer()                                # cake tags 用；alias-only 對標準詞足夠
    rows = [json.loads(l) for l in _RAW.read_text(encoding="utf-8").splitlines() if l.strip()]

    out, residuals, still_empty = [], {}, 0
    for r in rows:
        if r["method"] == "llm_extract":
            skills = list(dict.fromkeys(s for s in r.get("picked", []) if s in vocab_set))
        else:                                               # tags_mapped
            skills = []
            for t in r.get("rawTags", []):
                if t in vocab_set:
                    if t not in skills:
                        skills.append(t)
                    continue
                hit = norm.normalize(t)
                if hit and hit.name_zh not in skills:
                    skills.append(hit.name_zh)
                elif not hit:
                    residuals.setdefault(t, 0)
                    residuals[t] += 1
        if not skills:
            still_empty += 1
            continue                                        # 抽不到就不寫回，維持原狀
        out.append({"_id": r["_id"], "source": r["source"], "method": r["method"],
                    "requiredSkills": skills})

    with _NORM.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _RESID.write_text(json.dumps(sorted(residuals.items(), key=lambda kv: -kv[1]),
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"可寫回 {len(out)} 筆；仍為空（抽不到技能）{still_empty} 筆 → {_NORM}", flush=True)
    print(f"cake tags 殘留 {len(residuals)} 種 → {_RESID}", flush=True)


# ---------------------------------------------------------------------------
# writeback
# ---------------------------------------------------------------------------

def _to_id(s: str):
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        return s                                            # 非 ObjectId 的來源用原字串


def cmd_writeback(args) -> None:
    rows = [json.loads(l) for l in _NORM.read_text(encoding="utf-8").splitlines() if l.strip()]
    now = datetime.now(timezone.utc).isoformat()
    print(f"待寫回 {len(rows)} 筆；模式：{'APPLY（真的寫）' if args.apply else 'DRY-RUN（不寫）'}", flush=True)

    if not args.apply:
        for r in rows[:10]:
            print(f"  [dry] {r['_id']} ({r['source']}) ← {r['requiredSkills']}", flush=True)
        print(f"  ...（共 {len(rows)} 筆；加 --apply 才會真的寫）", flush=True)
        return

    from tools.ingest_atlas import make_client, resolve_db, resolve_uri, mask_uri
    uri = resolve_uri(None)
    db = resolve_db(args.db, uri)
    print(f"連線 {mask_uri(uri)} / {db}", flush=True)
    coll = make_client(uri, appname="build_job_skills")[db][_COLL]

    updated = skipped = 0
    for r in rows:
        res = coll.update_one(
            {"_id": _to_id(r["_id"]), **_EMPTY_QUERY},       # 只動仍為空的，不覆蓋 104
            {"$set": {"requiredSkills": r["requiredSkills"],
                      "requiredSkillsSource": r["method"],
                      "requiredSkillsExtractedAt": now}})
        if res.modified_count:
            updated += 1
        else:
            skipped += 1
    print(f"寫回完成：更新 {updated} 筆；略過（已非空或查無）{skipped} 筆", flush=True)


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="職缺 JD 技能抽取（§12）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="讀空 requiredSkills 職缺 → 抽技能中間檔")
    pe.add_argument("--jobs-file", default="", help="本地 jsonl 樣本（測試用，不連 Atlas）")
    pe.add_argument("--db", default="", help="database 名（預設 MONGODB_DB 或 URI 內）")
    pe.add_argument("--batch", type=int, default=8)
    pe.add_argument("--limit", type=int, default=0)
    pe.set_defaults(func=cmd_extract)

    pn = sub.add_parser("normalize", help="中間檔 → 對齊詞彙表 + 殘留")
    pn.set_defaults(func=cmd_normalize)

    pw = sub.add_parser("writeback", help="寫回 Atlas（預設 dry-run）")
    pw.add_argument("--db", default="")
    pw.add_argument("--dry-run", action="store_true", help="只預覽不寫（預設行為，加不加都一樣）")
    pw.add_argument("--apply", action="store_true", help="真的寫入；不加則只預覽")
    pw.set_defaults(func=cmd_writeback)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
