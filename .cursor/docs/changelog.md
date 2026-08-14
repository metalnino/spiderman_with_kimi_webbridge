# 过程决策简记

| 日期 | 决策 |
|------|------|
| 2026-08-09 | 四站固定；江苏搁置；MySQL utf8mb4；HTTP主 WebBridge辅 |
| 2026-08-09 | 建立 `.cursor/docs` 为过程文档唯一源；验收看阶段勾选 |
| 2026-08-09 | 仓库：https://github.com/metalnino/spiderman_with_kimi_webbridge |
| 2026-08-09 | P0 落地：crawl 包四站增量入库 + incremental.html；T1–T5 自测通过（库约 73 条） |
| 2026-08-09 | P1/P2：清洗/级联看板/词库/监控/AI钩子/人工标记/验证码待办；unittest 14/14 |
| 2026-08-09 | P3：jsggzy（全国 ggzy 江苏切片）+ 采招 Cookie 详情可选 + CRM/entities；unittest 18/18 |
| 2026-08-09 | 台账改为本机只读 API（127.0.0.1:8765）+ ledger_app 壳页；静态 dashboard 作离线快照 |
| 2026-08-09 | 验证码：本机同事划（打开/已解决）+ Cookie 落盘回灌；台账仅放行 captcha POST |
| 2026-08-09 | NAS Docker：爬虫+台账容器（MySQL 沿用）；compose 暴露 8765 |
| 2026-08-11 | 接入江苏招标网 jiangsu_zhaobiao（账号登录可选+滑块人工；列表 Dqsearch） |
| 2026-08-14 | 修复主入口 ImportError（build_incremental_html→list）；网络测试 SPIDER_LIVE_TESTS=1 门控；http 4xx/5xx/网络错误分类；关键词上限可配(默认不限)；验证码待办去重；6 站配置/看板同步；补根 README；unittest 26/26 |
| 2026-08-14 | 详情字段抓取起步：crawl/detail.py 新增 ccgp 详情 HTTP 解析（金额/招标人/代理/项目编号）并接入 runner 回填；探针确认 ggzy=JS壳、jiangsu=Cloudflare、cebpub=验证码、chinabidding=登录墙（待接入）；unittest 27/27 |
