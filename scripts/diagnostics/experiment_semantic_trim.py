"""小實驗:語義文本收斂能否壓低 admin 的虛高語義分。
測試方案:當職涯用技能清單當語義文本時,去掉辦公三寶(Excel/Word/PPT/Outlook)、
只保留特色技能上限 5 個。看 admin 的語義分有沒有降、正確答案有沒有相對浮上。
用法:放 repo 根目錄 → python experiment_semantic_trim.py
純實驗,不改任何檔案。約一分鐘。
"""
import json
import sys

sys.path.insert(0, ".")

from app.api.routes import _build_reco_deps
from app.pipeline.recommend import profile_from_experiences
from app.schemas.api import ExperienceIn
from app.pipeline.scorer import cosine

deps = _build_reco_deps()
if deps is None:
    print("依賴建不起來,請在平常那台機器跑")
    raise SystemExit
retriever, scorer, normalizer = deps
cat = json.load(open("fixtures/careers/careers_v1.json", encoding="utf-8"))
by_id = {c["id"]: c for c in cat}
rows = [json.loads(l) for l in open("fixtures/eval/persona_150.jsonl", encoding="utf-8") if l.strip()]

GENERIC_OFFICE = {"Excel", "Word", "PowerPoint", "Outlook"}


def sem_score(prof, text):
    names = {normalizer.display_name(se.skill_id) for se in prof.skills}
    names |= {t for t in prof.raw_tags if t}
    ptxt = " ".join(sorted(n for n in names if n))
    if not ptxt or not text:
        return 0.0
    va, vb = scorer._embedding.embed([ptxt, text])
    return max(0.0, min(1.0, cosine(va, vb)))


def text_old(c):
    return " ".join([c["title"]] + c["requiredSkills"])


def text_new(c):
    special = [s for s in c["requiredSkills"] if s not in GENERIC_OFFICE]
    return " ".join([c["title"]] + special[:5])


CASES = [
    ("網頁設計師", "graphic_designer"),
    ("儲備幹部", "operations_mgmt"),
    ("工務人員／助理", "technician"),
    ("產品維修人員", "technician"),
]

print("實驗:語義文本去辦公三寶+收斂上限5\n")
print(f"{'案子':<16}{'第一名':<16}{'admin舊→新語義':<18}{'正確答案語義'}")
print("-" * 66)
for target, correct in CASES:
    p = next((x for x in rows if x.get("career", {}).get("targetOccupation") == target), None)
    if not p:
        continue
    owned = p.get("skills", {}).get("owned", [])
    exp0 = (p.get("experiences") or [{}])[0]
    prof = profile_from_experiences("t", [ExperienceIn(
        id="e1", title=exp0.get("title", "經歷"), category="工作", timeRange="",
        description=exp0.get("title", ""), tags=owned)], normalizer)

    admin = by_id["admin"]
    old_a = sem_score(prof, text_old(admin))
    new_a = sem_score(prof, text_new(admin))
    corr = by_id[correct]
    corr_old = sem_score(prof, text_old(corr))
    corr_new = sem_score(prof, text_new(corr))
    print(f"{target:<16}{'admin':<16}{old_a:.2f} → {new_a:.2f}       {correct} {corr_old:.2f}→{corr_new:.2f}")

print("\n判讀:")
print("  admin 語義若明顯下降(如 0.80→0.60),且正確答案語義維持或上升 → 方案有效")
print("  admin 語義幾乎不動 → 收斂沒用,問題不在辦公三寶,得換方向")
