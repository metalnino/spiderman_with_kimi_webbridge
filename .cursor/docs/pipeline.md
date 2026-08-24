# 管道接线与岗位分层（P6）

> 背景：用户发现「采集岗需求越做越多、与下游对接不到位」。诊断后确立本口径。
> 相关：总设计师工作区《管道契约与四岗位开发指导.html》四·五节（交接机制）。

## 一、岗位分层（防止采集岗边界继续膨胀）

| 层 | 内容 | 归属 | 是否进 collector 契约/考核 |
|----|------|------|---------------------------|
| 采集岗（员工） | 六站列表抓取、清洗、去重、详情/附件、观测报告 | collector/v1.2.0 契约 | 是 |
| 平台设施 | 台账 UI、跨站折叠、阶段时间线、CRM、原发寻址、报告历史/简报 | 本工作区平台层（P4/P5） | 否（增强观测与运营，不改契约 output） |
| 管道 | 交接物、版本漂移、registry | 总设计师工作区 | — |

规则：**新需求先分层再动手**——「抓取/清洗/产出」归采集岗；「展示/运营/管线」归平台层；契约改动必须走总设计师 MIGRATION。

## 二、管道接线（运行时交接）

- 采集员每轮自动落盘：
  - `handoffs/collector/latest.json`（下游读取）+ `handoffs/collector/<runId>.json`（归档）
  - 字段：`{runId, implements, generatedAt, items}`；items 与契约 output 同构。
- 解析员（parser_employee）入口 `scripts/parser_from_handoff.py`：
  - 读上游 latest.json → 只送 `tenderFile` 非空条目（跳过计数 skipped_no_tenderfile）
  - 逐条解析 → `handoffs/parser/latest.json` + 归档 + `reports/parser-report.json`
- 契约侧：parser v1.1.0（tenderFile required→optional，MIGRATION 2026-08-23 登记）；registry：parser=current/v1.1.0/解析工作区。

## 三、验证方式

```
# 采集员出勤（真实采集 + 自动交接物）
python scripts/collector_run.py data/trial/e2e_input_jiangsu.json --max-pages 1

# 解析员接单（读交接物，真机 LLM 解析）
cd ../parser_employee && python scripts/parser_from_handoff.py

# 端到端证据
handoffs/collector/latest.json → parser_employee/handoffs/parser/latest.json
```
