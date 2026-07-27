"""能力輪廓組裝(成員 B,第 1 週末)。
W1 版:normalizer 可為 None → 原始技能字串全部進 raw_tags(唯一允許的暫時降級)。
W2 起:A 的 VocabNormalizer 插入,對得上的進 skills(帶證據),殘留才進 raw_tags。"""
from collections import Counter

from app.schemas.domain import ExtractedExperience, SkillEvidence, UserProfile


def build_profile(user_id: str, drafts: list[ExtractedExperience],
                  normalizer=None) -> UserProfile:
    skills: dict[str, SkillEvidence] = {}
    residual: Counter[str] = Counter()
    for d in drafts:
        for raw in d.raw_skills:
            canon = normalizer.normalize(raw) if normalizer else None
            if canon is None:
                residual[raw] += 1
            else:
                ev = skills.setdefault(
                    canon.skill_id, SkillEvidence(skill_id=canon.skill_id))
                ev.evidence.append(d.source_quote)
                ev.weight = float(len(ev.evidence))
    raw_tags = [s for s, _ in residual.most_common()]
    return UserProfile(user_id=user_id, skills=list(skills.values()), raw_tags=raw_tags)


def aggregate_display_skills(profile: UserProfile, name_of=None) -> list[str]:
    """給 API response 的 skills 欄位:canonical 名稱在前(W2 起),殘留原字串在後。"""
    named = [name_of(s.skill_id) for s in profile.skills] if name_of else []
    return [n for n in named if n] + profile.raw_tags
