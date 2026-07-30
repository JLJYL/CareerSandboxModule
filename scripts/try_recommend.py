"""C1 開發迴圈駕駛艙:真零件跑一發推薦,把「過濾前的世界」全部攤開。
用法:
  python scripts/try_recommend.py "我喜歡整理數據,也對做產品有點興趣"
  python scripts/try_recommend.py "..." --min-score 0        # 看斷頭台下的亡魂
  python scripts/try_recommend.py "..." --no-llm             # 隔離排序官,看純分數世界
需要:torch+模型(先 $env:HF_HUB_OFFLINE="1")與已建索引;LLM 沒設定會自動走純分數。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--min-score", type=int, default=30)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--tags", default="SQL,Excel,數據分析",
                    help="模擬母版經歷的技能標籤,逗號分隔")
    args = ap.parse_args()

    from app.pipeline.normalize import VocabNormalizer
    from app.pipeline.recommend import (_dedupe_chunks, load_catalog,
                                        profile_from_experiences, recommend)
    from app.pipeline.scorer import WeightedScorer
    from app.providers.embeddings import BgeM3Embedding
    from app.providers.llm import LLMUnavailable, OpenAICompatibleLLM
    from app.retrieval.vector_retriever import VectorRetriever
    from app.schemas.api import ExperienceIn
    from app.schemas.domain import JobRequirement

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

    exps = [ExperienceIn(id="e1", title="模擬經歷", category="工作", timeRange="",
                         description="", tags=[t.strip() for t in args.tags.split(",") if t.strip()])]

    profile = profile_from_experiences("dev_user_001", exps, norm)
    print("=" * 62, "\n[輪廓]")
    for se in profile.skills:
        print(f"  {norm.display_name(se.skill_id)}({se.skill_id}) 權重 {se.weight}")
    if profile.raw_tags:
        print(f"  殘留區: {profile.raw_tags}")

    chunks = _dedupe_chunks(retriever.search(args.query, k=8))
    print("\n[檢索] 去重後", len(chunks), "塊:")
    for c in sorted(chunks, key=lambda x: -x.score)[:8]:
        m = c.entry.metadata
        print(f"  {c.score:.3f} [{c.entry.id}] ({c.entry.type}) careerId={m.get('careerId')} {c.entry.title[:24]}")

    seen = {c.entry.metadata.get("careerId") for c in chunks} - {None}
    catalog = load_catalog()
    pool = list(catalog)   # 與管線一致:全型錄上擂台,seen 僅供觀察
    snip = {}
    for c in chunks:
        cid = c.entry.metadata.get("careerId")
        if cid:
            snip.setdefault(cid, []).append(c.entry.content)

    print(f"\n[計分] 候選 {len(pool)} 個(檢索命中 {sorted(seen) or '無 → 全型錄'}),過濾線 {args.min_score} 分:")
    for c in pool:
        if not c.get("requiredSkills") and not snip.get(c["id"]):
            print(f"  ⊘ {c['title']:<10} 零證據跳過(無技能骨架、無知識摘錄)")
            continue
        fit = scorer.score(profile, JobRequirement(
            job_id=c["id"], title=c["title"],
            required_skills=c.get("requiredSkills", []),
            jd_text=" ".join(snip.get(c["id"], [])[:2])))
        mark = "  " if fit.match_score >= args.min_score else "✗ "
        print(f"  {mark}{c['title']:<10} {fit.match_score:>3} 分 | 覆蓋 {fit.covered_skills or '無'} | 缺 {fit.missing_skills[:4]}")

    recs = recommend(args.query, exps, normalizer=norm, retriever=retriever,
                     scorer=scorer, llm=llm, min_score=args.min_score)
    print(f"\n[出貨] {len(recs)} 張卡:")
    for r in recs:
        print(f"  {r.title} {r.matchScore} 分 | {r.shortSubtitle} | 缺 {r.missingSkills[:3]}")


if __name__ == "__main__":
    main()
