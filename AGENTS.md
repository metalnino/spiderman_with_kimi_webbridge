# AGENTS.md — 本项目协作规则（AI Agent 必读）

> 所有 AI Agent（不限工具）在本仓库工作时默认遵守以下规则；与全局规则冲突时以本文件为准。

## 1. 思考方式

- 思考（thinking/reasoning）全程用英文；最终回复与总结用中文。
- 用第一性原理分析：先拆解到最基本事实（可达性、字段、反爬、关键词、地区粒度），再重新推导；不套用未经检验的假设。
- 先想清楚再动手；优先用探针/小样本验证假设，再扩规模。

## 2. 协作方式（自主执行）

- 用户只给需求，其余全自主：**自定计划 → 编码 → 写测试 → 跑测试 → 修报错 → 文档 → 部署 → 提交**，闭环完成。
- 不要讨论开发过程/测试/文档/部署细节，只汇报最终结果；失败自己修，不回头问。
- 仅在以下情况暂停询问：缺关键密钥/账号、破坏性操作、合规红线、目标互相矛盾。
- 遇到小问题禁止暂停询问，自行处理。

## 3. 输出

- 中文、简洁、先结论后依据；不废话、不重复已知信息。
- 重要发现必须落成可复用产物（代码/配置/文档），不只停留在聊天。

## 4. 诚实记录不可抗力

- 验证码、需登录账号、IP 频控等外部阻塞：如实记录在案（crawl_runs.note、待办、文档），绝不造假、不把「假 0」当成功。
- 0 条结果必须可自证（记录 raw/过滤丢数），页面有结果却解析为 0 时视为 bug 预警。

## 5. 文档与规则优先级

- 权威细节见 `.cursor/rules/`（自主执行与第一性原理、按文档开发、MySQL 规范）与 `.cursor/docs/`（architecture / data_model / filters_cascade / anti_bot_lessons.html / phases/当前阶段.md）。
- 配置与文档冲突时先改齐再写代码；过程文档只放 `.cursor/docs/`，不要另起平行目录。

## 6. 项目关键口径（当前阶段）

- 需求口径：关键词 = 租摆族 + 花卉族 + 场景绿植族 + 办公绿化族 + 职场绿植绿化 + 室内绿化 + 室外养护族 + 运动场养护族 + 工程景观族 + 供应采购族（2026-08-26 三次扩展，共 42 词，全量审计见 `.cursor/docs/keywords_audit.md`）× 8 城（南京/上海/苏州/杭州/武汉/深圳/广州/合肥）× 发布时间 2026-07-01 ~ 2026-08-31；词库增删必须 config.active + DB keyword_state + config/keywords.json 三层同步。
- 架构：HTTP 主爬 + 真浏览器（WebBridge/Playwright）过反爬；NAS 已弃用（2026-08-20），本机为唯一运行点、十站运行（2026-09-18 新增「深圳阳光采购平台」szexgrp，HTTP JSON API、无登录/无验证码）+ 瑞达恒暂缓（注册墙暂无账号，邮件验证码回传闭环已备，见 .cursor/docs/rccchina_email_auth.md）：ccgp/chinabidding/ggzy/jsggzy/yfbzb/szexgrp=HTTP，cebpub/tgnet=Playwright，jiangsu/qianlima=WebBridge（qianlima 搜索 API 曾被 CloudWAF 418 IP 级硬拦，2026-08-25 起经 HK 出口代理恢复；无代理环境遇 418 只探 1 词即停）；共享同一 MySQL。Windows 任务 SpidermanCollector（11:00/22:00，config 驱动 keywords.json+platforms.json）自动覆盖全部启用站点与 42 词。源站启用口径唯一权威 = config/platforms.json（sources.json 的 enabled 仅作无外壳层时的内核兜底）；两层漂移由 crawl.sources.source_config_drift() 检测，/api/health 暴露 + tests/test_collector_contract.py::test_no_source_config_drift 断言，改其中一层必须同步另一层。
- 员工口径：采集走「招标采集员」外壳（crawl/collector_employee.py，implements collector/v1.2.0）→ 契约 output（含 tenderFile，可空）+ reports/collector-report.json（7 项指标）。实体升维走「实体情报员」外壳（crawl/intel_employee.py，implements entity_intel/v1.0.0）→ 读 notices 累积库产出实体图（entities/winners/relations，含中标企业抽取与周期粗估）+ reports/intel-report.json + handoffs/intel/latest.json；入口 scripts/intel_run.py，先跑 scripts/migrate_ops.py 建 notices.winner 列。采集员详情补全（agent 纵向链）走 scripts/collector_detail.py（详情→原发寻址→原发转爬 + AI 字段抽取兜底，写 notices.ai_fields；AI 用 crawl/ai_extract.py，DeepSeek 文本、失败降级规则、只抽取不判断）；独立于 11:00/22:00 定时任务。**采集员入口自带启动自记录**（`scripts/collector_run.py`，2026-09-19）：stdout/stderr 全量落 `logs/collector_run_<时间戳>.log`（留最近 30 份）+ 启动戳 `logs/collector_launch.json` + 未捕获异常留栈并 exit 1；`SPIDER_NO_RUN_LOG=1` 关。原因：任务动作是裸 `python.exe scripts\collector_run.py`，Task Scheduler 不落 stdout、本机 `TaskScheduler/Operational` 日志亦关闭，启动期死亡否则完全无痕（09-18 22:00 实证）。
- WebBridge 开桥 = 已固化的代码能力，禁止重新逆向：桥服务端 = **官方 daemon `~/.kimi-webbridge/bin/kimi-webbridge.exe`**（127.0.0.1:10086，Kimi 扩展自动连；**旧 `scripts/webbridge_server.py` 已弃用，不得再让它占 10086** —— 它一占，官方 daemon 起不来、扩展连不上，WebBridge 源就静默 0 条）。可用性严格判定：`wb.available()` = daemon 在线 **且** `extension_connected=true`（只看端口会误报）。**浏览器统一走 Chrome（Edge 已弃用）**：开页面只用 `webbridge_client.open_in_chrome()`（Chrome 候选路径；`EDGE_CANDIDATES` 已删），**禁用 `webbrowser.open`**（走系统默认浏览器，可能落到 Edge）。保活三层：常驻 `scripts/wb_bridge.py watch`（Windows 任务 SpidermanWebBridge 的动作，每 120s 巡检 + 写心跳 `data/web/wb_watch_heartbeat.json`）+ `wb_bridge.py ensure-daemon`（心跳陈旧则后台重拉）+ 采集时 `_wait_bridge_ready` 等桥恢复（默认 300s，`SPIDER_BRIDGE_WAIT_SEC` 可调；HTTP 源不受影响）。协议文档 .cursor/docs/webbridge_bridge.md。
- 反爬兜底原则：部分结果必须保留（SourceError.partial）；频控靠冷却阶梯不靠轰炸；测试夹具必须自清理。
