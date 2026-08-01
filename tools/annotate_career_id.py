"""為知識庫文章段落補標 metadata.careerId(成員 A,W2 後續)。

原則(對齊模型組回饋:確定才標、不確定留空、標錯比不標更糟):
  1. 只標「標題」明確命中某職涯 aliases 的 → 高信心(標題點名職業 = 文章主題)。
  2. 內文命中但標題沒有 → 不標(內文順帶提及不代表主題)。
  3. 命中多個職涯 → 不標(模稜兩可,留空更安全)。
  4. 發票/颱風/放假等民生新聞雜訊 → 標 metadata.offtopic=true(不刪,交由檢索端過濾)。
  5. 其餘一律留空 careerId。

職涯池來源:fixtures/careers/careers.v1.json(30 個大類,由 95 職業歸併)。
輸入/輸出同一檔(原子寫回);--dry-run 只報統計不寫入。
"""
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CAREERS = REPO / "fixtures/careers/careers.v1.json"
ARTICLES = REPO / "fixtures/kb_seed/kb_entries.articles.v1.json"

# 非職涯民生新聞雜訊關鍵字(標題含之 → offtopic)
NOISE_KW = ["發票","中獎","統一發票","颱風","放假","連假","國道","電費","油價",
            "匯率","天氣","高鐵時刻","停班停課","樂透","威力彩","母親節","父親節"]


def load_careers():
    d = json.loads(CAREERS.read_text(encoding="utf-8"))
    # [(careerId, [aliases])],alias 轉小寫比對
    return [(c["careerId"], [a.lower() for a in c["aliases"]]) for c in d["careers"]]


def match_title(title: str, careers) -> list[str]:
    """回傳標題命中的 careerId 清單(可能 0/1/多個)。"""
    t = title.lower()
    hit = []
    for cid, aliases in careers:
        if any(a in t for a in aliases):
            hit.append(cid)
    return hit


def main():
    ap = argparse.ArgumentParser(description="文章補標 careerId")
    ap.add_argument("--dry-run", action="store_true", help="只報統計,不寫入")
    args = ap.parse_args()

    careers = load_careers()
    arts = json.loads(ARTICLES.read_text(encoding="utf-8"))

    stat = Counter()
    per_career = Counter()
    for e in arts:
        title = e.get("title", "")
        meta = e.setdefault("metadata", {})

        # 1) 雜訊優先判斷
        if any(k in title for k in NOISE_KW):
            meta["offtopic"] = True
            meta.pop("careerId", None)          # 確保雜訊不帶 careerId
            stat["offtopic"] += 1
            continue

        # 2) 標題命中判斷
        hits = match_title(title, careers)
        if len(hits) == 1:                       # 唯一命中 → 高信心,標
            meta["careerId"] = hits[0]
            per_career[hits[0]] += 1
            stat["tagged"] += 1
        elif len(hits) >= 2:                     # 多重命中 → 模稜兩可,留空
            meta.pop("careerId", None)
            stat["ambiguous_left_blank"] += 1
        else:                                    # 無命中 → 留空
            meta.pop("careerId", None)
            stat["no_match_left_blank"] += 1

    total = len(arts)
    print(f"文章總數 {total}")
    print(f"  已標 careerId(標題唯一命中): {stat['tagged']}")
    print(f"  標為 offtopic 雜訊:         {stat['offtopic']}")
    print(f"  多重命中留空:               {stat['ambiguous_left_blank']}")
    print(f"  無命中留空:                 {stat['no_match_left_blank']}")
    print(f"\n已標職涯分布(前15):")
    for cid, n in per_career.most_common(15):
        print(f"    {cid:<20}{n}")

    if args.dry_run:
        print("\n[dry-run] 未寫入。確認統計合理後,拿掉 --dry-run 正式標註。")
        return

    tmp = ARTICLES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(arts, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ARTICLES)
    print(f"\n✓ 已寫回 {ARTICLES.name}")


if __name__ == "__main__":
    main()
