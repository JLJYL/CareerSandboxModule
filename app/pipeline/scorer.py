"""matchScore v1（成員 A，W2）：確定性公式，LLM 只寫解釋、不給分。

score = 100 × ( w_cover × 覆蓋率 ＋ w_sem × 語意相似度 )，四捨五入、夾在 0–100。

覆蓋率（標籤覆蓋加權）：JD 的 required_skills 逐一正規化，看 profile 是否持有——
  經正規化證據命中，計該證據的 weight（夾 0–1）；
  僅 raw_tag 字面相同（未正規化的自述），打 0.6 折；
  沒有就進 missing。covered/missing 用標準顯示名，對不上詞彙表保留原字串。

語意：profile 經歷全文＋技能名 vs jd_text 的 embedding 餘弦，截斷至 [0,1]；
  jd_text 空則不計語意（回 None，不再退回職稱——職稱太短會系統性虛高）。

退化路徑（真實資料的常態），以 score_basis 標示：
  JD 無 required_skills（jobs 七成如此）→ 只剩語意，暫乘 w_cover 壓到同量級（semantic_only）；
  未注入 embedding 或 jd_text 空 → 只剩覆蓋率（coverage_only）；兩者皆無 → 0 分（none）。
  兩腿都在 → both。semantic_only 的壓分為暫定，待黃金集校準（§4）改線性對映。

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
            score, basis = 0, "none"
        elif coverage is None:
            # §2：語意單腿暫以 w_cover 壓到和兩腿同量級（待 §4 校準定案線性對映後取代）
            score, basis = round(100 * semantic * self._w_cover), "semantic_only"
        elif semantic is None:
            score, basis = round(100 * coverage), "coverage_only"
        else:
            score = round(100 * (self._w_cover * coverage + self._w_sem * semantic)
                          / (self._w_cover + self._w_sem))
            basis = "both"
        return FitResult(match_score=max(0, min(100, score)),
                         covered_skills=list(dict.fromkeys(covered)),
                         missing_skills=list(dict.fromkeys(missing)),
                         score_basis=basis)

    # ------------------------------------------------ 內部
    def _semantic(self, profile: UserProfile, job: JobRequirement,
                  required: list[str]) -> float | None:
        if self._embedding is None:
            return None
        jd = (job.jd_text or "").strip()                     # §1：jd_text 空就回 None，不退回職稱
        names = {self._normalizer.display_name(se.skill_id) for se in profile.skills}
        names |= {t for t in profile.raw_tags if t}
        narrative = getattr(profile, "narrative", "") or ""  # §3：經歷全文；B 的欄位未合前退回空字串
        ptxt = " ".join([narrative, *sorted(n for n in names if n)]).strip()  # 排序固定 ⇒ 決定性
        if not jd or not ptxt:
            return None
        va, vb = self._embedding.embed([ptxt, jd])
        return max(0.0, min(1.0, cosine(va, vb)))
