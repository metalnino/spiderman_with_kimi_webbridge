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
| 2026-08-16 | 两路合并并 NAS 部署：接入 jiangsu HTTP 521 的 __jsl_clearance_s 纯 HTTP 解；定时改固定时刻 8/12/18/22 东八区；CRM 主体规范化全国合并(uk_name)；SSH 重建镜像验证 healthy |
| 2026-08-16 | 台账后端换 FastAPI（api.py + uvicorn，契约不变/自动 /docs）；源站精简为 4 站（停用 ggzy/jsggzy，代码保留）；Dockerfile 用清华 PyPI 镜像 |
| 2026-08-17 | 本机并行重跑(绿植租摆/8城/7-8月)：ccgp 可用但 8城+7-8月交集极少；加发布时间范围过滤；cebpub Playwright 渲染+提取已通、关键词过滤未通(加密搜索 searchName 未传)；chinabidding info_search 超时；jiangsu 521(JSL 未解)。以上为待修项 |
| 2026-08-18 | 六站全部攻克定稿：jiangsu WebBridge 真浏览器(JSL 两阶段) 11 条入库；cebpub Playwright performSearchRequest 5 条入库（见 anti_bot_lessons.html）；NAS 此后弃用，本机为唯一运行点 |
| 2026-08-19 | 员工化套壳：招标采集员 collector/v1.0.0 外壳四层 + 契约测试；配置层 keywords/platforms/filters.json；观测报告 reports/collector-report.json；内核仅 2 处增量 seam |
| 2026-08-20 | 六站全开（长期口径）：platforms.json 全 enabled + 路由(ccgp/chinabidding/ggzy/jsggzy=HTTP，cebpub=Playwright，jiangsu=WebBridge)；内置桥服务端 scripts/webbridge_server.py（标准库，Chrome 扩展自动连）；scheduler 支持 CRAWL_MODE=collector；本机定时任务 SpidermanCollector(8/12/18/22)+SpidermanWebBridge(登录启动) |
