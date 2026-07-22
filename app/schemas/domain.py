"""內部領域模型（snake_case——camelCase 只存在於對外那層，別讓合約污染 codebase）。"""
from pydantic import BaseModel, Field


class CanonicalSkill(BaseModel):
    """標準技能詞彙表的一個條目（成員 A 第 1 週的核心產出）。"""
    skill_id: str                      # 例："skill_sql"
    name_zh: str                       # 例："SQL 資料查詢"
    name_en: str = ""
    aliases: list[str] = Field(default_factory=list)   # 同義詞:"SQL","sql","結構化查詢"
    ucan_code: str = ""                # UCAN 職能代碼（可空，逐步補）
    onet_code: str = ""                # O*NET 對照（可空）


class ExtractedExperience(BaseModel):
    """LLM 結構化擷取的原始輸出（正規化前）。"""
    title: str
    category: str                      # 擷取階段先不強制四類，正規化階段對齊
    time_range: str
    description: str
    raw_skills: list[str] = Field(default_factory=list)  # 未正規化的技能字串
    source_quote: str                  # 證據句
    confidence: int = Field(ge=0, le=100)


class SkillEvidence(BaseModel):
    skill_id: str
    evidence: list[str] = Field(default_factory=list)  # 支持這個技能的經歷 id / 證據句
    weight: float = 1.0


class UserProfile(BaseModel):
    """能力輪廓：所有下游功能的唯一輸入源。"""
    user_id: str
    skills: list[SkillEvidence] = Field(default_factory=list)
    raw_tags: list[str] = Field(default_factory=list)  # 尚無法正規化的殘留標籤


class KBEntry(BaseModel):
    """職涯知識庫條目（落地到 Chroma → Atlas 的單位；成員 A 維護格式）。"""
    id: str                            # kb_{n}
    type: str                          # 對齊 03 落地值: job_skill / career_path / industry
    title: str
    content: str
    skills: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)       # industry / source / careerId…


class RetrievedChunk(BaseModel):
    entry: KBEntry
    score: float                       # 相似度（Fake 階段可為關鍵字命中數）


class JobRequirement(BaseModel):
    job_id: str
    title: str
    required_skills: list[str] = Field(default_factory=list)
    jd_text: str = ""


class FitResult(BaseModel):
    match_score: int = Field(ge=0, le=100)
    covered_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
