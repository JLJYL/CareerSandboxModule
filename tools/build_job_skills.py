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
from app.pipeline.job_skills import (  # noqa: E402  prompt/解析/過濾與端點共用同一份
    build_system, filter_vocab, format_jobs, parse_items, vocab_names)
from app.pipeline.normalize import VocabNormalizer  # noqa: E402

_RAW = REPO / "data" / "job_skills_raw.jsonl"
_NORM = REPO / "data" / "job_skills_normalized.jsonl"
_RESID = REPO / "data" / "job_skills_residuals.json"
_COLL = "jobs"
_EMPTY_QUERY = {"$or": [{"requiredSkills": {"$exists": False}},
                       {"requiredSkills": None}, {"requiredSkills": []}]}


# ---------------------------------------------------------------------------
# extract（prompt／解析／詞彙表過濾已移到 app/pipeline/job_skills.py，與端點共用同一份）
# ---------------------------------------------------------------------------


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
    vocab = vocab_names()
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
            system = build_system(vocab)
            for start in range(0, len(llm_jobs), args.batch):
                batch = llm_jobs[start:start + args.batch]
                # JD 組文：conditionOther（條件）放前面、description（含公司介紹）在後，
                # 避免上限內被公司介紹擠掉條件（format_jobs 內再截到 _MAX_JD）。
                batch_jobs = [{"title": j.get("title", ""),
                               "jd": "\n".join(p for p in (j.get("conditionOther"),
                                                           j.get("description")) if p)}
                              for j in batch]
                try:
                    picks = parse_items(
                        llm.complete(system, format_jobs(batch_jobs), force_json=True), len(batch))
                except Exception as e:
                    print(f"  ! batch {start} 失敗：{e}", flush=True)
                    picks = [[] for _ in batch]
                for k, j in enumerate(batch):
                    valid = filter_vocab(picks[k], vocab_set)   # 防自創
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
    vocab_set = set(vocab_names())
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
