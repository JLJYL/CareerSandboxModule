"""matchScore v1（成員 A，W2）：確定性公式，LLM 只寫解釋、不給分。

score = 100 × ( w_cover × 覆蓋率 ＋ w_sem × 語意相似度 )，四捨五入、夾在 0–100。

覆蓋率（標籤覆蓋加權）：JD 的 required_skills 逐一正規化，看 profile 是否持有——
  經正規化證據命中，計該證據的 weight（夾 0–1）；
  僅 raw_tag 字面相同（未正規化的自述），打 0.6 折；
  沒有就進 missing。covered/missing 用標準顯示名，對不上詞彙表保留原字串。

語意：profile 技能名彙總文字 vs jd_text（無 jd_text 用 title＋required 頂）
  的 embedding 餘弦，截斷至 [0,1]。

退化路徑（真實資料的常態）：
  JD 無 required_skills（jobs_all 七成如此）→ 權重全給語意；
  未注入 embedding → 權重全給覆蓋率；兩者皆無 → 0 分。

決定性保證：輸入排序固定、embedding provider 決定性 ⇒ 同 profile 同 job 同分。
w_cover/w_sem 預設 0.65/0.35 與正規化門檻同屬待校準參數，W3 黃金測試集回歸定案。
"""
from __future__ import annotations

from app.pipeline.normalize import VocabNormalizer, cosine
from app.pipeline.vocab import norm_key
from app.providers.embeddings import EmbeddingProvider
from app.schemas.domain import FitResult, JobRequirement, UserProfile

RAW_TAG_DISCOUNT = 0.6  # 未經正規化驗證的自述標籤折扣


class WeightedScorer:
    def __init__(self, normalizer: VocabNormalizer,
                 embedding: EmbeddingProvider | None = None,
                 w_cover: float = 0.65, w_sem: float = 0.35):
        self._normalizer = normalizer
        self._embedding = embedding
        self._w_cover = w_cover
        self._w_sem = w_sem

    # ------------------------------------------------ Scorer Protocol
    def score(self, profile: UserProfile, job: JobRequirement) -> FitResult:
        held = {}
        for se in profile.skills:
            w = max(0.0, min(1.0, se.weight))
            held[se.skill_id] = max(w, held.get(se.skill_id, 0.0))
        raw_tags = {norm_key(t) for t in profile.raw_tags if t}

        required = [r.strip() for r in (job.required_skills or []) if r and r.strip()]
        covered: list[str] = []
        missing: list[str] = []
        credit = 0.0
        for r in required:
            skill = self._normalizer.normalize(r)
            display = skill.name_zh if skill else r
            if skill and skill.skill_id in held:
                credit += held[skill.skill_id]
                covered.append(display)
            elif norm_key(r) in raw_tags:
                credit += RAW_TAG_DISCOUNT
                covered.append(display)
            else:
                missing.append(display)
        coverage = (credit / len(required)) if required else None

        semantic = self._semantic(profile, job, required)

        if coverage is None and semantic is None:
            score = 0
        elif coverage is None:
            score = round(100 * semantic)
        elif semantic is None:
            score = round(100 * coverage)
        else:
            score = round(100 * (self._w_cover * coverage + self._w_sem * semantic)
                          / (self._w_cover + self._w_sem))
        return FitResult(match_score=max(0, min(100, score)),
                         covered_skills=list(dict.fromkeys(covered)),
                         missing_skills=list(dict.fromkeys(missing)))

    # ------------------------------------------------ 內部
    def _semantic(self, profile: UserProfile, job: JobRequirement,
                  required: list[str]) -> float | None:
        if self._embedding is None:
            return None
        jd = (job.jd_text or "").strip() or " ".join([job.title, *required]).strip()
        names = {self._normalizer.display_name(se.skill_id) for se in profile.skills}
        names |= {t for t in profile.raw_tags if t}
        ptxt = " ".join(sorted(n for n in names if n))       # 排序固定 ⇒ 決定性
        if not jd or not ptxt:
            return None
        va, vb = self._embedding.embed([ptxt, jd])
        return max(0.0, min(1.0, cosine(va, vb)))
