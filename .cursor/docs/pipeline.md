# 管道接线与岗位分层（P6）

> 背景：用户发现「采集岗需求越做越多、与下游对接不到位」。诊断后确立本口径。
> 相关：总设计师工作区《管道契约与四岗位开发指导.html》四·五节（交接机制）。

## 一、岗位分层（防止采集岗边界继续膨胀）

| 层 | 内容 | 归属 | 是否进 collector 契约/考核 |
|----|------|------|---------------------------|
| 采集岗（员工） | 六站列表抓取、清洗、去重、详情/附件、观测报告 | collector/v1.2.0 契约 | 是 |
| 实体情报岗（员工） | 采购人实体聚合、中标企业抽取、周期粗估、原发渠道、供需关系（吃 notices 累积库，非单轮 handoff） | entity_intel/v1.0.0 契约 | 是 |
| 平台设施 | 台账 UI、跨站折叠、阶段时间线、CRM、原发寻址、报告历史/简报 | 本工作区平台层（P4/P5） | 否（增强观测与运营，不改契约 output） |
| 管道 | 交接物、版本漂移、registry | 总设计师工作区 | — |

规则：**新需求先分层再动手**——「抓取/清洗/产出」归采集岗；「展示/运营/管线」归平台层；契约改动必须走总设计师 MIGRATION。

### 岗位定义（一句话分清）

- **采集员（collector）回答「发生了什么」**：把源站公告抄成结构化条目——某日某地某单位发了一条什么公告。产出是**事件流**（单轮、窄窗口）。靠「实时记录 + 过反爬」。
- **实体情报员（entity_intel）回答「是谁、和谁、多久一次」**：把累积的公告整理成**实体图**——某医院是客户、每年 7 月左右招标、上次中标的是某园林公司。产出是**实体 + 关系 + 周期规律**（跨轮、全历史）。靠「历史归纳 + 纯计算」，只读库不碰网。

关键区别：采集员要**广度 + 实时**（抓新东西，过反爬）；情报员要**深度 + 累积**（算规律，需跨多年历史）。一个碰网、一个只读库，节奏与依赖完全不同，所以不合成一个岗；两者靠交接物对接。

> 采集员自身内部还有一条纵向链（详情 → 原发寻址 → 原发转爬 → AI 字段抽取），这是「采集员这个岗位内部的完善」，不改变岗位边界——它仍然只产出「忠实的事件条目」，不越界去做实体归纳或业务决策。

## 二、管道接线（运行时交接）

- 采集员每轮自动落盘：
  - `handoffs/collector/latest.json`（下游读取）+ `handoffs/collector/<runId>.json`（归档）
  - 字段：`{runId, implements, generatedAt, items}`；items 与契约 output 同构。
- 解析员（parser_employee）入口 `scripts/parser_from_handoff.py`：
  - 读上游 latest.json → 只送 `tenderFile` 非空条目（跳过计数 skipped_no_tenderfile）
  - 逐条解析 → `handoffs/parser/latest.json` + 归档 + `reports/parser-report.json`
- 契约侧：parser v1.1.0（tenderFile required→optional，MIGRATION 2026-08-23 登记）；registry：parser=current/v1.1.0/解析工作区。
- 实体情报员入口 `scripts/intel_run.py`（implements entity_intel/v1.0.0）：
  - 读 notices 累积库（跨轮多年，**不是单轮 handoff**，这是与解析员的架构区别）→ 实体图
  - 落盘 `handoffs/intel/latest.json` + 归档 + `reports/intel-report.json`
  - 字段：`{runId, implements, generatedAt, entities, winners, relations}`；先跑 `scripts/migrate_ops.py` 建 `notices.winner` 列。

## 三、验证方式

```
# 采集员出勤（真实采集 + 自动交接物）
python scripts/collector_run.py data/trial/e2e_input_jiangsu.json --max-pages 1

# 解析员接单（读交接物，真机 LLM 解析）
cd ../parser_employee && python scripts/parser_from_handoff.py

# 端到端证据
handoffs/collector/latest.json → parser_employee/handoffs/parser/latest.json
```
