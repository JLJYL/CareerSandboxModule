"""黃金測試集回歸器（成員 A，W3）——吃 A+B 覆核定案的 golden_pairs.v1。

對 15 格逐一跑「tags → 正規化 → 差集判定」，與 expected covered/missing 逐技能
比對（二值制），輸出通過/失敗與逐格差異；另附 matchScore 矩陣供分數量級討論。
之後任何詞彙表、門檻、合併表、公式的改動，都拿這支回歸——這就是 04 文件說的
「人工覆核後入庫」的入庫形式。

判定零漂移設計：不另寫一份差集邏輯，而是對每個 required skill 單獨呼叫
WeightedScorer.score（embedding=None、單一技能），判定路徑與正式計分完全同源。
正規化器照常帶 embedding（門檻第二段是被測物之一）。

用法：
  python tools/run_golden_pairs.py --real          # 正式回歸（需本機模型）
  python tools/run_golden_pairs.py                 # Fake：只驗流程與第一段命中
輸出 data/golden_pairs_report.md；有任何格失敗時結束碼為 1（可掛腳本）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.pipeline.normalize import VocabNormalizer  # noqa: E402
from app.pipeline.scorer import WeightedScorer  # noqa: E402
from app.providers.embeddings import FakeEmbedding  # noqa: E402
from app.schemas.domain import JobRequirement, SkillEvidence, UserProfile  # noqa: E402

GOLDEN = REPO / "fixtures/golden_set/golden_pairs.v1.json"


def build_profile(resume: dict, normalizer: VocabNormalizer):
    """經歷 tags 全集 → 正規化。命中進 SkillEvidence，未命中留 raw_tags。
    回傳 (profile, 正規化明細) —— 錯了要看得見。"""
    tags = list(dict.fromkeys(
        t for exp in resume.get("experiences", []) for t in exp.get("tags", []) if t))
    evidence, raw_tags, audit = [], [], []
    for t in tags:
        hit = normalizer.normalize(t)
        if hit:
            evidence.append(SkillEvidence(skill_id=hit.skill_id, weight=1.0))
            audit.append(f"{t}→{hit.name_zh}")
        else:
            raw_tags.append(t)
            audit.append(f"{t}→（raw_tag）")
    return (UserProfile(user_id=resume["resumeId"], skills=evidence,
                        raw_tags=raw_tags), audit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    ap.add_argument("--out", type=Path, default=REPO / "data/golden_pairs_report.md")
    args = ap.parse_args()

    g = json.loads(args.golden.read_text(encoding="utf-8"))
    resumes = {r["resumeId"]: r for r in g["resumes"]}
    jds = {j["jobId"]: j for j in g["jds"]}
    cases = [c for c in g["cases"] if c.get("verified")]
    # 黃金檔自身健檢：每個 required skill 必須恰好出現在 covered ∪ missing 其一
    for c in cases:
        req = set(jds[c["jobId"]]["requiredSkills"])
        covered = set(c["expected"]["covered"])
        missing = set(c["expected"]["missing"])
        overlap = covered & missing
        assert not overlap, (
            f"{c['caseId']} covered/missing 重複：{overlap}"
        )
        exp = covered | missing
        assert req == exp, (
            f"{c['caseId']} expected 未涵蓋全部 requiredSkills：{req ^ exp}"
        )

    embedding = None
    if args.real:
        from app.providers.embeddings import BgeM3Embedding
        embedding = BgeM3Embedding()
    else:
        embedding = FakeEmbedding()
    normalizer = VocabNormalizer(embedding=embedding)
    verdict_scorer = WeightedScorer(normalizer, embedding=None)   # 純差集，零漂移
    full_scorer = WeightedScorer(normalizer, embedding=embedding)  # 分數矩陣用

    profiles = {rid: build_profile(r, normalizer) for rid, r in resumes.items()}

    mode = "bge-m3（正式回歸）" if args.real else "Fake（僅驗流程；第二段判定無語意）"
    lines = [f"# 黃金測試集回歸報告（{g['version']}）", "", f"- 模式：{mode}",
             f"- 覆核定案格數：{len(cases)}", ""]
    n_pass = n_verdict_ok = n_verdict = 0
    fails: list[str] = []
    scores: dict[tuple[str, str], int] = {}

    for c in cases:
        prof, audit = profiles[c["resumeId"]]
        jd = jds[c["jobId"]]
        exp_cov = set(c["expected"]["covered"])
        wrong: list[str] = []
        for r in jd["requiredSkills"]:
            one = verdict_scorer.score(prof, JobRequirement(
                job_id=jd["jobId"], title=jd["title"], required_skills=[r]))
            ours_covered = bool(one.covered_skills)
            n_verdict += 1
            if ours_covered == (r in exp_cov):
                n_verdict_ok += 1
            else:
                trace = normalizer.normalize(r)
                wrong.append(f"「{r}」應判 {'covered' if r in exp_cov else 'missing'}"
                             f"，我們判 {'covered' if ours_covered else 'missing'}"
                             f"（該字串正規化→"
                             f"{trace.name_zh if trace else '未命中'}）")
        full = full_scorer.score(prof, JobRequirement(
            job_id=jd["jobId"], title=jd["title"],
            required_skills=jd["requiredSkills"], jd_text=jd.get("jd", "")))
        scores[(c["resumeId"], jd["jobId"])] = full.match_score
        if wrong:
            note = c["expected"].get("notes", "")
            fails.append(f"### ✗ {c['caseId']}\n"
                         + "\n".join(f"- {w}" for w in wrong)
                         + (f"\n- 裁決依據：{note}" if note else "")
                         + f"\n- 該履歷正規化明細：{'；'.join(audit)}")
        else:
            n_pass += 1

    lines += [f"## 總結：{n_pass}/{len(cases)} 格通過；"
              f"逐技能判定 {n_verdict_ok}/{n_verdict} 正確", ""]
    jd_ids = [j["jobId"] for j in g["jds"]]
    lines += ["## matchScore 矩陣（含語意分量，供分數量級討論；黃金集不裁分數）",
              "", "| 履歷 \\ JD | " + " | ".join(jds[j]["title"] for j in jd_ids) + " |",
              "|" + "---|" * (len(jd_ids) + 1)]
    for r in g["resumes"]:
        row = [f"{r['resumeId']}（{r.get('profileNote', '')}）"]
        row += [str(scores.get((r["resumeId"], j), "—")) for j in jd_ids]
        lines.append("| " + " | ".join(row) + " |")
    if fails:
        lines += ["", "## 失敗明細", ""] + fails
    else:
        lines += ["", "全數通過。此結果連同本檔即為 W3 驗收「差集結果人工覆核通過」的證明。"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{n_pass}/{len(cases)} 格通過；逐技能 {n_verdict_ok}/{n_verdict}。"
          f"報告 → {args.out}")
    sys.exit(0 if n_pass == len(cases) else 1)


if __name__ == "__main__":
    main()
