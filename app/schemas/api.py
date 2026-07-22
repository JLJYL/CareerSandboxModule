"""對外 API 合約（凍結層）。

原則（詳見 CONTRACTS.md）：
- 欄位名一律 camelCase，逐字鏡射前端 Kotlin data class（org.json 按名取值）。
- List 永遠不為 null：無資料回 []。
- 「輸入寬、輸出嚴」：前端送進來的資料照單全收（str），我們吐出去的受 Literal 約束。
- 合法值與字串風格的出處都標了前端檔案，改動前先看該檔案還在不在。
"""
from typing import Literal
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 合法值（出處：前端程式碼，非交接文件——文件與程式碼衝突時以程式碼為準）
# ---------------------------------------------------------------------------

# CareerExplorationScreen.kt 篩選列；「全部」是 UI 篩選器專用，永不出現在資料中
CareerCategory = Literal["數據", "產品", "設計", "學術"]

# MockData.kt 母版經歷使用的四類
ExperienceCategory = Literal["社團", "工作", "競賽", "學業"]

FindingType = Literal["strength", "gap", "suggestion"]


# ---------------------------------------------------------------------------
# 共用：Experience（鏡射 data/model/Models.kt:34）
# ---------------------------------------------------------------------------

class ExperienceIn(BaseModel):
    """前端送來的母版經歷。category 收 str 不設限——前端是它自己資料的事實來源。"""
    id: str
    title: str
    category: str
    timeRange: str
    description: str
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 端點 1：POST /resume/master/generate（母版生成；無前端原型，我方主筆 → PROPOSAL）
# ---------------------------------------------------------------------------

class MasterGenerateRequest(BaseModel):
    userId: str                       # 帳號系統未建，一律先填 "dev_user_001"
    narratives: list[str] = Field(min_length=1)   # 使用者的口語經歷敘述，一段一條


class DraftExperience(BaseModel):
    """母版經歷「草稿」：Experience 全欄位 + 供前端確認 UI 用的兩個附加欄位。
    org.json 手動取值，前端未升級前多出的欄位天然被忽略，安全。"""
    id: str                           # 草稿 id 規則：e_ai_{n}；使用者確認後由前端定稿
    title: str
    category: ExperienceCategory      # 輸出嚴格：只吐四類之一
    timeRange: str                    # 風格照 MockData："2024.09 - 2025.06"
    description: str
    tags: list[str] = Field(default_factory=list)
    sourceQuote: str                  # 證據句：這條草稿依據使用者哪句話生成（不捏造的執行點）
    confidence: int = Field(ge=0, le=100)


class MasterGenerateResponse(BaseModel):
    draftExperiences: list[DraftExperience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)   # 對齊 ResumeMaster.skills: List<String>


# ---------------------------------------------------------------------------
# 端點 2：POST /career/recommend（C1；鏡射 CareerExplorationScreen.kt:54 CareerRec）
# ---------------------------------------------------------------------------

class CareerRecommendRequest(BaseModel):
    userId: str
    query: str = Field(min_length=1)              # 使用者的自然語言探索描述
    experiences: list[ExperienceIn] = Field(default_factory=list)  # Real service 從本地母版帶上來


class CareerRecOut(BaseModel):
    """注意：前端 CareerRec 還有 icon: ImageVector——UI 型別，不可序列化，API 不含。
    前端抽 provider（D11）時以本地「category → icon」對照表補上。"""
    id: str                           # 純 slug，照前端現值："data_analyst"、"pm"，不加前綴
    title: str
    subtitleEn: str
    shortSubtitle: str                # 風格："數據 · 45-65k"（半形空格 + · + salary）
    salary: str                       # 顯示就緒字串："45-65k"／"依機構"
    openings: str                     # 千分位字串："1,240"，不是數字
    matchScore: int = Field(ge=0, le=100)
    missingSkills: list[str] = Field(default_factory=list)
    category: CareerCategory
    isAcademic: bool = False
    academicNote: str = ""            # 交接文件漏了此欄位；程式碼有，以程式碼為準


class CareerRecommendResponse(BaseModel):
    recommendations: list[CareerRecOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 端點 3/4：POST /jobs/fit-all、POST /jobs/{jobId}/fit（B2；鏡射 FitAnalysisService.kt JobFit）
# 決策：用 POST 不用 GET——Kotlin 介面 fitFor(jobId) 沒有使用者參數，
# 個人化所需的 experiences 由前端 Real service 從本地母版（ResumeHierarchyProvider）
# 取得後放進 body 帶上來。
# ---------------------------------------------------------------------------

class JobsFitRequest(BaseModel):
    userId: str
    experiences: list[ExperienceIn] = Field(default_factory=list)


class JobFitOut(BaseModel):
    jobId: str                        # 風格照前端現值："fit_da"、"fit_pm"
    title: str
    company: str
    tags: list[str] = Field(default_factory=list)
    salary: str                       # 風格："55-85k"
    deadline: str                     # 顯示就緒字串："11/02 截止"
    matchScore: int = Field(ge=0, le=100)
    styleTag: str                     # 例："數據導向型"、"硬實力強"、"溝通導向型"
    requiredSkills: list[str] = Field(default_factory=list)


class JobsFitAllResponse(BaseModel):
    jobs: list[JobFitOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 端點 5：POST /resume/customize（B1；鏡射 JdCustomizer.kt CustomizedItem）
# 注意：coveredKeywords/jdKeywords 在前端掛在 MockJdCustomizer 物件上、不在 interface，
# 但客製結果頁需要它們算命中率 → 一併放進 response，D11/D12 抽 provider 時對齊。
# ---------------------------------------------------------------------------

class CustomizeRequest(BaseModel):
    userId: str
    jobId: str                        # 對應 JobTarget.id；JD 內文由後端依 jobId 取得
    experiences: list[ExperienceIn] = Field(min_length=1)


class CustomizedItemOut(BaseModel):
    text: str                         # 改寫原則：只重排與強調母版既有事實，不捏造
    matchedKeywords: list[str] = Field(default_factory=list)
    highlighted: bool                 # true=強化, false=弱化


class CustomizeResponse(BaseModel):
    jdKeywords: list[str] = Field(default_factory=list)       # 這份 JD 看重的關鍵字
    coveredKeywords: list[str] = Field(default_factory=list)  # 母版涵蓋到的子集
    items: list[CustomizedItemOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 端點 6：POST /resume/overview（B3；前端連 data class 都沒有 → 我方主筆 PROPOSAL，
# 待怡君回簽；順位最低，第三週行有餘力才實作）
# ---------------------------------------------------------------------------

class JobTargetIn(BaseModel):
    """鏡射 ResumeHierarchy.kt JobTarget 的必要子集。"""
    title: str
    company: str
    jdKeywords: list[str] = Field(default_factory=list)


class OverviewRequest(BaseModel):
    userId: str
    experiences: list[ExperienceIn] = Field(default_factory=list)
    jobTargets: list[JobTargetIn] = Field(default_factory=list)


class FindingOut(BaseModel):
    type: FindingType                 # strength / gap / suggestion
    title: str
    detail: str
    relatedSkills: list[str] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    findings: list[FindingOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 統一錯誤格式：前端靠這個形狀（或連線失敗/非 2xx）觸發退回 Mock 的保險絲
# ---------------------------------------------------------------------------

class ErrorBody(BaseModel):
    code: str                         # 機器可讀："llm_unavailable"、"validation_error"…
    message: str                      # 人類可讀，可直接顯示


class ErrorResponse(BaseModel):
    error: ErrorBody
