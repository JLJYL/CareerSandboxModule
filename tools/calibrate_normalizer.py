"""正規化門檻校準（成員 A，W3）。

吃 jobs_all.jsonl 的 requiredSkills 全集，跑過 VocabNormalizer，回答一個問題：
「門檻 0.62 該上該下？」做法：把門檻暫設為不可能達到的值，讓每一個
alias 未命中的字串都帶著它的最佳相似度落進殘留區，然後：

  1. 三段分流統計（alias 命中率／各門檻下的自動採納率／殘留率）
  2. 門檻掃描表 0.50–0.76：每個候選門檻下自動採納 vs 殘留的數量
  3. 關鍵帶樣本（sim 0.45–0.76）：raw → 建議標準名，人工掃過就知道刀該切哪
  4. 低相似高頻殘留 top 20：市場常見卻對不上詞彙表的字串＝新詞條候選

輸出 data/calibration_report.md（data/ 已 gitignore；要留檔自行複製）。

用法：
  python tools/calibrate_normalizer.py --jobs <path>/jobs_all.jsonl --real
  （--fake 只驗流程，數字無語意）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.pipeline.normalize import VocabNormalizer  # noqa: E402
from app.providers.embeddings import FakeEmbedding  # noqa: E402

SWEEP = [round(0.50 + i * 0.02, 2) for i in range(14)]  # 0.50–0.76


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True, type=Path)
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--out", type=Path, default=REPO / "data" / "calibration_report.md")
    args = ap.parse_args()

    # 收集 raw 技能字串與市場頻次（幾筆職缺要求它）
    freq: Counter = Counter()
    for line in open(args.jobs, encoding="utf-8"):
        for s in json.loads(line).get("requiredSkills") or []:
            s = (s or "").strip()
            if s:
                freq[s] += 1
    raws = sorted(freq)
    print(f"共 {len(raws)} 個不重複技能字串（{sum(freq.values())} 次要求）", flush=True)

    if args.real:
        from app.providers.embeddings import BgeM3Embedding
        embedding = BgeM3Embedding()
    else:
        embedding = FakeEmbedding()

    # 門檻設 9.9：所有 alias 未命中者一律進殘留區、帶最佳 sim ——校準的原始資料
    n = VocabNormalizer(embedding=embedding, threshold=9.9)
    t0 = time.time()
    stage1_hits = 0
    for i, raw in enumerate(raws, 1):
        if n.normalize(raw) is not None:
            stage1_hits += 1
        if i % 200 == 0:
            print(f"  進度 {i}/{len(raws)}（{time.time() - t0:.0f}s）", flush=True)
    cands = n.residuals()  # 每筆: raw / best_id / best_surface / sim

    # 報告
    lines = ["# 正規化門檻校準報告", "",
             f"- 資料源：`{args.jobs.name}`；不重複字串 {len(raws)}，"
             f"總要求次數 {sum(freq.values())}",
             f"- 模式：{'bge-m3（真向量）' if args.real else 'Fake（僅驗流程，數字無語意）'}",
             f"- 第一段 alias 精確命中：{stage1_hits}/{len(raws)}"
             f"（{stage1_hits / len(raws):.0%}）", "",
             "## 門檻掃描（第二段候選的分流）", "",
             "| 門檻 | 自動採納 | 進殘留 | 採納率 |", "|---|---|---|---|"]
    for th in SWEEP:
        acc = sum(1 for c in cands if c["sim"] >= th)
        lines.append(f"| {th:.2f} | {acc} | {len(cands) - acc} | "
                     f"{acc / max(1, len(cands)):.0%} |")

    lines += ["", "## 關鍵帶樣本（sim 0.45–0.76，由高到低）",
              "", "人工判讀：往下讀到「開始出現錯併」的那一列，門檻就切在它上面。",
              "", "| sim | 原始字串（×職缺數） | → 建議標準名 |", "|---|---|---|"]
    band = sorted((c for c in cands if 0.45 <= c["sim"] < 0.76),
                  key=lambda c: -c["sim"])[:90]
    for c in band:
        lines.append(f"| {c['sim']:.3f} | {c['raw']}（×{freq[c['raw']]}） | "
                     f"{c['best_surface']} |")

    lines += ["", "## 高頻低相似殘留 top 20（新詞條候選）", "",
              "市場常要求、詞彙表卻接不住的字串——考慮加進 SEEDS 或 aliases。", "",
              "| 職缺數 | 原始字串 | 最佳近鄰 | sim |", "|---|---|---|---|"]
    low = sorted((c for c in cands if c["sim"] < 0.45),
                 key=lambda c: -freq[c["raw"]])[:20]
    for c in low:
        lines.append(f"| {freq[c['raw']]} | {c['raw']} | {c['best_surface']} | "
                     f"{c['sim']:.3f} |")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"報告 → {args.out}", flush=True)


if __name__ == "__main__":
    main()
