"""調酒師案分數拆解診斷器。
在完整環境跑,把 admin 和 food_service 的覆蓋率分/語義分/加權/合成分全部印出來。
用法:放 repo 根目錄 → python diagnose_bartender.py
只跑 1 個 persona × 幾個職涯,幾十秒。純診斷,不改任何檔案。
"""
import json
import sys

sys.path.insert(0, ".")

from app.api.routes import _build_reco_deps
from app.pipeline.recommend import profile_from_experiences
from app.schemas.api import ExperienceIn
from app.schemas.domain import JobRequirement

deps = _build_reco_deps()
if deps is None:
    print("依賴建不起來,請確認在平常那台機器、且已 pip install 完整")
    raise SystemExit
retriever, scorer, normalizer = deps

# 找出調酒師 persona
rows = [json.loads(l) for l in open("fixtures/eval/persona_150.jsonl", encoding="utf-8") if l.strip()]
p = next(x for x in rows if x.get("career", {}).get("targetOccupation") == "調酒師／吧台人員")
query = p["aboutMe"]
owned = p.get("skills", {}).get("owned", [])
exp0 = (p.get("experiences") or [{}])[0]
prof = profile_from_experiences("t", [ExperienceIn(
    id="e1", title=exp0.get("title", "經歷"), category="工作", timeRange="",
    description=exp0.get("title", ""), tags=owned)], normalizer)

print(f"使用者描述:{query}")
print(f"使用者技能:{owned}\n")

# 檢索這個 query 拿到的摘錄,分給各職涯
from app.pipeline.recommend import _usable_chunks
chunks = _usable_chunks(retriever.search(query, k=8))
snip = {}
for c in chunks:
    cid = c.entry.metadata.get("careerId")
    if cid:
        snip.setdefault(cid, []).append(c.entry.content)
print(f"檢索到 {len(chunks)} 塊摘錄,涉及職涯:{list(snip.keys()) or '無(全是未標 careerId 的文章)'}\n")

cat = json.load(open("fixtures/careers/careers_v1.json", encoding="utf-8"))
targets = ["admin", "reception", "operations_mgmt", "food_service", "customer_service"]

print(f"{'職涯':<16}{'覆蓋率':>8}{'語義分':>8}{'合成':>6}  說明")
print("-" * 60)
for cid in targets:
    career = next((x for x in cat if x["id"] == cid), None)
    if not career:
        continue
    jd = " ".join(snip.get(cid, [])[:2])
    req = career["requiredSkills"]

    # 手動拆解(複製 scorer 邏輯)
    held = {se.skill_id: se.weight for se in prof.skills}
    from app.pipeline.scorer import norm_key, RAW_TAG_DISCOUNT
    raw_tags = {norm_key(t) for t in prof.raw_tags if t}
    credit = 0.0
    for r in req:
        sk = normalizer.normalize(r)
        if sk and sk.skill_id in held:
            credit += held[sk.skill_id]
        elif norm_key(r) in raw_tags:
            credit += RAW_TAG_DISCOUNT
    coverage = credit / len(req) if req else None

    job = JobRequirement(job_id=cid, title=career["title"], required_skills=req, jd_text=jd)
    semantic = scorer._semantic(prof, job, req)

    result = scorer.score(prof, job)
    src = "有摘錄" if jd else "無摘錄→用標題+技能當文本"
    cov_s = f"{coverage:.2f}" if coverage is not None else "—"
    sem_s = f"{semantic:.2f}" if semantic is not None else "—"
    star = "  ← 正確答案" if cid == "food_service" else ""
    print(f"{cid:<16}{cov_s:>8}{sem_s:>8}{result.match_score:>6}  {src}{star}")

print(f"\n加權設定:覆蓋率權重 {scorer._w_cover} / 語義權重 {scorer._w_sem}")
print("判讀:若 admin 的語義分明顯高於 food_service,問題在語義計算(A 的計分器);")
print("      若 admin 覆蓋率高而 food_service 覆蓋率低,問題在骨架或門檻。")
