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
web           展示：本机只读 API + 台账壳页（监控 / 增量 / 清洗 / 线索 / CRM）
```

## 台账（本机 / NAS 容器）

- 入口：`python scripts/jobs/serve_ledger.py` → `http://127.0.0.1:8765/`
- 默认绑定 localhost；Docker 用 `LEDGER_HOST=0.0.0.0`
- GET 为主；验证码人工解允许 POST `/api/captcha/open|done`
- 数据真源：MySQL；页面 `data/web/ledger_app.html` 经 `/api/*` 拉数

## NAS 部署（爬虫 + 台账，MySQL 沿用现库）

```
# 项目目录放好 .env（MYSQL_* 指向现有库）
docker compose up -d --build
# 台账：http://<NAS-IP>:8765/
```

- 文件：`Dockerfile`、`docker-compose.yml`、`scripts/docker_entrypoint.sh`
- 容器内：台账常驻 + 按 `CRAWL_INTERVAL_HOURS` 跑增量
- 验证码/WebBridge 仍在本机划；Cookie 可挂载 `data/sessions`

## 数据流

```
定时/手动 jobs
  → source adapter（HTTP ± WebBridge）
  → pipeline
  → MySQL notices + crawl_runs
  → 本机只读 API → 台账 UI
```

## 配置

- `config/sources.json` 源站开关
- `config/anti_bot.json` 反爬
- `config/crawl_config.json` 词与城市
- `config/product_plan.json` 机器摘要（与本文档同步）
