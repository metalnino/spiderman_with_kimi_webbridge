# 数据模型

库：`spiderman_bids`（utf8mb4）  
Schema：`sql/schema.sql`  
连接：`.env` + `scripts/db.py`

## 表

### notices（公告主表）

关键字段：source_id、external_id、title、publish_date、city、keyword、amount、detail_url、content_hash、created_at（首次发现）

去重：`source_id + external_id` 或 `content_hash` upsert  
增量定义：首次插入 = NEW（用 created_at）

### crawl_runs（任务批次）

source_id、started_at、finished_at、status、item_count、note  
用于「运行监控 / 是否跑成功」

### entities（主体，P1+）

采购人聚合；P0 可不写页面

## 凭证

只存 `.env`，禁止提交。MCP：`spiderman-mysql`
