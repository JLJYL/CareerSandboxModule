"""課程技能正規化（成員 A，批次 bge-m3 版）——抽取中間檔 → 最終課程目錄。

build_resources.py build --real 一次一字串地打 bge-m3，對 ~12000 個不重複技能字串太慢。
這支等價但快：去重 + 批次向量化，matching 邏輯完全沿用 VocabNormalizer（同樣的表面形集合、
同樣的 cosine、同樣門檻 0.88），所以結果與 build --real 一致，只是幾分鐘就跑完。

流程：rawSkills 去重 → 先吃 alias 精確命中 → 其餘批次向量化、找最近表面形 ≥0.88 → name_zh；
對不上落殘留。每門課去重後若零技能則不入目錄（零證據不出貨）。

用法：
  python tools/normalize_courses.py --raw data/resources_raw_skills_llm.jsonl \
      --out fixtures/resources/resources_v1.json \
      --residuals docs/resources_residuals_report.md [--threshold 0.88]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.pipeline.normalize import VocabNormalizer, cosine  # noqa: E402
from app.pipeline.vocab import norm_key  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(REPO / "data" / "resources_raw_skills_llm.jsonl"))
    ap.add_argument("--out", default=str(REPO / "fixtures" / "resources" / "resources_v1.json"))
    ap.add_argument("--residuals", default=str(REPO / "docs" / "resources_residuals_report.md"))
    ap.add_argument("--threshold", type=float, default=0.88)
    ap.add_argument("--chunk", type=int, default=512)
    args = ap.parse_args()

    from app.providers.embeddings import BgeM3Embedding
    norm = VocabNormalizer(embedding=BgeM3Embedding(), threshold=args.threshold)
    norm._ensure_vectors()                               # 批次向量化所有表面形（約 500 個）
    surf_vecs = norm._surface_vecs
    surf_skill = [s for _, s in norm._surfaces]

    rows = [json.loads(l) for l in Path(args.raw).read_text(encoding="utf-8").splitlines() if l.strip()]
    uniq = sorted({s for r in rows for s in r.get("rawSkills", [])})
    print(f"課程 {len(rows)} 門；不重複 raw 技能 {len(uniq)}", flush=True)

    # 第一段：alias 精確命中（免向量）
    mapping: dict[str, str | None] = {}
    misses = []
    for rs in uniq:
        hit = norm._alias.get(norm_key(rs))
        if hit:
            mapping[rs] = hit.name_zh
        else:
            misses.append(rs)
    print(f"alias 命中 {len(uniq) - len(misses)}；待向量比對 {len(misses)}", flush=True)

    # 第二段：批次向量化 misses，找最近表面形 ≥ 門檻
    residuals = []
    for i in range(0, len(misses), args.chunk):
        chunk = misses[i:i + args.chunk]
        vecs = norm._embedding.embed(chunk)
        for rs, qv in zip(chunk, vecs):
            best_i, best = max(enumerate(cosine(qv, v) for v in surf_vecs), key=lambda t: t[1])
            if best >= args.threshold:
                mapping[rs] = surf_skill[best_i].name_zh
            else:
                mapping[rs] = None
                residuals.append((rs, surf_skill[best_i].name_zh, round(best, 3)))
        print(f"  比對 {min(i + args.chunk, len(misses))}/{len(misses)}", flush=True)

    # 套用：每門課去重、零技能剔除
    out_rows, no_skill = [], 0
    for r in rows:
        skills = list(dict.fromkeys(m for s in r.get("rawSkills", [])
                                    if (m := mapping.get(s))))
        if not skills:
            no_skill += 1
            continue
        out_rows.append({
            "resourceId": r["resourceId"], "type": "course", "title": r["title"],
            "provider": r.get("provider", ""), "providerKey": r.get("providerKey", ""),
            "skills": skills, "description": r.get("description", ""),
            "url": r.get("url", ""), "deadline": "", "sourceId": r.get("sourceId", ""),
        })

    Path(args.out).write_text(json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"寫出課程目錄 {len(out_rows)} 門（零技能剔除 {no_skill}）→ {args.out}", flush=True)

    # 殘留報告（給 B：高相似度的多半是漏收 alias，補上能救回）
    residuals.sort(key=lambda t: -t[2])
    lines = ["# 課程技能正規化殘留報告（給成員 B 覆核）", "",
             "LLM 抽出、bge-m3 比對仍對不上詞彙表的字串。高相似度（接近門檻）多為漏收別名，"
             "補進對應詞條 aliases（改 `tools/build_vocab.py` 重跑）可救回。", "",
             f"- 課程 {len(rows)} 門，入目錄 {len(out_rows)}，零技能剔除 {no_skill}",
             f"- 不重複殘留字串 {len(residuals)}", "",
             "## 殘留 top 150（raw → 最近詞條 / 相似度）", "",
             "| 原始字串 | 最近詞條 | 相似度 |", "|---|---|---|"]
    lines += [f"| {rs} | {surf} | {sim} |" for rs, surf, sim in residuals[:150]]
    Path(args.residuals).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"殘留報告 → {args.residuals}", flush=True)


if __name__ == "__main__":
    main()
