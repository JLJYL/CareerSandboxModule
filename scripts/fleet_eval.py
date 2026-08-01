"""C1 艦隊評測:150 persona 的前三命中率——W2 的量化句點、校準會的共同大尺。

報告雙數字,把兩個問題切開:
  引擎得分 = 命中數 / 可命中數     (在型錄蓋得到的範圍內,引擎排對了嗎)
  型錄天花板 = 可命中數 / 總數     (73 個目標裡,三格型錄理論上蓋得到幾個)
天花板低是覆蓋問題(A 的 careerId 標註戰場),得分低才是引擎問題(B 的排序戰場)。

用法:
  python scripts/fleet_eval.py                    # clear 組(有目標職業者),真 LLM 排序
  python scripts/fleet_eval.py --no-llm           # 純分數排序對照組
  python scripts/fleet_eval.py --limit 10         # 抽查省錢
需要:torch+模型+已建索引(先 $env:HF_HUB_OFFLINE="1");mini 全跑 73 人約 NT$5-15。
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# persona 經歷 type → 四類(與 batch_eval 同表,改動請同步)
TYPE_TO_CATEGORY = {
    "part_time": "工作", "internship": "工作",
    "campus": "社團", "volunteer": "社團",
    "project": "學業", "exchange": "學業",
    "competition": "競賽",
}

# 型錄職涯 → 目標職業關鍵詞(開放詞庫:判定 targetOccupation 是否「這格蓋得到」)
TARGET_KEYS = {
    "data_analyst": ("資料分析", "數據分析"),
    "data_engineer": ("資料工程", "數據工程"),
    "pm": ("產品經理", "產品企劃", "PM"),
}


def persona_to_request(p: dict):
    """persona → (query, experiences)。query 用 aboutMe 自述;
    skills.owned 掛上首段經歷的 tags(輪廓吃 tags,persona 的技能存在人身上不在經歷上)。"""
    from app.schemas.api import ExperienceIn
    query = (p.get("aboutMe") or "").strip() or "還在探索方向"
    exps = []
    for i, e in enumerate(p.get("experiences", []), 1):
        exps.append(ExperienceIn(
            id=f"p{i}", title=e.get("title", ""),
            category=TYPE_TO_CATEGORY.get(e.get("type", ""), "工作"),
            timeRange=e.get("period", ""), description=e.get("description", ""),
            tags=[]))
    owned = p.get("skills", {}).get("owned", [])
    if not exps:
        exps = [ExperienceIn(id="p0", title="尚無經歷", category="工作",
                             timeRange="", description="", tags=[])]
    exps[0].tags = owned
    return query, exps


def target_reachable(target: str) -> str | None:
    """這個目標職業,型錄裡哪一格理論上蓋得到?蓋不到回 None(天花板之外)。"""
    for cid, keys in TARGET_KEYS.items():
        if any(k in target for k in keys):
            return cid
    return None


def is_hit(rec_ids: list[str], target: str, top: int = 3) -> bool:
    cid = target_reachable(target)
    return cid is not None and cid in rec_ids[:top]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "fixtures/eval/persona_150.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()

    from app.pipeline.normalize import VocabNormalizer
    from app.pipeline.recommend import recommend
    from app.pipeline.scorer import WeightedScorer
    from app.providers.embeddings import BgeM3Embedding
    from app.providers.llm import LLMUnavailable, OpenAICompatibleLLM
    from app.retrieval.vector_retriever import VectorRetriever

    recs_all = [json.loads(l) for l in Path(args.data).read_text(encoding="utf-8").splitlines() if l.strip()]
    fleet = [p for p in recs_all
             if p.get("career", {}).get("clarity") == "clear"
             and p.get("career", {}).get("targetOccupation")]
    if args.limit:
        fleet = fleet[: args.limit]

    emb = BgeM3Embedding()
    norm = VocabNormalizer(embedding=emb)
    retriever = VectorRetriever(embedding=emb, persist_path=ROOT / "data/kb_index.json")
    scorer = WeightedScorer(norm, embedding=emb)
    llm = None
    if not args.no_llm:
        try:
            llm = OpenAICompatibleLLM()
        except LLMUnavailable:
            print("(LLM 未設定 → 純分數排序)")

    hits = reachable = empty = 0
    top1 = Counter()
    miss_samples = []
    for i, p in enumerate(fleet, 1):
        query, exps = persona_to_request(p)
        target = p["career"]["targetOccupation"]
        out = recommend(query, exps, normalizer=norm, retriever=retriever,
                        scorer=scorer, llm=llm)
        ids = [r.id for r in out]
        if not ids:
            empty += 1
        else:
            top1[ids[0]] += 1
        cid = target_reachable(target)
        if cid:
            reachable += 1
            if cid in ids[: args.top]:
                hits += 1
            elif len(miss_samples) < 5:
                miss_samples.append((target, cid, ids))
        if i % 10 == 0:
            print(f"  …{i}/{len(fleet)}")

    n = len(fleet)
    print("\n" + "=" * 56)
    print(f"艦隊 {n} 人(clear 且有目標) | 排序:{'LLM' if llm else '純分數'} | top-{args.top}")
    print(f"型錄天花板:{reachable}/{n}({reachable/n:.0%})——目標落在三格型錄射程內的比例")
    if reachable:
        print(f"引擎得分:{hits}/{reachable}({hits/reachable:.0%})——射程內的命中率")
    print(f"總命中率:{hits}/{n}({hits/n:.0%})   優雅空手:{empty} 人")
    print(f"top-1 分布:{dict(top1)}")
    if miss_samples:
        print("射程內失手抽樣:")
        for t, cid, ids in miss_samples:
            print(f"  目標「{t}」該中 {cid},實出 {ids}")
    print("=" * 56)
    print("判讀:天花板低 → 覆蓋問題(A 的 careerId 戰場);得分低 → 排序問題(B 的戰場)。")


if __name__ == "__main__":
    main()
