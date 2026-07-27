"""本機建 KB 向量索引＋檢索煙霧測試（成員 A，W2）。

--fake 用假向量快速驗流程；--real 用 bge-m3（先 pip install -r requirements-ml.txt，
首次執行自動下載約 2.3GB 模型，CPU 可跑、586 條約數分鐘）。

W2 驗收「對真 JD 檢索 top-5 人工看合理」就用這支：
  python tools/build_kb_index.py --real --rebuild
  python tools/build_kb_index.py --real --query "轉職 資料分析 需要準備什麼"

注意：索引檔預設存 data/kb_index.json，請把 `data/` 加進 .gitignore。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.providers.embeddings import FakeEmbedding  # noqa: E402
from app.retrieval.vector_retriever import VectorRetriever  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="用 bge-m3（預設 FakeEmbedding）")
    ap.add_argument("--persist", type=Path, default=REPO / "data" / "kb_index.json")
    ap.add_argument("--rebuild", action="store_true", help="忽略快取重算向量")
    ap.add_argument("--query", default="資料分析師需要什麼技能")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    if args.real:
        print("[1/3] 載入 bge-m3……首次會先下載約 2.3GB(HuggingFace 進度條會出現在下方,"
              "中斷可續傳);下載完載入模型還要一兩分鐘,別急", flush=True)
        t0 = time.time()
        from app.providers.embeddings import BgeM3Embedding
        embedding = BgeM3Embedding()
        print(f"      模型就緒({time.time() - t0:.0f}s)", flush=True)
        print("[2/3] 建索引:若無快取要對 586 條算向量,CPU 約 10–40 分鐘,"
              "逐批進度如下——", flush=True)
    else:
        embedding = FakeEmbedding()

    t0 = time.time()
    r = VectorRetriever(embedding, persist_path=args.persist, rebuild=args.rebuild)
    print(f"索引就緒：{r.count()} 條（{'bge-m3' if args.real else 'fake'}，"
          f"{time.time() - t0:.1f}s）→ {args.persist}")

    print(f"\n[3/3] 查詢：{args.query}")
    for c in r.search(args.query, k=args.k):
        print(f"  {c.score:.3f}  [{c.entry.id}] ({c.entry.type}) {c.entry.title[:40]}")


if __name__ == "__main__":
    main()
