# 江苏省公共资源交易网（jsggzy）

## 采集路径

1. **全国 ggzy 江苏切片**（`_fetch_via_national`）：www.ggzy.gov.cn getTradList，DEAL_PROVINCE=320000。
   字段可用：publishTime（有值，主用）。
2. **省站 inteligentsearch API**（`_fetch_via_province_api`）：
   `http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew`（HTTP、跳过坏证书）。
   仅 `wd` 必需；`sort={"webdate":"0"}` 传参名与返回字段名无关。

## 省站 API 记录字段（2026-08-26 实测探明）

| 字段 | 含义 | 是否可用作 publish_date |
|------|------|------------------------|
| `infodatepx` | 详情页「信息发布时间」同值（含时分秒，6/6 命中） | ✅ 首选 |
| `infodateformat` | 同上纯日期形态 | ✅ 次选 |
| `infodate` | 入库/索引时间 | ❌ 可能比真实发布时间晚（如 2023-10-23 vs 页面 2023-10-10） |
| linkurl 中 8 位日期段 | 发布/迁移日期 | ❌ 老公告迁移日（如 URL 20200921、页面真实 2020-05-07） |
| `webdate` / `publishTime` | 历史字段名，实际不存在 | —（保留兜底） |

规则：`infodatepx → infodateformat → webdate → publishTime`，其余不用。

## 历史数据修补

2026-08-25 入库的 20 条省站记录 publish_date 为 NULL（当时解析只认 webdate/publishTime）。
修补脚本：`scripts/backfill_publish_dates.py`（详情页实证「信息发布时间」+ 标题核对，dry-run 默认）。
报告：`data/backfill_publish_report.json`。
