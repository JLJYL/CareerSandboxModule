"""C1 推薦管線(成員 B)。流程:
輪廓(正規化) → 檢索(article 以 sourceId 去重) → 候選(型錄∩檢索,空則全型錄)
→ Scorer 確定性計分 → LLM 排序(失敗退分數排序) → 組裝 CareerRecOut。

分工鐵律:分數與差集只認 Scorer;LLM 只排序與寫學術備註;所有展示文字過 sanitize。
"""
import json
from pathlib import Path

from app.pipeline.textrules import sanitize_display_text
from app.prompts.recommend import RETRY_SUFFIX, SYSTEM_PROMPT, build_rank_prompt
from app.schemas.api import CareerRecOut, ExperienceIn
from app.schemas.domain import JobRequirement, SkillEvidence, UserProfile

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "careers" / "careers_v1.json"


def load_catalog(path: Path = _CATALOG_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def profile_from_experiences(user_id: str, experiences: list[ExperienceIn],
                             normalizer) -> UserProfile:
    """已結構化的母版經歷 → 輪廓(tags 走正規化;對不上進殘留區)。"""
    skills: dict[str, SkillEvidence] = {}
    residual: list[str] = []
    for exp in experiences:
        for raw in exp.tags:
            canon = normalizer.normalize(raw) if normalizer else None
            if canon is None:
                if raw not in residual:
                    residual.append(raw)
            else:
                ev = skills.setdefault(canon.skill_id,
                                       SkillEvidence(skill_id=canon.skill_id))
                ev.evidence.append(exp.title)
                ev.weight = float(len(ev.evidence))
    return UserProfile(user_id=user_id, skills=list(skills.values()), raw_tags=residual)


def _usable_chunks(chunks) -> list:
    """先剔除 metadata.offtopic=true 的雜訊(A 標註的發票/颱風等民生新聞),再同篇去重。"""
    return _dedupe_chunks([c for c in chunks if not c.entry.metadata.get("offtopic")])


def _dedupe_chunks(chunks) -> list:
    """article 切塊同篇只留最高分(合約:同篇引用一次)。非 article 原樣保留。"""
    best: dict[str, object] = {}
    out = []
    for c in chunks:
        sid = c.entry.metadata.get("sourceId")
        if not sid:
            out.append(c)
            continue
        if sid not in best or c.score > best[sid].score:
            best[sid] = c
    return out + list(best.values())


def _llm_rank(llm, query, skill_names, candidates) -> tuple[list[str], dict]:
    """回 (order, notes);任何不合規 → 拋 ValueError 讓上層退分數排序。"""
    raw = llm.complete(SYSTEM_PROMPT, build_rank_prompt(query, skill_names, candidates),
                       force_json=True)
    data = json.loads(raw)
    legal = {c["id"] for c in candidates}
    order = [i for i in data.get("order", []) if i in legal]
    if not order:
        raise ValueError("order 為空或全非法")
    notes = {k: str(v) for k, v in (data.get("notes") or {}).items() if k in legal}
    return order, notes


def recommend(query: str, experiences: list[ExperienceIn], *, normalizer, retriever,
              scorer, llm=None, catalog: list[dict] | None = None,
              top_n: int = 3, min_score: int = 30) -> list[CareerRecOut]:
    catalog = catalog if catalog is not None else load_catalog()
    profile = profile_from_experiences("dev_user_001", experiences, normalizer)
    skill_names = [normalizer.display_name(s.skill_id) for s in profile.skills] \
        + profile.raw_tags if normalizer else profile.raw_tags

    chunks = _usable_chunks(retriever.search(query, k=8)) if retriever else []
    seen_cids = {c.entry.metadata.get("careerId") for c in chunks} - {None}  # 僅供紀錄/摘錄
    # 候選一律全型錄:型錄僅個位數格,全量計分成本趨零;且 93% 的庫是未標 careerId
    # 的 article(啞巴選民),靠檢索提名會餓死候選——待 A 補標與型錄長大後再回來做 ∩ 最佳化。
    pool = list(catalog)

    snippets: dict[str, list[dict]] = {}
    for c in chunks:
        cid = c.entry.metadata.get("careerId")
        if cid:
            snippets.setdefault(cid, []).append(
                {"text": c.entry.content, "url": c.entry.metadata.get("url", "")})

    candidates = []
    for c in pool:
        if not c.get("requiredSkills") and not snippets.get(c["id"]):
            continue  # 零證據不參賽:無技能骨架也無知識摘錄,任何分數都無從有據——
            #           寧可缺席,不端中性分誤導使用者(缺[]會被讀成「你什麼都不缺」)
        fit = scorer.score(profile, JobRequirement(
            job_id=c["id"], title=c["title"],
            required_skills=c.get("requiredSkills", []),
            jd_text=" ".join(s["text"] for s in snippets.get(c["id"], [])[:2])))
        candidates.append({**c, "matchScore": fit.match_score,
                           "missing": fit.missing_skills,
                           "snippets": snippets.get(c["id"], [])})

    candidates = [c for c in candidates if c["matchScore"] >= min_score]
    if not candidates:
        return []                                   # 優雅退場:寧可不推,不硬編

    order_ids, notes = None, {}
    if llm is not None:
        try:
            order_ids, notes = _llm_rank(llm, query, skill_names, candidates)
        except Exception:
            try:  # 帶病歷重試一次
                raw2 = llm.complete(
                    SYSTEM_PROMPT,
                    build_rank_prompt(query, skill_names, candidates) + RETRY_SUFFIX,
                    force_json=True)
                data = json.loads(raw2)
                legal = {c["id"] for c in candidates}
                order_ids = [i for i in data.get("order", []) if i in legal] or None
                notes = {k: str(v) for k, v in (data.get("notes") or {}).items()}
            except Exception:
                order_ids = None                    # LLM 罷工 → 純分數排序照樣出貨

    by_id = {c["id"]: c for c in candidates}
    if order_ids:
        ranked = [by_id[i] for i in order_ids]
        ranked += sorted((c for c in candidates if c["id"] not in set(order_ids)),
                         key=lambda c: -c["matchScore"])
    else:
        ranked = sorted(candidates, key=lambda c: -c["matchScore"])

    out = []
    for c in ranked[:top_n]:
        note = sanitize_display_text(notes.get(c["id"], "")) if c["isAcademic"] else ""
        out.append(CareerRecOut(
            id=c["id"], title=c["title"], subtitleEn=c["subtitleEn"],
            shortSubtitle=f"{c['category']} · {c['salary']}",
            salary=c["salary"], openings=c["openings"],
            matchScore=c["matchScore"], missingSkills=c["missing"],
            category=c["category"], isAcademic=c["isAcademic"], academicNote=note))
    return out
