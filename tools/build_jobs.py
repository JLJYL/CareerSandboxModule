"""B2 職缺型錄生成器:從 jobs_all 依桶制多樣性+詞彙表命中率選拔,輸出顯示就緒的 jobs_v1。
用法: python tools/build_jobs.py --jobs path/to/jobs_all.jsonl
每個欄位的出處與加工見 to_fixture();deadline 為全表唯一無源頭欄位(顯示值,三方確認中)。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pipeline.vocab import lookup  # noqa: E402

BUCKETS = [("數據資訊", r"資料|數據|分析|軟體|資訊|工程師|網頁|UI|UX", 3),
           ("行政", r"行政", 2), ("門市銷售", r"門市|店員|專櫃|銷售", 2),
           ("人資", r"人力資源|人資", 1), ("會計財務", r"會計|出納|記帳|財務", 1),
           ("業務", r"業務", 1), ("企劃行銷", r"企劃|行銷|社群", 2),
           ("客服", r"客服", 1), ("學生職缺", r"實習|工讀", 1)]


# ── 標題拆解器:文法層(通用結構)+分類層(模式類)+安全層(認不出=保留) ──
# 詞庫為開放清單,照 aliases 的維護哲學隨證據成長;丟棄採白名單制,僅限下列兩類。
_BRACKET_RE = re.compile(r"[（(《【\[「]([^）)》】\]」]{1,30})[）)》】\]」]")
_SEP_RE = re.compile(r"[_｜|│]+")
_TIME_RE = re.compile(r"\d{1,2}[:：]\d{2}(?:\s*[-~～至]\s*\d{1,2}[:：]\d{2})?")
# 分店擷取以行政區詞庫為錨:無詞典的中文分詞判不出「人員|三重」的界線,
# 認得的地名才拆,沒收錄的分店名留在本名(安全層);詞庫照證據成長。
_DISTRICTS = ("三重", "板橋", "新莊", "中和", "永和", "中山", "信義", "大安", "松山",
              "士林", "內湖", "南港", "文山", "萬華", "西屯", "北屯", "南屯", "楠梓",
              "左營", "前鎮", "苓雅", "竹北", "新店", "淡水", "汐止", "中壢", "平鎮")
_STORE_RE = re.compile(rf"({'|'.join(_DISTRICTS)})(?:店|分店|門市|館)$")
_SALARY_RE = re.compile(r"\d+\s*[-~～至]?\s*\d*\s*[KkＫ萬]|時薪|月薪|年薪|底薪|依經驗核薪|\d+元|\d{5,6}(?:\s*起)?|\d{4}\s*起")  # 裸五位數薪資:全池考場抓到的字典缺口
_CODE_RE = re.compile(r"^[A-Za-z0-9\-]{2,10}$")
_HYPE_RE = re.compile(r"優渥|高薪|急徵|搶手|無壓力|無業績|福利|獎金|分紅|月休|周休|排休|供餐|抽成")
_COND_RE = re.compile(r"經驗|歡迎|需|限|證照|年以上|輪班|夜班|早班|晚班|兼職|工讀|實習|外派|駐點")


def _classify(seg: str) -> tuple[str, str]:
    """段落 → (處置, 內容)。處置: name回填/badge保留/drop丟棄。白名單丟棄,認不出=badge。"""
    seg = seg.strip(" ，,、_-")
    if not seg:
        return "drop", ""
    if _SALARY_RE.search(seg):
        return "drop", seg          # 與 salary 欄重複
    if _CODE_RE.fullmatch(seg) and not _COND_RE.search(seg):
        return "drop", seg          # 內碼樣式(115PC 之流)
    if _HYPE_RE.search(seg) and not _COND_RE.search(seg):
        return "drop", seg          # 話術/福利宣傳
    if re.search(r"無經驗|歡迎.{0,6}無經驗", seg):
        return "badge", "無經驗可"   # 高頻條件的模式級歸一
    if len(seg) > 10:               # 裁切在詞界:ASCII 內容不得斷在單字中間
        cut = seg[:10]
        seg = cut.rsplit(" ", 1)[0] if " " in cut and cut[-1].isascii() else cut
    return "badge", seg             # 認不出 → 保留(安全層)


def split_title(raw: str) -> tuple[str, list[str]]:
    """原始標題 → (職務本名, 條件徽章)。結構通吃,內容分類,不依賴特定例子。"""
    raw = raw.strip()
    badges, name = [], raw
    for m in _BRACKET_RE.finditer(raw):          # 文法層 1:所有括號家族
        for sub in re.split(r"[，,、/／]", m.group(1)):
            act, val = _classify(sub)
            if act == "badge" and val:
                badges.append(val)
    name = _BRACKET_RE.sub(" ", name)
    parts = _SEP_RE.split(name)                   # 文法層 2:分隔符段
    name = parts[0]
    for seg in parts[1:]:
        act, val = _classify(seg)
        if act == "badge" and val:
            badges.append(val)
    tm = _TIME_RE.search(name)                    # 文法層 3:黏在本名上的時段/分店
    if tm:
        badges.append(tm.group(0).replace("：", ":"))
        name = name[:tm.start()] + name[tm.end():]
    st = _STORE_RE.search(name.strip())
    if st and st.start() > 1:
        badges.append(st.group(0))
        name = name[:st.start()]
    seen, uniq = set(), []
    for b in badges:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return re.sub(r"\s+", " ", name).strip(" ，,、-_／/"), uniq


def _clean_title(t: str) -> str:                  # 相容舊呼叫點
    return split_title(t)[0]


def _salary(lo: int, hi: int | None) -> str:
    if lo < 2000:                      # 104 對兼職刊時薪,不可硬套月薪 k 格式
        return f"時薪 {lo}-{hi}" if hi and lo < hi < 2000 else f"時薪 {lo}"
    return f"{lo//1000}-{hi//1000}k" if hi and hi > lo else f"{lo//1000}k起"


def to_fixture(r: dict) -> dict:
    jd = re.sub(r"\s+", " ", (r.get("description") or ""))[:600]
    return {"jobId": f"fit_{r['sourceId']}", "title": split_title(r["title"])[0],
            "company": r["company"].replace("股份有限公司", "").replace("有限公司", "").strip()[:12],
            "tags": ([(r.get("jobCategory") or ["職缺"])[0][:8]]
                     + split_title(r["title"])[1]
                     + ([r["workExp"][:6]] if r.get("workExp") and "不拘" not in r["workExp"] else []))[:5],
            "salary": _salary(r["salaryLow"], r.get("salaryHigh")),
            "deadline": "長期招募", "requiredSkills": r["requiredSkills"][:8],
            "jd": jd, "sourceUrl": r["url"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    args = ap.parse_args()
    recs = [json.loads(l) for l in open(args.jobs, encoding="utf-8") if l.strip()]
    pool = [r for r in recs if r.get("requiredSkills") and r.get("salaryLow")]

    def hit_rate(r):
        sk = r["requiredSkills"]
        return sum(1 for s in sk if lookup(s)) / len(sk)

    picked, used = [], set()
    for _, pat, k in BUCKETS:
        cands = [r for r in pool if r["sourceId"] not in used
                 and re.search(pat, (r.get("jobCategory") or [""])[0] + r.get("title", ""))]
        cands.sort(key=lambda r: (-hit_rate(r), abs(len(r["requiredSkills"]) - 6)))
        for r in cands[:k]:
            picked.append(r)
            used.add(r["sourceId"])
    out = ROOT / "fixtures/jobs/jobs_v1.json"
    json.dump([to_fixture(r) for r in picked], open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"型錄 {len(picked)} 筆 → {out}")


if __name__ == "__main__":
    main()
