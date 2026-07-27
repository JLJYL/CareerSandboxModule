"""技能詞彙表 v1 產生器（成員 A，W1）。

從三個來源篩選 80–120 個 CanonicalSkill：
  L0 curated  精選種子（保證 MockData 9 個 tag 全數命中；合併規則透明可審）
  L1 onet     張圖譜的 35 個 O*NET 可轉移技能（自帶 name_en + onet_skill_id）
  L2 ucan     張圖譜中掛在目標職涯途徑（ITC/MKC/BAC）上的 UCAN 職能
  L3 market   科技職類 job_skill 聚合（頻率百分比）＋科技業職缺 requiredSkills 頻次

skill_id 策略（Day 1–2 議題一的提案實作）：
  能對上張圖譜（name_zh / name_en / alias 精確比對）→ 沿用權威 ID `sk:{hash}`
  對不上（市場工具技能等）→ 鑄造 `skm:{sha1(正規化名)[:10]}`（決定性，重跑不變）

輸出：
  fixtures/vocab/skills_v1.json             （嚴格符合 domain.CanonicalSkill）
  fixtures/vocab/skills_v1.provenance.json  （血緣側檔，非合約）

用法：
  python tools/build_vocab.py \
    --zhang-skills ../data/zhang/skills.jsonl \
    --zhang-occupations ../data/zhang/occupations.jsonl \
    --zhang-edges ../data/zhang/occupation_skills.jsonl \
    --career-knowledge ../data/JL/career_knowledge.jsonl \
    --jobs ../data/JL/jobs_all.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.schemas.domain import CanonicalSkill  # noqa: E402

# ---------------------------------------------------------------- 正規化

def norm(s: str) -> str:
    """比對鍵：NFKC → 斜線變體統一 → 去空白 → 小寫。"""
    s = unicodedata.normalize("NFKC", s or "")
    for ch in ("╱", "／", "\\"):
        s = s.replace(ch, "/")
    return "".join(s.split()).lower()


def mint_id(name: str) -> str:
    return "skm:" + hashlib.sha1(norm(name).encode()).hexdigest()[:10]


# ------------------------------------------------ 變體合併（透明、可審查）
# key = norm(原始字串) → 統一顯示名。過度合併比不合併更危險，只收明確同義。
MERGE_DISPLAY = {
    "github": "Git", "git": "Git",
    "ms sql": "SQL", "mssql": "SQL", "mysql": "SQL", "postgresql": "SQL",
    "sqlite": "SQL", "t-sql": "SQL",
    "photoshop": "Adobe Photoshop", "adobe photoshop": "Adobe Photoshop",
    "illustrator": "Illustrator", "adobe illustrator": "Illustrator",
    "vuejs": "Vue.js", "vue": "Vue.js", "vue.js": "Vue.js",
    "nodejs": "Node.js", "node.js": "Node.js",
    "reactjs": "React", "react": "React",
    "html5": "HTML", "html": "HTML", "css3": "CSS", "css": "CSS",
    "powerpoint": "PowerPoint", "excel": "Excel", "word": "Word",
    "outlook": "Outlook", "javascript": "JavaScript",
}
MERGE_DISPLAY = {norm(k): v for k, v in MERGE_DISPLAY.items()}

# 市場層黑名單：門市／物流／庶務類，與本 app 目標職涯（數據/產品/設計/學術）無關
BLOCK_KEYWORDS = [
    "包裝", "揀貨", "理貨", "補貨", "進貨", "退貨", "出貨", "盤點", "倉庫",
    "櫃檯", "接待", "收銀", "售票", "打字", "電話接聽", "訂位", "領檯",
    "吧檯", "飲料調製", "餐點", "清潔", "消毒", "保全", "駕駛", "傳票",
    "收發", "影印", "庶務", "跑腿", "電訪",
]

# ------------------------------------------------ L0：精選種子
# 目的：(a) MockData 9 tag 保證命中 (b) 給常見概念一個乾淨的標準名。
# match_hint：拿去撞張圖譜的額外別名（撞到就沿用 sk: id）。
SEEDS = [
    dict(name_zh="資料分析", name_en="Data Analysis",
         aliases=["數據分析", "數據分析技能", "資料分析能力", "數據分析相關知識"]),
    dict(name_zh="SQL", name_en="SQL",
         aliases=["MS SQL", "MySQL", "PostgreSQL", "SQLite", "T-SQL", "資料庫查詢"]),
    dict(name_zh="Excel", name_en="Excel",
         aliases=["Microsoft Excel", "試算表"]),
    dict(name_zh="簡報表達", name_en="Presentation",
         aliases=["簡報", "簡報製作", "口語簡報技巧", "提案簡報", "企畫及簡報能力"]),
    dict(name_zh="團隊領導", name_en="Leadership",
         aliases=["領導", "領導能力", "團隊激勵與領導技巧"]),
    dict(name_zh="策略規劃", name_en="Strategic Planning",
         aliases=["策略", "商業策略", "策略思維", "企業策略規劃概念"]),
    dict(name_zh="報表製作", name_en="Reporting",
         aliases=["報表", "報表彙整與管理", "商業報表設計", "業績與管理報表撰寫"]),
    dict(name_zh="內容創作", name_en="Content Creation",
         aliases=["內容行銷", "內容經營", "文案撰寫"]),
    dict(name_zh="全端開發", name_en="Full Stack Development",
         aliases=["全端", "Full Stack", "Fullstack"]),
    dict(name_zh="資料視覺化", name_en="Data Visualization",
         aliases=["圖表製作", "Tableau", "Power BI"]),
    dict(name_zh="專案管理", name_en="Project Management",
         aliases=["專案溝通/整合管理", "專案時間/進度控管", "專案管理能力"]),
    dict(name_zh="A/B 測試", name_en="A/B Testing",
         aliases=["AB測試", "A/B測試", "AB Test"]),
    dict(name_zh="統計分析", name_en="Statistics",
         aliases=["統計", "統計檢定", "統計學"]),
    dict(name_zh="溝通協調", name_en="Communication",
         aliases=["溝通", "跨部門溝通", "溝通協調能力"]),
    dict(name_zh="使用者訪談", name_en="User Interview",
         aliases=["用戶訪談", "使用者研究", "用戶研究"]),
    # 核心程式/資料技能：小樣本職類的百分比排名會漏掉，必收不靠運氣
    dict(name_zh="Python", name_en="Python", aliases=["python3"]),
    dict(name_zh="Java", name_en="Java", aliases=[]),
    dict(name_zh="C++", name_en="C++", aliases=["C", "C語言"]),
    dict(name_zh="Vue.js", name_en="Vue.js", aliases=["Vue", "VueJS"]),
    dict(name_zh="Node.js", name_en="Node.js", aliases=["NodeJS"]),
    dict(name_zh="React", name_en="React", aliases=["ReactJS", "React.js"]),
    dict(name_zh="機器學習", name_en="Machine Learning",
         aliases=["AI", "ML", "人工智慧", "深度學習", "LLM"]),
]

# MockData 四段經歷的 tags（去重後 9 個；驗收：至少 10/12 個 tag 實例對得上）
MOCKDATA_TAGS = ["領導", "內容創作", "數據分析", "簡報", "SQL", "報表", "Excel", "策略", "全端"]

# L2：抓 UCAN 職能的目標途徑（張的 occupation_id）
UCAN_TARGET_OCCS = {
    "occ:ITC-47",  # 網路規劃與建置管理
    "occ:ITC-48",  # 資訊支援與服務
    "occ:ITC-49",  # 數位內容與傳播
    "occ:ITC-50",  # 軟體開發及程式設計
    "occ:MKC-56",  # 行銷管理
    "occ:MKC-58",  # 行銷傳播
    "occ:BAC-16",  # 企業資訊管理
}

# L3：市場層要看的科技/數位職類（JL job_skill 聚合的 occupation 名）
MARKET_OCCS = [
    "軟體工程師", "前端工程師", "全端工程師", "AI工程師", "Internet程式設計師",
    "網頁設計師", "測試人員", "網路管理工程師", "資訊助理",
    "UI設計師", "UX設計師", "商業設計", "平面設計／美編", "美術設計",
    "產品經理", "產品企劃", "產品管理師", "產品行銷企劃",
    "行銷企劃", "數位行銷", "社群行銷", "電商行銷", "網站行銷企劃", "廣告文案／企劃",
    "營運管理師／系統整合／ERP專案師", "財務分析／財務人員", "行銷主管",
]

TECH_INDUSTRY_KEYWORDS = ["網際網路", "軟體", "系統整合", "半導體", "光電",
                          "電子", "電腦", "電信", "多媒體", "數位"]


# ---------------------------------------------------------------- 載入

def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_zhang_index(zhang_skills_path: Path):
    """norm(任一名稱) → 張圖譜 record。同鍵衝突以來源優先序 onet > ucan > icap 取捨。"""
    prio = {"onet": 0, "ucan": 1, "icap": 2}
    by_id, index = {}, {}
    for rec in load_jsonl(zhang_skills_path):
        by_id[rec["skill_id"]] = rec
        keys = {rec.get("name_zh") or ""}
        keys.update(rec.get("aliases") or [])
        if rec.get("name_en"):
            keys.add(rec["name_en"])
        p = min(prio.get(s, 9) for s in (rec.get("sources") or ["icap"]))
        for k in keys:
            nk = norm(k)
            if not nk:
                continue
            if nk not in index or p < index[nk][0]:
                index[nk] = (p, rec)
    return by_id, {k: v[1] for k, v in index.items()}


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zhang-skills", required=True, type=Path)
    ap.add_argument("--zhang-occupations", required=True, type=Path)
    ap.add_argument("--zhang-edges", required=True, type=Path)
    ap.add_argument("--career-knowledge", required=True, type=Path)
    ap.add_argument("--jobs", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=REPO / "fixtures/vocab/skills_v1.json")
    ap.add_argument("--target", type=int, default=110, help="目標條目數（80–120 之間）")
    args = ap.parse_args()

    zhang_by_id, zhang_index = build_zhang_index(args.zhang_skills)

    entries: dict[str, dict] = {}      # skill_id → entry dict
    prov: dict[str, dict] = {}         # skill_id → 血緣
    norm2id: dict[str, str] = {}       # norm(名稱/別名) → skill_id（去重用）

    def register(name_zh, name_en="", aliases=(), layer="", extra_prov=None):
        """去重後登記一個條目；能撞到張圖譜就沿用 sk: id。回傳 skill_id。"""
        # 先看是不是既有條目的別名
        for cand in (name_zh, name_en, *aliases):
            if cand and norm(cand) in norm2id:
                sid = norm2id[norm(cand)]
                e = entries[sid]
                for a in (name_zh, name_en, *aliases):
                    if a and norm(a) not in {norm(x) for x in
                                             [e["name_zh"], e["name_en"], *e["aliases"]]}:
                        e["aliases"].append(a)
                        norm2id[norm(a)] = sid
                prov[sid]["layers"] = sorted(set(prov[sid]["layers"]) | {layer})
                return sid
        # 撞張圖譜
        zrec = None
        for cand in (name_zh, name_en, *aliases):
            if cand and norm(cand) in zhang_index:
                zrec = zhang_index[norm(cand)]
                break
        sid = zrec["skill_id"] if zrec else mint_id(name_zh)
        alias_pool = [a for a in aliases if a]
        if zrec:
            for a in [zrec.get("name_zh"), zrec.get("name_en"),
                      *(zrec.get("aliases") or [])]:
                if a and norm(a) not in {norm(x) for x in [name_zh, name_en, *alias_pool] if x}:
                    alias_pool.append(a)
        entry = dict(
            skill_id=sid,
            name_zh=name_zh,
            name_en=name_en or (zrec.get("name_en") or "" if zrec else ""),
            aliases=alias_pool,
            ucan_code="",  # 張的資料無逐技能 UCAN 代碼，依 schema 註解逐步補
            onet_code=(zrec.get("onet_skill_id") or "") if zrec else "",
        )
        entries[sid] = entry
        prov[sid] = dict(layers=[layer],
                         zhang_matched=bool(zrec),
                         zhang_sources=(zrec.get("sources") if zrec else []),
                         **(extra_prov or {}))
        for a in [name_zh, name_en, *alias_pool]:
            if a:
                norm2id.setdefault(norm(a), sid)
        return sid

    # ---- L0 種子
    for s in SEEDS:
        register(s["name_zh"], s.get("name_en", ""), s.get("aliases", []), layer="L0_curated")

    # ---- L1 O*NET 35
    for rec in load_jsonl(args.zhang_skills):
        if "onet" in (rec.get("sources") or []):
            register(rec["name_zh"], rec.get("name_en") or "",
                     rec.get("aliases") or [], layer="L1_onet")

    # ---- L2 UCAN（目標途徑上的 UCAN 職能，取權重高者）
    ucan_hits: dict[str, dict] = {}
    for edge in load_jsonl(args.zhang_edges):
        if edge["occupation_id"] not in UCAN_TARGET_OCCS:
            continue
        rec = zhang_by_id.get(edge["skill_id"])
        if not rec or "ucan" not in (rec.get("sources") or []):
            continue
        nz = rec["name_zh"]
        if len(nz) > 14 or "（" in nz or "(" in nz:   # 濾掉句子型長名
            continue
        h = ucan_hits.setdefault(edge["skill_id"], dict(rec=rec, w=0.0, occs=set()))
        h["w"] = max(h["w"], edge.get("weight") or 0)
        h["occs"].add(edge["occupation_id"])
    ranked_ucan = sorted(ucan_hits.values(),
                         key=lambda h: (-len(h["occs"]), -h["w"], h["rec"]["name_zh"]))
    for h in ranked_ucan[:22]:
        register(h["rec"]["name_zh"], h["rec"].get("name_en") or "",
                 h["rec"].get("aliases") or [], layer="L2_ucan",
                 extra_prov=dict(ucan_occs=sorted(h["occs"]), ucan_weight=h["w"]))

    # ---- L3 市場層
    market_score: Counter = Counter()
    market_occ_pcts: dict[str, dict] = defaultdict(dict)
    for rec in load_jsonl(args.career_knowledge):
        if rec.get("type") != "job_skill" or rec.get("occupation") not in MARKET_OCCS:
            continue
        for skill, pct in (rec.get("stats") or {}).items():
            if pct < 20:
                continue
            market_score[skill] += pct
            market_occ_pcts[skill][rec["occupation"]] = pct
    tech_freq: Counter = Counter()
    for job in load_jsonl(args.jobs):
        ind = job.get("industry") or ""
        if not any(k in ind for k in TECH_INDUSTRY_KEYWORDS):
            continue
        for s in job.get("requiredSkills") or []:
            tech_freq[s] += 1
    for skill, f in tech_freq.items():
        if f >= 9:
            market_score[skill] += f * 2

    def blocked(name):
        return any(k in name for k in BLOCK_KEYWORDS)

    ranked_market = sorted(((s, sc) for s, sc in market_score.items() if not blocked(s)),
                           key=lambda kv: (-kv[1], kv[0]))
    for raw, sc in ranked_market:
        if len(entries) >= args.target:
            break
        display = MERGE_DISPLAY.get(norm(raw), unicodedata.normalize("NFKC", raw))
        is_latin = all(ord(c) < 0x2E80 for c in display)
        register(display,
                 name_en=display if is_latin else "",
                 aliases=([raw] if norm(raw) != norm(display) else []),
                 layer="L3_market",
                 extra_prov=dict(market_score=sc,
                                 occ_pcts=market_occ_pcts.get(raw, {}),
                                 tech_industry_freq=tech_freq.get(raw, 0)))

    # ---------------------------------------------------------------- 驗收
    assert 80 <= len(entries) <= 120, f"條目數 {len(entries)} 不在 80–120"
    covered, missing = [], []
    for tag in MOCKDATA_TAGS:
        (covered if norm(tag) in norm2id else missing).append(tag)
    assert not missing, f"MockData tag 未覆蓋：{missing}"
    for e in entries.values():
        CanonicalSkill.model_validate(e)
        for s in [e["name_zh"], e["name_en"], *e["aliases"]]:
            assert "!" not in s and "！" not in s, f"驚嘆號違規：{s}"

    # ---------------------------------------------------------------- 輸出
    out = sorted(entries.values(), key=lambda e: (e["skill_id"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    prov_path = args.out.with_suffix("").with_suffix("")  # strip .json
    prov_path = args.out.parent / (args.out.stem + ".provenance.json")
    prov_path.write_text(json.dumps(prov, ensure_ascii=False, indent=1), encoding="utf-8")

    n_sk = sum(1 for e in out if e["skill_id"].startswith("sk:"))
    layers = Counter(l for p in prov.values() for l in p["layers"])
    print(f"詞彙表 v1：{len(out)} 條 → {args.out.relative_to(REPO)}")
    print(f"  沿用張圖譜權威 ID(sk:)：{n_sk}；自鑄(skm:)：{len(out) - n_sk}")
    print(f"  層別：{dict(layers)}")
    print(f"  MockData tag 覆蓋：{len(covered)}/9（{covered}）")


if __name__ == "__main__":
    main()
