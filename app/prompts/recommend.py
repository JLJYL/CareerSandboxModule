"""C1 職涯推薦的第二封信(成員 B 的迭代面)。

設計立場:LLM 在這裡是「懂人話的排序官」,不是卡片作者——
CareerRec 的每個欄位(分數、差集、薪資、缺量)都由型錄與 Scorer 供給,
LLM 只做三件事:讀懂使用者的話、在給定候選中排序、必要時寫一句學術備註。
它掛了,管線退回純分數排序照樣出貨——C1 沒有 LLM 也能活。
"""

SYSTEM_PROMPT = """你是 CareerSandbox 的職涯排序官。使用者用一段話描述興趣或困惑,\
系統已依知識庫檢索出若干「候選職涯」,每個候選附有適配分數、缺少技能與知識庫摘錄。

【輸出格式】只輸出一個 JSON 物件,不要任何前後文或 markdown 圍欄:
{"order": ["careerId", ...],        // 由最適合到次適合;只能用候選清單裡的 id
 "notes": {"careerId": "..."}}      // 選填;僅對標示 isAcademic 的候選寫一句 30 字內備註

【鐵則】
1. 只能排序給定的候選,絕不發明清單外的職涯 id。
2. 不確定就少排:與使用者描述明顯無關的候選,寧可不放進 order。
3. 排序依據 = 使用者描述的意圖 × 知識庫摘錄的內容 × 適配分數;三者衝突時,\
意圖優先,但不得把低分候選排到明顯更契合的高分候選之前超過一位。
4. notes 禁用驚嘆號,口吻像真人;若引用文章摘錄,必須改寫並在句末附(來源: 該摘錄的 url),\
禁止原文照貼。
5. 摘錄沒提到的事實不准出現在 notes。"""


def build_rank_prompt(query: str, skill_names: list[str], candidates: list[dict]) -> str:
    lines = [f"使用者的描述:{query.strip()}",
             f"使用者已具備的技能:{'、'.join(skill_names) if skill_names else '(尚未建立)'}",
             "", "候選職涯:"]
    for c in candidates:
        lines.append(f"- id={c['id']} 《{c['title']}》 適配 {c['matchScore']} 分"
                     f"{' [學術]' if c.get('isAcademic') else ''}")
        if c.get("missing"):
            lines.append(f"  尚缺:{'、'.join(c['missing'][:3])}")
        for s in c.get("snippets", [])[:2]:
            lines.append(f"  摘錄:{s['text'][:80]}… (url: {s.get('url') or '無'})")
    lines.append("\n請輸出 JSON。")
    return "\n".join(lines)


RETRY_SUFFIX = "\n\n上一次輸出不合規。只輸出 {\"order\": [...], \"notes\": {...}} 的合法 JSON,order 只能含給定的 id。"
