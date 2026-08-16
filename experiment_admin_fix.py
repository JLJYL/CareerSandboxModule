"""admin 語義壓制修法比較實驗(對照 A 建議的方案 1 與方案 2)。
用七個失手案,比較三種計分方式對「正確答案能否進前三」的效果:
  現況    :無摘錄時用「標題+技能清單」當語義文本(admin 虛高的來源)
  方案1   :無摘錄時語義設 None,只計覆蓋率
  方案2   :通用職涯(骨架技能跨職涯出現率高)語義打折
用法:放 repo 根目錄 → python experiment_admin_fix.py
純實驗,不改任何正式程式。約一兩分鐘。
"""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")

from app.api.routes import _build_reco_deps
from app.pipeline.recommend import profile_from_experiences, _usable_chunks
from app.schemas.api import ExperienceIn
from app.schemas.domain import JobRequirement
from app.pipeline.scorer import norm_key, RAW_TAG_DISCOUNT, cosine

deps = _build_reco_deps()
if deps is None:
    print("依賴建不起來,請在平常那台機器跑")
    raise SystemExit
retriever, scorer, normalizer = deps
cat = json.load(open("fixtures/careers/careers_v1.json", encoding="utf-8"))
rows = [json.loads(l) for l in open("fixtures/eval/persona_150.jsonl", encoding="utf-8") if l.strip()]

# 通用職涯判準(方案2用):骨架技能有 >=40% 出現在其他職涯骨架 → 視為通用
span = Counter(s for c in cat for s in c["requiredSkills"])
def generic_ratio(career):
    if not career["requiredSkills"]:
        return 0.0
    shared = sum(1 for s in career["requiredSkills"] if span[s] >= len(cat) * 0.3)
    return shared / len(career["requiredSkills"])
GENERIC_CAREERS = {c["id"] for c in cat if generic_ratio(c) >= 0.5}
print(f"方案2 判定的通用職涯: {sorted(GENERIC_CAREERS)}\n")

MISSES = [
    ("網頁設計師", "graphic_designer"), ("產品維修人員", "technician"),
    ("調酒師／吧台人員", "food_service"), ("儲備幹部", "operations_mgmt"),
    ("國貿助理", "sales"), ("OP／旅行社人員", "travel"),
    ("工務人員／助理", "technician"),
]


def coverage_of(prof, req):
    held = {se.skill_id: se.weight for se in prof.skills}
    raw = {norm_key(t) for t in prof.raw_tags if t}
    credit = 0.0
    for r in req:
        sk = normalizer.normalize(r)
        if sk and sk.skill_id in held:
            credit += held[sk.skill_id]
        elif norm_key(r) in raw:
            credit += RAW_TAG_DISCOUNT
    return (credit / len(req)) if req else None


def semantic_of(prof, career, snip, mode):
    req = career["requiredSkills"]
    jd = " ".join(snip.get(career["id"], [])[:2]).strip()
    if not jd:
        if mode == "plan1":              # 方案1:無摘錄 → 語義 None
            return None
        jd = " ".join([career["title"], *req])
    names = {normalizer.display_name(se.skill_id) for se in prof.skills}
    names |= {t for t in prof.raw_tags if t}
    ptxt = " ".join(sorted(n for n in names if n))
    if not jd or not ptxt:
        return None
    va, vb = scorer._embedding.embed([ptxt, jd])
    sem = max(0.0, min(1.0, cosine(va, vb)))
    if mode == "plan2" and career["id"] in GENERIC_CAREERS and not \
            " ".join(snip.get(career["id"], [])).strip():
        sem *= 0.6                        # 方案2:通用職涯無摘錄時語義打6折
    return sem


def combine(cov, sem, wc=0.65, ws=0.35):
    if cov is None and sem is None:
        return 0
    if cov is None:
        return round(100 * sem)
    if sem is None:
        return round(100 * cov)
    return round(100 * (wc * cov + ws * sem) / (wc + ws))


def rank_for(prof, snip, mode):
    scored = []
    for c in cat:
        cov = coverage_of(prof, c["requiredSkills"])
        sem = semantic_of(prof, c, snip, mode)
        sc = combine(cov, sem)
        if sc >= 30:
            scored.append((c["id"], sc))
    scored.sort(key=lambda x: -x[1])
    return scored


results = {"現況": 0, "方案1": 0, "方案2": 0}
MODES = {"現況": "now", "方案1": "plan1", "方案2": "plan2"}
print(f"{'目標':<16}{'正確答案':<18}{'現況':<8}{'方案1':<8}{'方案2':<8}")
print("-" * 60)
for target, correct in MISSES:
    p = next((x for x in rows if x.get("career", {}).get("targetOccupation") == target), None)
    if not p:
        continue
    owned = p.get("skills", {}).get("owned", [])
    exp0 = (p.get("experiences") or [{}])[0]
    prof = profile_from_experiences("t", [ExperienceIn(
        id="e1", title=exp0.get("title", "經歷"), category="工作", timeRange="",
        description=exp0.get("title", ""), tags=owned)], normalizer)
    chunks = _usable_chunks(retriever.search(p["aboutMe"], k=8))
    snip = {}
    for ch in chunks:
        cc = ch.entry.metadata.get("careerId")
        if cc:
            snip.setdefault(cc, []).append(ch.entry.content)

    row = []
    for label, mode in MODES.items():
        ranked = rank_for(prof, snip, mode)
        top3 = [cid for cid, _ in ranked[:3]]
        hit = correct in top3
        if hit:
            results[label] += 1
        pos = next((i + 1 for i, (cid, _) in enumerate(ranked) if cid == correct), None)
        row.append(f"{'中' if hit else '✗'}({pos})" if pos else "✗(-)")
    print(f"{target:<16}{correct:<18}{row[0]:<8}{row[1]:<8}{row[2]:<8}")

print("-" * 60)
print(f"{'七案命中數':<34}{results['現況']:<8}{results['方案1']:<8}{results['方案2']:<8}")
print("\n判讀:命中數越高越好;但注意 A 的提醒——")
print("  方案1 若讓調酒師案(admin覆蓋率本就高)的正確答案仍進不了前三,屬正常(那是產品張力)")
print("  重點看方案能否修好「語義落差」型的案子(網頁設計/儲備幹部/工務等)")
