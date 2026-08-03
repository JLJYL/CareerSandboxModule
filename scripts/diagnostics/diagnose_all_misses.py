"""七個失手案的分數拆解診斷器。
對每個失手案,把正確答案 vs 實際前三名的覆蓋率/語義分/合成分拆開,
判斷病因是「覆蓋率落差」(技能與志向不符)還是「語義落差」(缺摘錄)。
用法:放 repo 根目錄 → python diagnose_all_misses.py
只跑 7 個 persona,約一兩分鐘。純診斷,不改檔案。
"""
import json
import sys

sys.path.insert(0, ".")

from app.api.routes import _build_reco_deps
from app.pipeline.recommend import profile_from_experiences, _usable_chunks
from app.schemas.api import ExperienceIn
from app.schemas.domain import JobRequirement
from app.pipeline.scorer import norm_key, RAW_TAG_DISCOUNT

deps = _build_reco_deps()
if deps is None:
    print("依賴建不起來,請確認在平常那台機器")
    raise SystemExit
retriever, scorer, normalizer = deps
cat = json.load(open("fixtures/careers/careers_v1.json", encoding="utf-8"))
by_id = {c["id"]: c for c in cat}

# 七個失手案:(目標職業字串, 正確 careerId)
MISSES = [
    ("網頁設計師", "graphic_designer"),
    ("產品維修人員", "technician"),
    ("調酒師／吧台人員", "food_service"),
    ("儲備幹部", "operations_mgmt"),
    ("國貿助理", "sales"),
    ("OP／旅行社人員", "travel"),
    ("工務人員／助理", "technician"),
]

rows = [json.loads(l) for l in open("fixtures/eval/persona_150.jsonl", encoding="utf-8") if l.strip()]


def decompose(prof, cid, snip):
    career = by_id.get(cid)
    if not career:
        return None
    jd = " ".join(snip.get(cid, [])[:2])
    req = career["requiredSkills"]
    held = {se.skill_id: se.weight for se in prof.skills}
    raw_tags = {norm_key(t) for t in prof.raw_tags if t}
    credit = 0.0
    for r in req:
        sk = normalizer.normalize(r)
        if sk and sk.skill_id in held:
            credit += held[sk.skill_id]
        elif norm_key(r) in raw_tags:
            credit += RAW_TAG_DISCOUNT
    coverage = credit / len(req) if req else 0
    job = JobRequirement(job_id=cid, title=career["title"], required_skills=req, jd_text=jd)
    sem = scorer._semantic(prof, job, req)
    score = scorer.score(prof, job).match_score
    return coverage, (sem or 0), score, bool(jd)


for target, correct_cid in MISSES:
    p = next((x for x in rows if x.get("career", {}).get("targetOccupation") == target), None)
    if not p:
        continue
    query = p["aboutMe"]
    owned = p.get("skills", {}).get("owned", [])
    exp0 = (p.get("experiences") or [{}])[0]
    prof = profile_from_experiences("t", [ExperienceIn(
        id="e1", title=exp0.get("title", "經歷"), category="工作", timeRange="",
        description=exp0.get("title", ""), tags=owned)], normalizer)
    chunks = _usable_chunks(retriever.search(query, k=8))
    snip = {}
    for c in chunks:
        cc = c.entry.metadata.get("careerId")
        if cc:
            snip.setdefault(cc, []).append(c.entry.content)

    # 正確答案的拆解
    correct = decompose(prof, correct_cid, snip)
    # 找出實際拿第一名的職涯(對全型錄計分取最高)
    best_cid, best_score = None, -1
    for c in cat:
        r = decompose(prof, c["id"], snip)
        if r and r[2] > best_score:
            best_cid, best_score = c["id"], r[2]
    top = decompose(prof, best_cid, snip)

    print(f"\n目標「{target}」該中 {correct_cid}")
    print(f"  技能:{owned}")
    print(f"  {correct_cid:<18}覆蓋 {correct[0]:.2f}  語義 {correct[1]:.2f}  合成 {correct[2]}  ← 正確答案")
    print(f"  {best_cid:<18}覆蓋 {top[0]:.2f}  語義 {top[1]:.2f}  合成 {top[2]}  ← 實際第一名")
    cov_gap = top[0] - correct[0]
    sem_gap = top[1] - correct[1]
    cause = "覆蓋率落差(技能與志向不符)" if cov_gap > sem_gap else "語義落差(正確答案缺摘錄)"
    print(f"  病因:{cause}(覆蓋差 {cov_gap:+.2f} / 語義差 {sem_gap:+.2f})")

print("\n" + "=" * 56)
print("彙總判讀:若七案多數是覆蓋率落差 → 產品張力(想做 vs 現在會),需討論;")
print("          若多數是語義落差 → A 補摘錄可解;混合則分開處理。")
