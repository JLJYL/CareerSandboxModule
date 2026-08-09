# W3 校准决议通知



日期：2026-08-03  

分支：`feat/a-w3-calibration`



## 已定案



- VocabNormalizer 真向量自动合并门槛由 `0.62` 调整为 `0.88`。

- 调整依据为 bge-m3 对「财务报表制作 → 报表制作」给出 0.8701，以及「业绩管理 → 业绩与管理报表撰写」给出 0.7991；两者语意相近但职业能力不同，不应自动合并。

- 新增 ERP 系统（鼎新、正航）、Claude、Zeplin 等精选词条。

- 词汇表重建后共 110 条，MockData tag 覆盖 9/9。

- 正式黄金集回归为 15/15 格、逐技能 75/75。

- matchScore 排序符合关键验收条件，覆盖率／语意权重维持 `0.65/0.35`。



## 证据文件



- `docs/calibration_report.md`

- `docs/golden_pairs_report.md`

- `docs/W3_CALIBRATION_NOTE.md`



## 合并前待办



- B 的 category PR、共用尺提案与桶名，将在团队统一合并时共同确认。

- MongoDB Atlas URI 尚待提供；取得 URI 后执行 `tools/ingest_atlas.py --create-index`，完成 587 条资料落地。

- 上述外部协作事项不影响本次本地黄金集 15/15 回归结果。

