"""B1 客製履歷管線(成員 B)。

流程:jdKeywords(職缺技能+使用者技能在 JD 內文的命中)→ coveredKeywords(交集)
→ 逐條經歷算 matchedKeywords 與強化/弱化 → LLM 改寫 → 逐條機械檢查
(數字不得無中生有)→ 違規條目退回原文。

分工鐵律:所有關鍵字與標記都是確定性規則;LLM 只改文字;每個數字都要有出處。
"""
import json
import re

from app.pipeline.textrules import sanitize_display_text
from app.pipeline.vocab import load_vocabulary, norm_key
from app.prompts.customize import RETRY_SUFFIX, SYSTEM_PROMPT, build_user_prompt
from app.schemas.api import CustomizedItemOut, CustomizeRequest, CustomizeResponse, ExperienceIn

_HIGHLIGHT_MIN = 2          # 命中 ≥2 個關鍵字才標強化(依 golden 範例校準)
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 評價詞防線:prompt 規則與反例示範連敗四輪後降到機械層——原文沒有就是不准寫。
_HYPE_WORDS = ("成功", "精通", "出色", "高效", "優異", "大幅", "卓越", "完美")
# Proper-noun guard (4th mechanical check, 2026-10-22): the LLM upgraded "商業競賽" to
# "全國大專商業個案大賽" in a real run. Any organisation / competition name in the rewrite
# must already exist in the source. We key on name suffixes and check the suffix plus the
# two preceding characters against the source text, so ordinary rephrasing passes while a
# newly invented name ("個案大賽", "中山大學") is caught. "系統/平台" are deliberately not
# suffixes: "中小企業貸款系統" is a legitimate rephrase of "幫助中小企業貸款的系統".
_NAME_SUFFIXES = ("大賽", "競賽", "比賽", "盃", "杯", "公司", "銀行", "大學", "學院",
                  "協會", "基金會", "集團", "部門", "實驗室")
_NAME_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{0,2}(?:" + "|".join(_NAME_SUFFIXES) + ")")


def _zh_period(t: str) -> str:
    """中文條目句尾的半形句點換全形——prompt 規則對此三案兩搖擺,降為機械正規化。
    只在句尾前一字是中日韓字元/數字/%/括號時替換,純英文句子不動。"""
    return re.sub(r"(?<=[\u4e00-\u9fff0-9%)）])\.(\s*)$", r"。\1", t.strip())


def _canon_id(normalizer, text: str) -> str | None:
    if normalizer is None:
        return None
    hit = normalizer.normalize(text)
    return hit.skill_id if hit else None


def extract_jd_keywords(job: dict, experiences: list[ExperienceIn], normalizer) -> list[str]:
    """職缺的結構化技能為主;使用者的標準技能若逐字出現在 JD 內文,一併列入。全程確定性。"""
    kws = list(job.get("requiredSkills", []))
    jd = job.get("jd", "")
    for exp in experiences:
        for tag in exp.tags:
            cid = _canon_id(normalizer, tag)
            name = normalizer.display_name(cid) if (normalizer and cid) else tag
            if name and name in jd and name not in kws:
                kws.append(name)
    return kws[:10]


def customize(job: dict, req_experiences: list[ExperienceIn], *, normalizer,
              llm=None) -> CustomizeResponse:
    jd_keywords = extract_jd_keywords(job, req_experiences, normalizer)
    kw_ids = {kw: _canon_id(normalizer, kw) for kw in jd_keywords}

    user_ids = set()
    user_raw = set()
    for exp in req_experiences:
        for tag in exp.tags:
            user_raw.add(tag)
            cid = _canon_id(normalizer, tag)
            if cid:
                user_ids.add(cid)
    covered = [kw for kw in jd_keywords
               if kw in user_raw or (kw_ids[kw] and kw_ids[kw] in user_ids)]

    items = []
    for exp in req_experiences:
        exp_ids = {c for c in (_canon_id(normalizer, t) for t in exp.tags) if c}
        blob = f"{exp.title} {exp.description} {' '.join(exp.tags)}"
        matched = [kw for kw in jd_keywords
                   if kw in blob or (kw_ids[kw] and kw_ids[kw] in exp_ids)]
        items.append({"title": exp.title, "description": exp.description,
                      "tags": exp.tags, "timeRange": exp.timeRange,
                      "matched": matched, "highlighted": False})
    # 強化判定:絕對門檻(≥2)為主;全員不足門檻時啟動相對救援——
    # 命中數最高且至少 1 的條目仍標強化(對此職缺最相關的牌不該被壓縮;全 0 則維持全弱化)
    max_hit = max((len(it["matched"]) for it in items), default=0)
    for it in items:
        n = len(it["matched"])
        it["highlighted"] = n >= _HIGHLIGHT_MIN or (0 < n == max_hit)

    texts = [it["description"] or it["title"] for it in items]   # 預設:原文出貨
    if llm is not None:
        texts = _llm_rewrite(llm, jd_keywords, items, texts)

    out = []
    for exp, t, it in zip(req_experiences, texts, items):
        text = sanitize_display_text(_zh_period(t))
        in_text, in_tags = split_matched(it["matched"], text, kw_ids, normalizer)
        out.append(CustomizedItemOut(id=exp.id, text=text, matchedKeywords=in_text,
                                     matchedTags=in_tags, highlighted=it["highlighted"]))
    return CustomizeResponse(jdKeywords=jd_keywords, coveredKeywords=covered, items=out)


def split_matched(matched: list[str], text: str, kw_ids: dict, normalizer) -> tuple[list[str], list[str]]:
    """The strong/weak decision counts hits in title + description + tags. For display,
    only keywords that actually appear in the final text go to matchedKeywords (so the
    App never highlights "Excel" on a sentence without it); hits that came from tags
    alone go to matchedTags. A keyword counts as "in text" when the text contains the
    keyword, its canonical display name, or any alias of the same skill id."""
    in_text, in_tags = [], []
    text_key = norm_key(text)
    for kw in matched:
        forms = {kw}
        cid = kw_ids.get(kw)
        if cid and normalizer is not None:
            skill = next((sk for sk in load_vocabulary() if sk.skill_id == cid), None)
            if skill:
                forms |= {skill.name_zh, skill.name_en, *skill.aliases}
        hit = any(norm_key(f) and norm_key(f) in text_key for f in forms)
        (in_text if hit else in_tags).append(kw)
    return in_text, in_tags


def _violations(cands: list[str], items: list[dict]) -> list[str]:
    """逐條機械檢查:條數對齊、非空、數字必須在該條原文出現過。回傳病歷。"""
    if len(cands) != len(items):
        return [f"items 數量 {len(cands)} 與輸入 {len(items)} 不符"]
    out = []
    for i, (t, it) in enumerate(zip(cands, items), 1):
        if not (t or "").strip():
            out.append(f"第 {i} 條為空")
            continue
        src = f"{it['title']} {it['description']} {' '.join(it['tags'])} {it['timeRange']}"
        ghost = [n for n in _NUM_RE.findall(t) if n not in _NUM_RE.findall(src)]
        if ghost:
            out.append(f"第 {i} 條出現原文沒有的數字 {ghost}")
        hype = [w for w in _HYPE_WORDS if w in t and w not in src]
        if hype:
            out.append(f"第 {i} 條出現原文沒有的評價詞 {hype}")
        names = invented_names(t, src)
        if names:
            out.append(f"第 {i} 條出現原文沒有的機構或賽事名稱 {names}")
    return out


def invented_names(candidate: str, source: str) -> list[str]:
    """Names (suffix + up to two preceding chars) present in the candidate but absent
    from the source. Comparison is on norm_key so width/case differences do not count."""
    src_key = norm_key(source)
    out = []
    for m in _NAME_RE.finditer(candidate):
        frag = norm_key(m.group(0))
        if frag and frag not in src_key and m.group(0) not in out:
            out.append(m.group(0))
    return out


def _llm_rewrite(llm, jd_keywords, items, fallback: list[str]) -> list[str]:
    prompt = build_user_prompt(jd_keywords, items)
    for attempt, extra in ((1, ""), (2, None)):
        try:
            raw = llm.complete(SYSTEM_PROMPT, prompt + (extra or ""), force_json=True)
            cands = [str(x.get("text", "")) for x in json.loads(raw).get("items", [])]
            probs = _violations(cands, items)
            if not probs:
                return cands
            if attempt == 1:
                extra = RETRY_SUFFIX + "\n具體問題:" + ";".join(probs)
                prompt_retry = prompt + extra
                raw2 = llm.complete(SYSTEM_PROMPT, prompt_retry, force_json=True)
                cands2 = [str(x.get("text", "")) for x in json.loads(raw2).get("items", [])]
                probs2 = _violations(cands2, items)
                if not probs2:
                    return cands2
                if len(cands2) == len(items):        # 條數對、個別違規 → 只退違規條
                    bad = {int(m.group(1)) - 1 for p in probs2
                           for m in [re.search(r"第 (\d+) 條", p)] if m}
                    return [c if i not in bad else fallback[i]
                            for i, c in enumerate(cands2)]
            break
        except Exception:
            break
    return fallback                                   # LLM 罷工 → 全數原文出貨
