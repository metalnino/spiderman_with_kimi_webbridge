# 架构

## 原则

- 语言：Python
- 存储：MySQL `spiderman_bids`（utf8mb4）
- 爬取：**HTTP 主，WebBridge 辅**（暖会话拿 Cookie → HTTP 限速复用）
- AI：清洗钩子预留，默认关闭；不做主爬虫

## 模块

```
sources/*     每站适配器（列表/详情能力不同）
core/http     HTTP、限速、Cookie 会话
core/webbridge 暖会话、验证码人工、频控兜底
pipeline      标准化 → 去重 → 清洗钩子 → 写库
jobs          增量 / 单站 / 清洗入口
scheduler     定时模块（轻量）
web           展示：监控 / 增量 / 清洗 / 线索台
```

## 数据流

```
定时/手动 jobs
  → source adapter（HTTP ± WebBridge）
  → pipeline
  → MySQL notices + crawl_runs
  → web 台账
```

## 配置

- `config/sources.json` 源站开关
- `config/anti_bot.json` 反爬
- `config/crawl_config.json` 词与城市
- `config/product_plan.json` 机器摘要（与本文档同步）
