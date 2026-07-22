"""JSONL → kb_seed 轉檔器（成員 A，W1）。

把兩包爬蟲交接資料轉成 30–50 條 KBEntry 種子知識庫，type 嚴守合約三值：
  job_skill    ← JL career_knowledge.jsonl 的 job_skill 聚合（科技/數位職類子集）
  career_path  ← 張 occupations.jsonl 的 UCAN 途徑（intro_zh ＋ 高權重職能）
  industry     ← JL salary_stats.jsonl 薪情平台行業別（最新年度、科技相關行業）

保留 kb_entries.sample.json 的 4 條手寫種子為 kb_001–004，新條目自 kb_005 起
以決定性排序編號（同輸入重跑，編號不變）。skills[] 一律先過詞彙表 alias 對照
轉成標準名，對不上才保留原字串。

文章類（type="article"）依決議通知 §一-5 轉出至**獨立檔案** kb_entries.articles.v1.json：
每篇切成約 900 字的段落塊（過長硬切於句號），ID 用 kb_a{n} 前綴與種子庫脫鉤。
著作權鐵律：文章僅供檢索，生成引用必改寫並附 metadata.url 出處；文中原有的
驚嘆號屬來源語料，不受生成文字鐵律約束（該鐵律只管我們生成的展示文字）。

用法：
  python tools/build_kb_seed.py \
    --career-knowledge ../data/JL/career_knowledge.jsonl \
    --salary ../data/JL/salary_stats.jsonl \
    --zhang-occupations ../data/zhang/occupations.jsonl \
    --zhang-edges ../data/zhang/occupation_skills.jsonl \
    --zhang-skills ../data/zhang/skills.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.schemas.domain import KBEntry  # noqa: E402

ALLOWED_TYPES = {"job_skill", "career_path", "industry", "article"}  # article：W2 決議擴充

# ---- job_skill：要轉的科技/數位職類（依 jobCount 排序後編號）
JOB_SKILL_OCCS = [
    "軟體工程師", "前端工程師", "全端工程師", "AI工程師", "Internet程式設計師",
    "網頁設計師", "測試人員", "網路管理工程師", "資訊助理",
    "UI設計師", "UX設計師", "商業設計", "平面設計／美編",
    "產品經理", "產品企劃", "產品管理師",
    "行銷企劃", "數位行銷", "社群行銷", "電商行銷",
]

# ---- career_path：張的 UCAN 途徑選集（對齊 CareerRec 四類：數據/產品/設計/學術）
CAREER_PATH_OCCS = [
    "occ:ITC-50",  # 軟體開發及程式設計
    "occ:ITC-48",  # 資訊支援與服務
    "occ:ITC-47",  # 網路規劃與建置管理
    "occ:ITC-49",  # 數位內容與傳播
    "occ:BAC-16",  # 企業資訊管理
    "occ:MKC-59",  # 市場分析研究
    "occ:MKC-56",  # 行銷管理
    "occ:MKC-58",  # 行銷傳播
    "occ:BAC-15",  # 一般管理
    "occ:ARC-11",  # 視覺藝術（設計線）
    "occ:SCC-67",  # 工程及技術
    "occ:SCC-68",  # 數學及科學（學術線）
]
CATEGORY_INDUSTRY = {"ITC": "科技/網路", "BAC": "企業管理", "MKC": "行銷/電商",
                     "ARC": "藝術設計", "SCC": "科學技術"}

# ---- industry：薪情平台行業別選集（取最新年度）
INDUSTRY_PICKS = [
    "資訊服務業", "出版影音及資通訊業", "電腦﹑電子產品及光學製品製造業",
    "電子零組件製造業", "專業﹑科學及技術服務業", "金融及保險業",
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    for ch in ("╱", "／", "\\"):
        s = s.replace(ch, "/")
    return "".join(s.split()).lower()


def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def strip_bang(s: str) -> str:
    """生成文字風格鐵律：全域禁用驚嘆號（CONTRACTS #15）。"""
    return s.replace("！", "。").replace("!", ".")


def chunk_text(text: str, target: int = 900, hard: int = 1200) -> list[str]:
    """把長文按段落切成 ≤target 字的檢索塊；超長段落於句號硬切；過短尾塊併回前塊。"""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > hard:
            cut = p.rfind("。", 0, target)
            cut = cut + 1 if cut > int(target * 0.4) else target
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:cut])
            p = p[cut:]
        if cur and len(cur) + 1 + len(p) > target:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    if len(chunks) >= 2 and len(chunks[-1]) < 200 and len(chunks[-2]) + len(chunks[-1]) < hard:
        tail = chunks.pop()
        chunks[-1] = chunks[-1] + "\n" + tail
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--career-knowledge", required=True, type=Path)
    ap.add_argument("--salary", required=True, type=Path)
    ap.add_argument("--zhang-occupations", required=True, type=Path)
    ap.add_argument("--zhang-edges", required=True, type=Path)
    ap.add_argument("--zhang-skills", required=True, type=Path)
    ap.add_argument("--vocab", type=Path, default=REPO / "fixtures/vocab/skills_v1.json")
    ap.add_argument("--sample", type=Path,
                    default=REPO / "fixtures/kb_seed/kb_entries.sample.json")
    ap.add_argument("--out", type=Path,
                    default=REPO / "fixtures/kb_seed/kb_entries.v1.json")
    ap.add_argument("--articles-out", type=Path,
                    default=REPO / "fixtures/kb_seed/kb_entries.articles.v1.json")
    args = ap.parse_args()

    # 詞彙表 alias 對照：norm(任一名) → 標準顯示名
    alias2canon: dict[str, str] = {}
    for e in json.loads(args.vocab.read_text(encoding="utf-8")):
        for a in [e["name_zh"], e["name_en"], *e["aliases"]]:
            if a:
                alias2canon.setdefault(norm(a), e["name_zh"])

    def canon(skill: str) -> str:
        return alias2canon.get(norm(skill), skill)

    generated: list[dict] = []

    # -------------------------------------------------- job_skill
    aggs = {r["occupation"]: r for r in load_jsonl(args.career_knowledge)
            if r.get("type") == "job_skill"}
    picked = [aggs[o] for o in JOB_SKILL_OCCS if o in aggs]
    picked.sort(key=lambda r: (-r["jobCount"], r["occupation"]))
    for r in picked:
        stats = sorted(r["stats"].items(), key=lambda kv: -kv[1])[:8]
        listing = "、".join(f"{canon(s)}（{p}%）" for s, p in stats)
        content = (f"依 {r['jobCount']} 筆{r['occupation']}職缺統計，"
                   f"市場最常要求的技能為{listing}。"
                   f"百分比為該技能在此職類職缺中的出現比例，"
                   f"可作為技能差距分析與履歷適配的市場基準。")
        skills = list(dict.fromkeys(canon(s) for s, _ in stats))[:8]
        generated.append(dict(
            type="job_skill",
            title=f"{r['occupation']}的市場技能要求",
            content=content, skills=skills,
            metadata=dict(industry="科技/網路", source="104職缺聚合",
                          occupation=r["occupation"], jobCount=r["jobCount"],
                          sourceId=r.get("sourceId", "")),
        ))

    # -------------------------------------------------- career_path
    zskills = {r["skill_id"]: r for r in load_jsonl(args.zhang_skills)}
    edges: dict[str, list] = {}
    for e in load_jsonl(args.zhang_edges):
        if e["occupation_id"] in CAREER_PATH_OCCS:
            edges.setdefault(e["occupation_id"], []).append(e)
    occs = {r["occupation_id"]: r for r in load_jsonl(args.zhang_occupations)}
    for oid in CAREER_PATH_OCCS:
        r = occs.get(oid)
        if not r:
            continue
        intro = strip_bang((r.get("ucan") or {}).get("intro_zh") or "")
        tops, seen = [], set()
        for e in sorted(edges.get(oid, []), key=lambda e: -(e.get("weight") or 0)):
            z = zskills.get(e["skill_id"])
            if not z:
                continue
            nz = z["name_zh"]
            if len(nz) > 14 or "（" in nz or "(" in nz or norm(nz) in seen:
                continue
            seen.add(norm(nz))
            tops.append(nz)
            if len(tops) >= 6:
                break
        content = intro
        if tops:
            content += f"此途徑的核心職能包括{ '、'.join(canon(t) for t in tops) }等。"
        cat = r["category_code"]
        generated.append(dict(
            type="career_path",
            title=f"{r['name_zh']}職涯途徑",
            content=content,
            skills=list(dict.fromkeys(canon(t) for t in tops))[:8],
            metadata=dict(industry=CATEGORY_INDUSTRY.get(cat, cat),
                          source="ucan_icap", occupationId=oid,
                          categoryCode=cat, depth=r["depth"]),
        ))

    # -------------------------------------------------- industry
    plat = [r for r in load_jsonl(args.salary) if r.get("source") == "薪情平台行業別"]
    latest = max(r["year"] for r in plat)
    by_name = {r["occupation"]: r for r in plat if r["year"] == latest}
    for name in INDUSTRY_PICKS:
        r = by_name.get(name)
        if not r:
            continue
        a, b = r.get("avgMonthly"), r.get("avgMonthlyTotal")
        content = (f"主計總處薪情平台 {latest} 年統計，{name}在職者的"
                   f"每月經常性薪資（底薪）約 {a:,.0f} 元")
        if b:
            content += f"，含獎金與加班費的每月總薪資約 {b:,.0f} 元"
        content += ("。經常性薪資反映固定底薪，總薪資較能反映實領水準；"
                    "科技與金融業獎金占比較高，兩者差距通常較大。"
                    "此為在職者統計，與個別職缺開價屬不同口徑。")
        generated.append(dict(
            type="industry", title=f"{name}薪資概況（{latest} 年）",
            content=content, skills=[],
            metadata=dict(industry=name, source="主計總處薪情平台", year=latest),
        ))

    # -------------------------------------------------- 組裝＋驗證
    manual = json.loads(args.sample.read_text(encoding="utf-8"))  # kb_001–004 保留
    entries = list(manual)
    next_n = len(manual) + 1
    for g in generated:
        g = dict(id=f"kb_{next_n:03d}", **g)
        entries.append(g)
        next_n += 1

    assert 30 <= len(entries) <= 50, f"條目數 {len(entries)} 不在 30–50"
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "id 重複"
    for e in entries:
        KBEntry.model_validate(e)
        assert e["type"] in ALLOWED_TYPES, f"type 違規：{e['type']}"
        for s in [e["title"], e["content"], *e["skills"]]:
            assert "!" not in s and "！" not in s, f"驚嘆號違規：{e['id']}"

    args.out.write_text(json.dumps(entries, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    from collections import Counter
    dist = Counter(e["type"] for e in entries)
    print(f"kb_seed v1：{len(entries)} 條 → {args.out.relative_to(REPO)}")
    print(f"  type 分布：{dict(dist)}（含手寫種子 kb_001–004）")

    # -------------------------------------------------- article（獨立檔案）
    # 決議通知 §一-5：僅供檢索；生成引用必改寫＋附 metadata.url。
    # 排序決定性：(source, sourceId, part)，同輸入重跑 ID 不變。
    articles = sorted(
        (r for r in load_jsonl(args.career_knowledge) if r.get("type") == "article"),
        key=lambda r: (r["source"], str(r["sourceId"])),
    )
    a_entries: list[dict] = []
    for art in articles:
        assert art.get("url") and art.get("title"), f"文章缺 url/title：{art.get('sourceId')}"
        chunks = chunk_text(art.get("text") or "")
        n = len(chunks)
        tags = art.get("tags") or []
        mapped = list(dict.fromkeys(
            alias2canon[norm(t)] for t in tags if norm(t) in alias2canon))[:8]
        for i, ch in enumerate(chunks, 1):
            title = art["title"] if n == 1 else f"{art['title']}（{i}/{n}）"
            a_entries.append(dict(
                id=f"kb_a{len(a_entries) + 1:03d}",
                type="article", title=title, content=ch, skills=mapped,
                metadata=dict(source=art["source"], sourceId=str(art["sourceId"]),
                              url=art["url"], publishedAt=art.get("publishedAt") or "",
                              tags=tags, part=i, parts=n),
            ))

    a_ids = [e["id"] for e in a_entries]
    assert len(a_ids) == len(set(a_ids)) and not set(a_ids) & set(ids), "article id 衝突"
    for e in a_entries:
        KBEntry.model_validate(e)
        assert 0 < len(e["content"]) <= 1400, f"塊長異常：{e['id']}"
    args.articles_out.write_text(json.dumps(a_entries, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print(f"kb_seed articles：{len(articles)} 篇 → {len(a_entries)} 塊 "
          f"→ {args.articles_out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
