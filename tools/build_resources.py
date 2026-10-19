"""資源目錄生成器（成員 A）——把原始課程與人工競賽清單，烤成 /skills/reinforce 讀的目錄。

兩段式，對應交接文件四第七節：

  extract：讀原始課程檔（courses_dedup.jsonl）→ 篩本校＋字面重疊 → LLM 抽「修完具備的技能」
           → 中間檔 data/resources_raw_skills.jsonl（含 rawSkills，未正規化）。
           LLM 只負責「從大綱抽技能」，不要求它用詞彙表字（會硬湊），抽完交第二段對。

  build：讀中間檔 → VocabNormalizer(0.88) 把 rawSkills 對成詞彙表 name_zh（對不上進殘留）
         → 併入人工競賽 CSV → 寫 fixtures/resources/resources_v1.json
         → 殘留清單寫 docs/resources_residuals_report.md（給 B 覆核、補 alias）。

為什麼分兩段：LLM 抽取要花錢且慢，抽一次存成中間檔；之後調正規化門檻、改競賽清單，
只需重跑 build（免錢免模型）。這也是「交棒靠 Fake 不靠等待」。

沒有 LLM 金鑰時的兩條路：
  --no-llm   只輸出通過字面預篩的課，rawSkills 留空（純驗流程）。
  --literal  免金鑰字面抽取：掃「課名」命中詞彙表表面形當技能（排除 AI/ML/TS 等
             ASCII≤2 別名，否則任何帶 AI 字樣的課都會被塞成機器學習）。精確度不如
             LLM 讀大綱，但課名訊號強、可直接產出堪用目錄；拿到金鑰後重跑 extract 升級。

courses_dedup.jsonl 的欄位名尚未定（檔案在爬蟲端），故欄位全部可由 CLI 覆寫，
並對常見命名做自動探測；對不到就報錯印出該筆實際有的鍵，不要猜著硬塞。

用法：
  python tools/build_resources.py extract --courses data/courses_dedup.jsonl \
      --school nsysu --provider "國立中山大學" --out data/resources_raw_skills.jsonl
      [--title-field 課程名稱] [--outline-field 課程大綱] [--school-field 開課學校]
      [--dept-field 開課系所] [--url-field 課程網址] [--no-llm] [--limit N]

  python tools/build_resources.py build --raw data/resources_raw_skills.jsonl \
      --competitions data/competitions_manual.csv \
      --out fixtures/resources/resources_v1.json \
      --residuals docs/resources_residuals_report.md [--real]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.pipeline.normalize import VocabNormalizer            # noqa: E402
from app.pipeline.vocab import VOCAB_PATH, load_vocabulary    # noqa: E402

# courses_dedup.jsonl 欄位的候選名（探測順序）。CLI 指定時以 CLI 為準。
_TITLE_KEYS = ("title", "name", "課程名稱", "course_name", "courseName", "科目名稱")
_OUTLINE_KEYS = ("outline", "description", "desc", "課程大綱", "課程簡介", "課程描述",
                 "syllabus", "summary", "intro")
_SCHOOL_KEYS = ("school", "schoolKey", "開課學校", "學校", "university", "org")
_DEPT_KEYS = ("dept", "department", "開課系所", "系所", "開課單位", "unit")
_URL_KEYS = ("url", "link", "課程網址", "網址", "courseUrl", "course_url")


def _pick(row: dict, override: str, candidates: tuple[str, ...]) -> str:
    """取欄位值：CLI 指定優先；否則依候選名探測；都沒有回空字串。"""
    if override:
        return str(row.get(override, "") or "")
    for k in candidates:
        if row.get(k):
            return str(row[k])
    return ""


def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6]


# ---------------------------------------------------------------------------
# 字面重疊預篩：只把「標題/大綱裡出現任何詞彙表表面形」的課送進 LLM，省抽取成本
# ---------------------------------------------------------------------------

def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def _vocab_surface_map() -> dict[str, str]:
    """表面形 → 標準名 name_zh。供字面抽取用。

    排除長度 ≤2 的 ASCII 別名（AI、ML、TS、C# 等）：它們會把課名裡任何帶
    「AI」字樣的課硬塞成機器學習（AI 繪本、AI 政治哲學、MLCC 製程都中招）。
    中文 2 字表面形（統計、溝通、策略…）保留——命中率高、誤判少。
    ASCII ≥3（Python、SQL、C++、ERP…）保留。"""
    m: dict[str, str] = {}
    for s in load_vocabulary(VOCAB_PATH):
        for name in (s.name_zh, s.name_en, *s.aliases):
            if not name or len(name) < 2:
                continue
            if _is_ascii(name) and len(name) <= 2:      # AI / ML / TS / C#：太貪婪，丟
                continue
            m[name] = s.name_zh
    return m


def _surfaces_sorted(surf_map: dict[str, str]) -> list[str]:
    return sorted(surf_map, key=len, reverse=True)


def _has_overlap(text: str, surfaces: list[str]) -> bool:
    return any(sf in text for sf in surfaces)


def _literal_skills(text: str, surf_map: dict[str, str],
                    surfaces: list[str]) -> list[str]:
    """字面抽取：text 命中哪些表面形，就回它們的標準名（去重、保順序）。"""
    out: list[str] = []
    for sf in surfaces:
        if sf in text and surf_map[sf] not in out:
            out.append(surf_map[sf])
    return out


# ---------------------------------------------------------------------------
# extract：課程 → rawSkills 中間檔
# ---------------------------------------------------------------------------

def _load_courses(path: Path) -> list[dict]:
    rows = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"  ! 第 {ln} 行非合法 JSON，略過", flush=True)
    return rows


def _make_llm():
    """有 .env 金鑰 → 真 LLM；沒有 → None（呼叫端自行降級）。"""
    try:
        from app.providers.llm import OpenAICompatibleLLM
        return OpenAICompatibleLLM()
    except Exception:
        return None


def cmd_extract(args) -> None:
    from app.prompts.resource_skills import EXTRACT_SYSTEM_PROMPT, build_extract_prompt

    courses = _load_courses(Path(args.courses))
    print(f"讀入 {len(courses)} 筆課程", flush=True)
    if not courses:
        print("無課程可處理，結束", flush=True)
        return
    if args.limit:
        courses = courses[: args.limit]

    surf_map = _vocab_surface_map()
    surfaces = _surfaces_sorted(surf_map)
    llm = None if (args.no_llm or args.literal) else _make_llm()
    if not args.literal and not args.no_llm and llm is None:
        print("  ! 偵測不到 LLM 金鑰，自動切 --no-llm（只輸出字面候選，rawSkills 留空）；"
              "要在無金鑰下也抽技能，改用 --literal", flush=True)
    if args.literal:
        print("  模式：--literal（字面抽取，掃課名"
              + ("＋大綱" if args.scan_outline else "") + "，免金鑰）", flush=True)

    out_rows, kept, skipped, probe_warned = [], 0, 0, False
    seen_ids: set[str] = set()                 # 去重：同課名＋系所只收一次
    for row in courses:
        title = _pick(row, args.title_field, _TITLE_KEYS).strip()
        outline = _pick(row, args.outline_field, _OUTLINE_KEYS).strip()
        if not title:
            if not probe_warned:
                print(f"  ! 有筆資料找不到課名，實際鍵為：{list(row.keys())}；"
                      f"請用 --title-field 指定", flush=True)
                probe_warned = True
            skipped += 1
            continue

        school = _pick(row, args.school_field, _SCHOOL_KEYS).strip()
        # 篩校用 --school-match（比對課程資料裡的校名，如「中山」）；
        # --school 是 providerKey 代碼（如 nsysu），只管 id 與 providerKey，不拿來比中文校名。
        if args.school_match and school and args.school_match not in school:
            skipped += 1
            continue

        scan_text = title if (args.literal and not args.scan_outline) \
            else f"{title} {outline}"
        if not _has_overlap(scan_text, surfaces):
            skipped += 1
            continue                           # 字面毫無重疊 → 多半非技能課，不收／不餵 LLM

        dept = _pick(row, args.dept_field, _DEPT_KEYS).strip()
        rid = f"crs_{args.school or 'x'}_{_short_id(title + dept)}"
        if rid in seen_ids:                    # 同課名＋系所（跨年度／班次）只收一次
            skipped += 1
            continue
        seen_ids.add(rid)

        raw_skills: list[str] = []
        if args.literal:
            raw_skills = _literal_skills(scan_text, surf_map, surfaces)
            if not raw_skills:                 # 僅因 ASCII≤2 命中被排除後歸零 → 跳過
                seen_ids.discard(rid)
                skipped += 1
                continue
        elif llm is not None:
            try:
                raw = llm.complete(EXTRACT_SYSTEM_PROMPT,
                                   build_extract_prompt(title, outline), force_json=True)
                raw_skills = [str(x).strip() for x in json.loads(raw).get("skills", [])
                              if str(x).strip()]
            except Exception as e:
                print(f"  ! 抽取失敗（{title}）：{e}", flush=True)

        provider = f"{args.provider} · {dept}" if (args.provider and dept) \
            else (args.provider or school or "")
        out_rows.append({
            "resourceId": rid,
            "type": "course", "title": title, "provider": provider,
            "providerKey": args.school or (school.lower() if school else ""),
            "url": _pick(row, args.url_field, _URL_KEYS).strip(), "deadline": "",
            "rawSkills": raw_skills,
            "description": outline[:300],
            "sourceId": str(row.get("sourceId") or row.get("id") or _short_id(title)),
        })
        kept += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"保留 {kept} 筆、略過 {skipped} 筆 → {out}", flush=True)
    if not args.literal and llm is None:
        print("（本次 rawSkills 皆空；取得金鑰後重跑 extract，或改用 --literal）", flush=True)


# ---------------------------------------------------------------------------
# build：rawSkills + 競賽 CSV → resources_v1.json + 殘留報告
# ---------------------------------------------------------------------------

def _make_normalizer(real: bool) -> VocabNormalizer:
    if not real:
        return VocabNormalizer()               # alias-only：抽取用詞已近標準名時足夠
    from app.providers.embeddings import BgeM3Embedding
    return VocabNormalizer(embedding=BgeM3Embedding())


def _normalize_skills(raw_skills: list[str], norm: VocabNormalizer) -> list[str]:
    out: list[str] = []
    for rs in raw_skills:
        hit = norm.normalize(rs)
        if hit and hit.name_zh not in out:
            out.append(hit.name_zh)
    return out


def _load_competitions(path: Path, norm: VocabNormalizer,
                       dropped: list[dict]) -> list[dict]:
    """人工競賽 CSV → 競賽資源。技能欄逗號分隔，逐一正規化；對不上的丟 dropped 記錄。"""
    vocab = {s.name_zh for s in load_vocabulary(VOCAB_PATH)}
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("名稱") or "").strip()
            if not name:
                continue
            raw_skills = [s.strip() for s in (row.get("技能") or "").replace("，", ",").split(",")
                          if s.strip()]
            skills = []
            for rs in raw_skills:
                if rs in vocab:
                    if rs not in skills:
                        skills.append(rs)
                else:
                    hit = norm.normalize(rs)
                    if hit and hit.name_zh not in skills:
                        skills.append(hit.name_zh)
                    else:
                        dropped.append({"競賽": name, "技能": rs})
            code = (row.get("編號") or "").strip()
            rows.append({
                "resourceId": f"cmp_open_{code or _short_id(name)}",
                "type": "competition", "title": name,
                "provider": (row.get("主辦單位") or "").strip(), "providerKey": "open",
                "url": (row.get("網址") or "").strip(),
                "deadline": (row.get("報名截止日") or "").strip(),
                "skills": skills,
                "description": (row.get("說明") or "").strip()[:300],
                "sourceId": f"manual_csv_{code or _short_id(name)}",
            })
    return rows


def cmd_build(args) -> None:
    norm = _make_normalizer(args.real)
    raw_rows = _load_courses(Path(args.raw)) if Path(args.raw).exists() else []
    print(f"讀入中間檔 {len(raw_rows)} 筆課程", flush=True)

    resources, no_skill = [], []
    for r in raw_rows:
        skills = _normalize_skills(r.get("rawSkills", []), norm)
        if not skills:
            no_skill.append(r.get("title", r.get("resourceId", "")))
            continue                           # 一個技能都對不上 → 不入目錄（零證據不出貨）
        resources.append({
            "resourceId": r["resourceId"], "type": "course", "title": r["title"],
            "provider": r.get("provider", ""), "providerKey": r.get("providerKey", ""),
            "skills": skills, "description": r.get("description", ""),
            "url": r.get("url", ""), "deadline": "", "sourceId": r.get("sourceId", ""),
        })

    # 競賽已改走獨立管線（tools/tag_competitions.py → competitions_v1.jsonl → Mongo）。
    # build 只負責課程，不再把競賽併進 resources_v1.json，避免課程檔混入競賽、與競賽來源重複。
    dropped: list[dict] = []

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(resources, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫出目錄 {len(resources)} 筆 → {out}", flush=True)

    _write_residuals(Path(args.residuals), norm, no_skill, dropped, len(resources))


def _write_residuals(path: Path, norm: VocabNormalizer, no_skill: list[str],
                     dropped: list[dict], total: int) -> None:
    res = norm.residuals()
    lines = ["# 資源技能殘留報告（給成員 B 覆核）", "",
             "正規化對不上詞彙表的字串在此。覆核後若屬同義，補進對應詞條的 aliases"
             "（改 `tools/build_vocab.py` 常數重跑），再重跑 `build_resources.py build`。", "",
             f"- 產出目錄：{total} 筆", f"- 零技能遭剔除的課程：{len(no_skill)} 筆",
             f"- 競賽被丟棄的技能：{len(dropped)} 筆",
             f"- 正規化殘留字串：{len(res)} 筆", ""]
    if no_skill:
        lines += ["## 一個技能都對不上、未入目錄的課程", ""]
        lines += [f"- {t}" for t in no_skill] + [""]
    if dropped:
        lines += ["## 競賽清單裡對不上詞彙表的技能", "", "| 競賽 | 技能 |", "|---|---|"]
        lines += [f"| {d['競賽']} | {d['技能']} |" for d in dropped] + [""]
    if res:
        lines += ["## 課程抽取後正規化殘留（raw → 最近表面形 / 相似度）", "",
                  "| 原始字串 | 最近詞條表面形 | 相似度 |", "|---|---|---|"]
        for c in sorted(res, key=lambda c: -(c.get("sim") or 0)):
            lines.append(f"| {c.get('raw','')} | {c.get('best_surface','（無模型）')} "
                         f"| {c.get('sim',0)} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"殘留報告 → {path}", flush=True)


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="資源目錄生成器（課程＋競賽 → reinforce 目錄）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="課程 → rawSkills 中間檔（LLM 抽取）")
    pe.add_argument("--courses", required=True)
    pe.add_argument("--school", default="", help="本校代碼（providerKey），如 nsysu；用於 id 前綴與 providerKey")
    pe.add_argument("--school-match", default="",
                    help="篩校用：比對課程資料校名欄的子字串，如「中山」；空＝不篩校")
    pe.add_argument("--provider", default="", help="機構顯示名，如 國立中山大學")
    pe.add_argument("--out", default=str(REPO / "data" / "resources_raw_skills.jsonl"))
    pe.add_argument("--title-field", default="")
    pe.add_argument("--outline-field", default="")
    pe.add_argument("--school-field", default="")
    pe.add_argument("--dept-field", default="")
    pe.add_argument("--url-field", default="")
    pe.add_argument("--no-llm", action="store_true", help="不呼叫 LLM，只做字面候選（rawSkills 留空）")
    pe.add_argument("--literal", action="store_true",
                    help="免金鑰字面抽取：掃課名命中詞彙表表面形（排除 AI/ML 等 ASCII≤2 別名）")
    pe.add_argument("--scan-outline", action="store_true",
                    help="配 --literal：連課程大綱一起掃（recall 高但雜訊多，預設只掃課名）")
    pe.add_argument("--limit", type=int, default=0)
    pe.set_defaults(func=cmd_extract)

    pb = sub.add_parser("build", help="rawSkills + 競賽 CSV → resources_v1.json")
    pb.add_argument("--raw", default=str(REPO / "data" / "resources_raw_skills.jsonl"))
    pb.add_argument("--competitions", default=str(REPO / "data" / "competitions_manual.csv"))
    pb.add_argument("--out", default=str(REPO / "fixtures" / "resources" / "resources_v1.json"))
    pb.add_argument("--residuals",
                    default=str(REPO / "docs" / "resources_residuals_report.md"))
    pb.add_argument("--real", action="store_true", help="用真 bge-m3 做第二段最近鄰")
    pb.set_defaults(func=cmd_build)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
