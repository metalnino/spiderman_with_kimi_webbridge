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

- 需求口径：关键词 = 租摆族 + 花卉族 + 场景绿植族 + 办公绿化族 + 职场绿植绿化（共 20 词，全量审计见 `.cursor/docs/keywords_audit.md`）× 8 城（南京/上海/苏州/杭州/武汉/深圳/广州/合肥）× 发布时间 2026-07-01 ~ 2026-08-31；词库收窄必须 config.active 与 DB keyword_state 两层同步。
- 架构：HTTP 主爬 + 真浏览器（WebBridge/Playwright）过反爬；NAS 已弃用（2026-08-20），本机为唯一运行点、九站运行 + 瑞达恒暂缓（注册墙暂无账号，邮件验证码回传闭环已备，见 .cursor/docs/rccchina_email_auth.md）：ccgp/chinabidding/ggzy/jsggzy/yfbzb=HTTP，cebpub/tgnet=Playwright，jiangsu/qianlima=WebBridge（qianlima 搜索 API 曾被 CloudWAF 418 IP 级硬拦，2026-08-25 起经 HK 出口代理恢复；无代理环境遇 418 只探 1 词即停）；共享同一 MySQL。Windows 任务 SpidermanCollector（11:00/22:00，config 驱动 keywords.json+platforms.json）自动覆盖全部启用站点与 20 词。
- 员工口径：采集走「招标采集员」外壳（crawl/collector_employee.py，implements collector/v1.2.0）→ 契约 output（含 tenderFile，可空）+ reports/collector-report.json（7 项指标）。
- WebBridge 开桥 = 已固化的代码能力，禁止重新逆向：桥服务端 scripts/webbridge_server.py（127.0.0.1:10086，Chrome/Edge 扩展自动连）；一键运维 scripts/wb_bridge.py status/start/stop；采集员跑 webbridge 源前自动 ensure_bridge()（起桥+开浏览器+等扩展，幂等）。协议文档 .cursor/docs/webbridge_bridge.md。
- 反爬兜底原则：部分结果必须保留（SourceError.partial）；频控靠冷却阶梯不靠轰炸；测试夹具必须自清理。
