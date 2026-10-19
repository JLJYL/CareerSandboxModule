"""技能補強配對管線（成員 A）。

對 missingSkills 的每個技能，從資源目錄（課程＋競賽）配對出能補它的資源回給前端。
設計原則與職缺計分一致（交接四第一節）：配對由程式做、LLM 只寫說明、零證據回空。

流程：技能正規化 → 找 skills 含該顯示名的資源 → 排序（本校課程優先 / 競賽近者優先 /
過期競賽剔除）→ 每技能最多 3 筆 → LLM 批次寫 note（防捏造，違規退空）。
配對是確定性的，不跑 WeightedScorer（回的是配對結果，不是分數）。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from app.pipeline.textrules import sanitize_display_text
from app.prompts.resource_skills import (
    NOTE_RETRY_SUFFIX, NOTE_SYSTEM_PROMPT, build_note_prompt,
)
from app.schemas.api import ReinforceItemOut, ReinforceResourceOut, ReinforceResponse

_RESOURCES_PATH = (Path(__file__).resolve().parents[2]
                   / "fixtures" / "resources" / "resources_v1.json")
_MAX_COURSES = 3          # 每技能最多幾門課
_MAX_COMPS = 2            # 每技能最多幾項競賽（與課程分開計，確保競賽也會出現）
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 與 customize.py 同一組評價詞防線：原文沒有就不准寫。
_HYPE_WORDS = ("成功", "精通", "出色", "高效", "優異", "大幅", "卓越", "完美")


def load_resources(path: Path = _RESOURCES_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 競賽來源：正式歸宿是 Mongo（競賽交接文件 2026/10/18）。與職缺一致：DB 優先、fixture 保底。
# ---------------------------------------------------------------------------

_COMPETITIONS_PATH = (Path(__file__).resolve().parents[2]
                      / "fixtures" / "resources" / "competitions_v1.jsonl")


def _from_comp_doc(doc: dict) -> dict:
    """競賽文件（Mongo competitions 或 competitions_v1.jsonl）→ reinforce 的資源形狀。
    唯一鍵用 sourceId（交接文件指定；不可用會隨重爬變動的顯示序 id）。
    deadline 取 deadlineIso 的日期部分（YYYY-MM-DD），給 _expired 比對。"""
    dl = str(doc.get("deadlineIso") or doc.get("deadline") or "")
    return {
        "resourceId": doc.get("sourceId") or doc.get("resourceId") or "",
        "type": "competition",
        "title": doc.get("title", ""),
        "provider": doc.get("organizer") or doc.get("provider", ""),
        "providerKey": "open",
        "url": doc.get("sourceUrl") or doc.get("url", ""),
        "deadline": dl[:10] if len(dl) >= 10 else dl,
        "skills": doc.get("skills") or [],
        "description": doc.get("description", ""),
    }


def _competitions_from_db() -> list[dict] | None:
    """讀後端組的 Mongo `competitions` collection；沿用 jobs_fit 同一把 client 與設定。
    未設定 MONGODB_URI 或連不上 → None，交由 fixture fallback。"""
    try:
        from app.pipeline.jobs_fit import _db
        db = _db()
        if db is None:
            return None
        return [_from_comp_doc(d) for d in db["competitions"].find({})]
    except Exception:
        return None


def _competitions_fixture(path: Path = _COMPETITIONS_PATH) -> list[dict]:
    if not Path(path).exists():
        return []
    return [_from_comp_doc(json.loads(ln))
            for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _load_catalog() -> list[dict]:
    """課程讀 resources_v1.json；競賽優先讀 Mongo，讀不到退 competitions_v1.jsonl。"""
    courses = [r for r in load_resources() if r.get("type") == "course"]
    comps = _competitions_from_db()
    if comps is None:
        comps = _competitions_fixture()
    return courses + comps


# ---------------------------------------------------------------------------
# 配對（確定性）
# ---------------------------------------------------------------------------

def _expired(deadline: str, today: date) -> bool:
    if not deadline:
        return False                      # 空＝年度賽／不限期，不過濾
    try:
        y, m, d = (int(x) for x in deadline.split("-"))
        return date(y, m, d) < today
    except (ValueError, TypeError):
        return False                      # 格式異常不當成過期，交由目錄測試把關


def _match(display_name: str, catalog: list[dict], school: str,
           today: date) -> list[dict]:
    """課程與競賽各給名額（否則課程量大時會把競賽全擠掉，競賽永遠不出現）。
    回傳：本校課→他校課（上限 _MAX_COURSES）在前，未過期競賽（近者優先，上限 _MAX_COMPS）在後。"""
    hits = [r for r in catalog if display_name in (r.get("skills") or [])]
    courses = [r for r in hits if r.get("type") == "course"]
    comps = [r for r in hits if r.get("type") == "competition"
             and not _expired(r.get("deadline", ""), today)]

    def course_key(r):
        own = school and r.get("providerKey") == school
        return (0 if own else 1, r.get("resourceId", ""))   # 本校課優先

    def comp_key(r):
        return (r.get("deadline") or "9999-99-99", r.get("resourceId", ""))  # 近者優先；空的排後

    return (sorted(courses, key=course_key)[:_MAX_COURSES]
            + sorted(comps, key=comp_key)[:_MAX_COMPS])


# ---------------------------------------------------------------------------
# note 批次生成（LLM 只寫說明；三條機械防線同 customize）
# ---------------------------------------------------------------------------

def _note_violation(note: str, resource: dict) -> bool:
    src = f"{resource.get('title', '')} {resource.get('description', '')}"
    src_nums = _NUM_RE.findall(src)
    if any(n not in src_nums for n in _NUM_RE.findall(note)):
        return True
    if any(w in note and w not in src for w in _HYPE_WORDS):
        return True
    return False


def _parse_notes(raw: str, n: int) -> list[str]:
    try:
        notes = json.loads(raw).get("notes", [])
    except (json.JSONDecodeError, AttributeError):
        return [""] * n
    notes = [str(x) for x in notes][:n]
    return notes + [""] * (n - len(notes))     # 補齊到 n，筆數不符時缺的留空


def _generate_notes(llm, pairs: list[tuple]) -> dict[tuple, str]:
    """pairs: [(skill, resource), ...] → {(skill, resourceId): note}。
    一次批次；有違規重試一次；再違規該筆留空。無 llm → 全空。"""
    if llm is None or not pairs:
        return {}
    prompt = build_note_prompt(pairs)
    try:
        notes = _parse_notes(llm.complete(NOTE_SYSTEM_PROMPT, prompt, force_json=True),
                             len(pairs))
    except Exception:
        return {}
    bad = [i for i, (_, r) in enumerate(pairs) if notes[i] and _note_violation(notes[i], r)]
    if bad:
        try:
            retry = _parse_notes(
                llm.complete(NOTE_SYSTEM_PROMPT, prompt + NOTE_RETRY_SUFFIX,
                             force_json=True), len(pairs))
            for i in bad:
                notes[i] = retry[i]
        except Exception:
            pass
    out: dict[tuple, str] = {}
    for i, (skill, r) in enumerate(pairs):
        note = notes[i]
        if note and _note_violation(note, r):     # 重試後仍違規 → 空
            note = ""
        out[(skill, r["resourceId"])] = sanitize_display_text(note) if note else ""
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def reinforce(missing_skills: list[str], *, normalizer, school: str = "",
              llm=None, catalog: list[dict] | None = None,
              today: date | None = None) -> ReinforceResponse:
    catalog = _load_catalog() if catalog is None else catalog
    today = today or date.today()

    plan: list[tuple[str, list[dict]]] = []
    for raw in missing_skills:
        hit = normalizer.normalize(raw)               # 可能是職缺原字 → 對不上回空
        plan.append((raw, _match(hit.name_zh, catalog, school, today) if hit else []))

    pairs = [(skill, r) for skill, rs in plan for r in rs]
    notes = _generate_notes(llm, pairs)

    items = []
    for skill, resources in plan:
        outs = [ReinforceResourceOut(
            resourceId=r["resourceId"], type=r["type"], title=r["title"],
            provider=r.get("provider", ""), url=r.get("url", ""),
            deadline=r.get("deadline", ""),
            note=notes.get((skill, r["resourceId"]), "")) for r in resources]
        items.append(ReinforceItemOut(skill=skill, resources=outs))
    return ReinforceResponse(items=items)
