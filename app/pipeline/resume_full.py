"""客製化完整履歷組裝層(契約 v1)。

在 B1 customize() 之上加一層純確定性組裝——零 LLM、零狀態:
  header  : eduLine 拼顯示就緒字串;bio 原文照登。
  contact : 五欄空值省略鍵(該行自然不印)。
  skills  : prioritized = 使用者技能中屬 coveredKeywords 者(過正規化,母版序);others = 其餘(母版序)。
  experiences : 強化條在前(依 matchedKeywords 數多到少,平手母版序),弱化條在後(母版序);
                每條自帶 title/timeRange;弱化一律包含;不帶 highlighted。
"""
from app.pipeline.customize import _canon_id, customize
from app.schemas.api import (CustomizeFullResponse, ExperienceIn, ProfileIn, ResumeExperienceOut,
                             ResumeHeaderOut, ResumeSkillsOut)

_CONTACT_KEYS = ("email", "phone", "linkedin", "github", "portfolio")


def build_edu_line(profile: ProfileIn) -> str:
    """school · department · year,空段落跳過。"""
    return " · ".join(s for s in (profile.school, profile.department, profile.year) if s.strip())


def split_skills(skills_have: list[str], covered: list[str], normalizer) -> tuple[list[str], list[str]]:
    """依正規化 id 判定使用者技能是否屬職缺看重的已具備集;兩組各保母版序。"""
    covered_ids = {_canon_id(normalizer, k) or k.strip().lower() for k in covered}
    prioritized, others = [], []
    for s in skills_have:
        key = _canon_id(normalizer, s) or s.strip().lower()
        (prioritized if key in covered_ids else others).append(s)
    return prioritized, others


def order_experiences(exps: list[ExperienceIn], items) -> list[ResumeExperienceOut]:
    """items 與 exps 一對一同序(B1 保證);依契約排序規則產出顯示順序。"""
    rows = [(i, e, it) for i, (e, it) in enumerate(zip(exps, items))]
    strong = sorted((r for r in rows if r[2].highlighted),
                    key=lambda r: (-len(r[2].matchedKeywords), r[0]))
    weak = [r for r in rows if not r[2].highlighted]
    return [ResumeExperienceOut(title=e.title, timeRange=e.timeRange, text=it.text,
                                matchedKeywords=list(it.matchedKeywords))
            for _, e, it in strong + weak]


def customize_full(job: dict, profile: ProfileIn, exps: list[ExperienceIn], *,
                   normalizer, llm=None) -> CustomizeFullResponse:
    b1 = customize(job, exps, normalizer=normalizer, llm=llm)
    prioritized, others = split_skills(profile.skillsHave, b1.coveredKeywords, normalizer)
    contact = {k: getattr(profile, k) for k in _CONTACT_KEYS if getattr(profile, k).strip()}
    return CustomizeFullResponse(
        header=ResumeHeaderOut(name=profile.name, eduLine=build_edu_line(profile), bio=profile.bio),
        contact=contact,
        skills=ResumeSkillsOut(prioritized=prioritized, others=others, languages=profile.languages),
        experiences=order_experiences(exps, b1.items),
    )
