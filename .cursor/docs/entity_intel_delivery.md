# 交付报告 · 实体情报员（implements: entity_intel/v1.0.0）

> 岗位：把采集员累积的公告库升维成「实体情报图」 ｜ 依据：`.cursor/docs/intelligence_chain.md`
> 内核类型：rule ｜ 自主性预算：deterministic ｜ 交付日期：2026-08-26

## 1. 结论先行

新增「实体情报员」员工外壳，确定性实现**采购人实体聚合 + 中标企业（供给侧）抽取 + 历史周期粗估 + 原发渠道 + 供需关系边**：
契约 input → 契约 output（entities/winners/relations）→ 观测报告 `reports/intel-report.json`（7 项指标）→ 交接物 `handoffs/intel/latest.json`。
**全量回归 243 通过、0 失败、3 跳过**（3 跳过为既有需 SPIDER_LIVE_TESTS 的用例）。

## 2. 改了什么

| 文件 | 层 | 内容 |
|---|---|---|
| crawl/winner_extract.py | 内核（新增） | 中标企业确定性抽取（纯函数）：结果公告 → 中标/成交供应商名；括号注释/金额噪声/多候选人/流标废标/登录墙逐条诚实处理，抽不到 null |
| crawl/entity_aggregate.py | 内核（新增） | 采购人实体聚合 + 周期粗估（纯函数）：名称规范化、全国同名合并、中位间隔外推、置信度分级；提炼自 build_crm_db |
| crawl/intel_employee.py | 身份/契约/观测 | IMPLEMENTS=entity_intel/v1.0.0；四层；7 项指标；读 notices 累积库（跨轮），非单轮 handoff |
| scripts/intel_run.py | 入口 | 契约 input → output + 报告 + handoffs/intel 交接物 |
| contract/entity_intel-v1.json | 契约副本 | 契约 schema（input/output/observability） |
| sql/schema.sql + scripts/migrate_ops.py | schema | 新增 `notices.winner`（中标/成交供应商，可空） |
| scripts/jobs/build_crm_db.py | 重构 | 实体名规范化/合并/周期粗估收口到 entity_aggregate，消除 CRM 与情报员逻辑分叉 |
| tests/test_winner_extract.py | 测试 | 中标抽取 16 用例（句式/噪声/负向/边界） |
| tests/test_intel_contract.py | 测试 | 契约/聚合/周期/交接物 12 用例（mock，不碰外网/DB） |
| tests/test_all.py | 修复 | 陈旧断言：meta sources 已从「仅 ccgp+chinabidding」更新为「九站运行 + rccchina 暂缓」 |

## 3. 契约输出是否 100% 符合 schema

- `entities`：采购人实体，字段 name/entityType/city/province/noticeCount/lastNoticeAt/nextBidHint/nextBidConfidence/medianCycleDays/nextBidDate/officialChannels/originSources/serviceTags/noticeIds 全量、类型严格。
- `winners`：仅 result 阶段抽取，字段 name/buyer/projectName/projectKey/noticeId/platform/url/wonAt/extractSource；抽不到不出现（诚实 null）。
- `relations`：供需边 buyer→winner，去重。
- 周期粗估是**提示非事实**：样本 < min_history_for_estimate 时 hint/confidence/median/date 全 null；confidence 分 low/medium/high。

## 4. 观测指标是否都能上报

7 项：`entity_count / winner_count / winner_extract_rate / cycle_estimate_count / official_channel_count / notice_scanned / elapsed_ms`。`winner_extract_rate` 无结果公告时为 null（不编 0）。

## 5. 中标企业抽取口径（诚实性红线）

- 只抽 result 阶段；候选（candidate）阶段不冒充中标，如实不抽（记录为限制）。
- 数据来源：summary（详情回填）> tenderfile_text > title；登录墙/无摘要/真流标 → `status=unknown`，winner=null。
- 名称校验：实体后缀 + 噪声短语黑名单（详见/见附件/流标/废标…）+ 数字占比，防止「详见附件」「123456」当实体。
- 抽取结果回写 `notices.winner`（幂等 UPDATE），供台账/CRM 直接查询。

## 6. 验证记录

- 新增单测：`python -m unittest tests.test_winner_extract tests.test_intel_contract` → 28/28 通过。
- 全量回归：`python scripts/run_tests.py` → **243 通过 / 0 失败 / 3 跳过**（退出码 0）。
- build_crm_db 重构后导入/函数烟测通过（normalize/estimate/extract 正常）。
- 真机冒烟（真实 MySQL，2026-08-26）：`python scripts/intel_run.py` → 扫描 1007 条公告，聚合 **357 个采购人实体**，57 个有周期粗估，2 个有原发渠道，耗时 624ms。
- 中标抽取真机结果：result 公告 191 条，`extracted=0`。根因：**191 条里 188 条 summary 为空**（采集员只对可投标阶段回填详情，结果公告从未回填）；仅 3 条有 summary 的还分别是 chinabidding 登录墙、ggzy 列表摘要。抽取代码正确（单测覆盖），是**数据未回填**，非代码 bug。

## 7. 还差什么（如实清单）

1. **中标抽取缺数据源（真机已证）**：抽取代码正确，但 result 公告 188/191 无 summary（采集员仅对 intent/bidding/change 回填详情，结果公告未回填）→ 真机 winner=0。二期需对 result 公告做详情回填：ccgp HTTP 开放可先通；chinabidding/cebpub/jiangsu 登录墙、vaptcha 未过时如实 null（同既有 tenderFile 口径）。
2. **历史深度不足**：当前采集窗约 2 个月，多数实体周期粗估为空（样本 < 2）；随采集累积自愈。
3. **原发渠道半填**：`origin.py` 寻址能力已有，但实体聚合目前只读已回填的 original_url/origin_source，未在实体层触发按需寻址（二期）。
4. **candidate 阶段未抽**：中标候选人是「可能的胜者」，当前不抽，避免与中标结果混淆（可后续加 winnerCandidate 字段）。
5. **周期粗估是启发式**：中位间隔对年度续签有效，对偶发/一次性采购无预测力，confidence 已标注。
6. **决策在环**：winner 关系喂给 CRM，投标/分包由人拍板，系统永不自动决策。

## 8. 运行方式（验收用）

```powershell
# 1. 建 winner 列（幂等）
python scripts/migrate_ops.py

# 2. 跑实体情报员（无输入=全量累积库）
python scripts/intel_run.py

# 3. 查看产物
#    reports/intel-report.json
#    handoffs/intel/latest.json

# 4. 带过滤（可选）
python scripts/intel_run.py data/trial/intel_input.json
```

契约 input 示例：`{"regionFilter":["南京"],"dateRange":{"start":"2026-07-01"},"extractWinners":true}`。

## 9. 红线自查

- coreType=rule、autonomyBudget=deterministic；未读语义（只抽名字不判断）；未做投标/分包任何业务决策；抽不到一律 null 不造假；验证码/登录墙如实记录待办，绝不绕过。
- 未改采集员契约任何字段；未动内核爬取控制流；仅新增模块 + winner 列 + CRM 逻辑收口。
