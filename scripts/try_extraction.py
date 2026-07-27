"""成員 B 的 prompt 迭代迴圈。用法:
  python scripts/try_extraction.py fixtures/samples/resume_01.txt
  python scripts/try_extraction.py            # 用內建示範敘述
每次改完 app/prompts/extraction.py 就跑一次,看卡片品質;滿意再跑 pytest 保合約。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.extraction import ExtractionError, LlmExtractor  # noqa: E402
from app.pipeline.textrules import ai_flavor_hits          # noqa: E402
from app.providers.llm import LLMUnavailable, OpenAICompatibleLLM  # noqa: E402

DEMO = "我大二在系學會當行銷組長,把社團 IG 從零做到一千二追蹤。暑假在電商實習,每週用 SQL 跟 Excel 拉數據做週報給業務。"


def main() -> None:
    if len(sys.argv) > 1:
        narratives = [Path(sys.argv[1]).read_text(encoding="utf-8")]
        src = sys.argv[1]
    else:
        narratives, src = [DEMO], "(內建示範敘述)"

    try:
        extractor = LlmExtractor(OpenAICompatibleLLM())
    except LLMUnavailable as e:
        sys.exit(f"[X] {e}\n    先把 .env.example 複製成 .env 並填入金鑰。")

    print(f"來源: {src}\n{'=' * 60}")
    try:
        drafts = extractor.extract(narratives)
    except ExtractionError as e:
        sys.exit(
            "[品管未過] 寫手兩次交稿都被防捏造防線退回,本輪不產卡。\n"
            f"  防線的退稿理由:{e}\n"
            "  最常見原因:source_quote 沒有逐字照抄(拼接多行、改寫數字、增刪標點)。\n"
            "  處置:回 app/prompts/extraction.py 補強引句規則後重跑。"
        )
    for i, d in enumerate(drafts, 1):
        print(f"\n[卡片 {i}] {d.title}  ({d.category} | {d.time_range} | 信心 {d.confidence})")
        print(f"  描述: {d.description}")
        print(f"  技能: {', '.join(d.raw_skills)}")
        print(f"  證據: 「{d.source_quote}」")
        flavor = ai_flavor_hits(d.title + d.description)
        if flavor:
            print(f"  [!] AI 味警報,調 prompt: {flavor}")

    print(f"\n{'=' * 60}\n人工檢查清單(每輪都過一遍):")
    for q in ["無捏造?每個數字/頭銜都出自原話", "證據句讀起來確實支持這張卡",
              "category 判得對", "描述像真人寫的、無驚嘆號", "該拆的經歷有拆開"]:
        print(f"  [ ] {q}")


if __name__ == "__main__":
    main()