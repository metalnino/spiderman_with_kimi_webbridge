# 交付报告 · 招标采集员员工（implements: collector/v1.0.0）

> 岗位：爬虫工作区「能力工位」 ｜ 依据：contract/collector-v1.json + contract/员工模板规范.html
> 交付日期：2026-08-18（v2 增补：2026-08-20 六站全开 + 内置桥服务端）｜ 内核类型：rule ｜ 自主性预算：deterministic

## 0. v2 增补（2026-08-20）：六站全开落地

用户口径：六站长期全开；NAS 已弃用，本机为唯一运行点。

- **配置**：config/platforms.json 六站 enabled=true + route 字段（ccgp/chinabidding/ggzy/jsggzy=http，cebpub=playwright，jiangsu_zhaobiao=webbridge）；keywords.json 对齐口径（绿植租摆）。
- **路由**：外壳新增平台→执行路径路由（BROWSER_ROUTES）：HTTP 走内核 run_source；cebpub→scripts/crawl_cebpub_pw.main（Playwright）；jiangsu→scripts/crawl_jiangsu_wb.main（WebBridge）。两个浏览器脚本 main() 改为返回 {status,error,notices}（纯增量，CLI 不变）。
- **桥服务端内置**：scripts/webbridge_server.py（纯标准库，零安装）。协议自 Kimi WebBridge 扩展 v1.11.5 background.js 逆向（WS /ws + HTTP /command）；Chrome 扩展自动连接（实测 1 分钟内连上）。文档：.cursor/docs/webbridge_bridge.md。
- **调度**：crawl/scheduler.py 支持 CRAWL_MODE=collector；Windows 任务 SpidermanCollector（8/12/18/22 跑 scripts/collector_run.py）+ SpidermanWebBridge（登录自启桥服务）。
- **六站真实验证**（2026-08-19 23:11 一轮，无 mock）：ccgp 0（20 条 raw 全在 8 城外，如实报空）、chinabidding 4、ggzy 2（新增 2）、jsggzy 1（新增 1）、cebpub 5（Playwright）、jiangsu 16（WebBridge，新增 6）；fetched=28、dedup_new=9、六站成功率全 1.0、blocked=0。
- **测试**：78 用例全过（含六站路由、桥服务端冒烟、平台配置不泄漏）。



## 1. 结论先行

现有爬虫内核**未重写**，已套上完整四层外壳并通过契约测试与两轮真实抓取验证：
输入契约 input → 输出 100% 符合 output schema 的去重公告数组 → 每次运行落盘观测报告
reports/collector-report.json（六项指标齐全）。契约文件本身**未做任何修改**。

## 2. 改了什么

### 新增（外壳，全部属于适配层，不触碰内核控制流）

| 文件 | 层 | 内容 |
|---|---|---|
| crawl/collector_employee.py | 身份/契约/配置/观测 | 员工外壳主模块：IDENTITY + `IMPLEMENTS="collector/v1.0.0"`；input 校验；Notice→契约 output 映射（dedupId=md5(title+platform+url)）；按 dedupId 去重；观测报告写入 |
| scripts/collector_run.py | 入口 | 最小运行入口：契约 input（文件/stdin/缺省用配置层默认）→ 契约 output + 观测报告 |
| config/keywords.json | 配置层 | 关键词库 string[]（改进层可增删；已按 DB 启用词+核心词库种子化） |
| config/platforms.json | 配置层 | platformConfig[]：平台 id/name/enabled/method/params(selector)/proxy，6 个平台全量 |
| config/filters.json | 配置层 | filterConfig：region 白名单（8 目标城市）/ budget 阈值（默认关）/ date 阈值（默认 2026-07-01~08-31） |
| tests/test_collector_contract.py | 契约测试 | 27 个用例：身份声明、input 校验、output 字段/类型/dedupId、去重、过滤、观测指标名与类型、报告落盘、平台 selector 生效 |
| .cursor/docs/collector_employee_delivery.md | 文档 | 本报告 |

### 修改（内核上的最小增量 seam，共 2 处，均不改变原有行为）

| 文件 | 改动 | 说明 |
|---|---|---|
| crawl/config_loader.py | 新增 `platform_overrides()`，`sources_cfg()` 末尾 overlay 一层 | 让契约配置层 platforms.json 真正驱动 selector（页面改版只改 platforms.json）；文件缺失时行为与改前完全一致 |
| crawl/runner.py | `run_source` 返回值新增 `raw_total` 与 `notices`（JSON 安全 dict 数组，含 content_hash） | 内核采集结果外显给外壳做格式转换层；原返回字段一字未动，旧消费者（run_one_source/run_parallel/scheduler）不受影响 |

## 3. 输出是否 100% 符合 schema

**契约测试逐字段断言（27/27 通过）+ 两轮真实抓取人工核验：**

- 8 个字段（title/platform/url/publishTime/region/amount/summary/dedupId）全量输出、顺序与类型严格符合契约；
- dedupId = md5(title+platform+url)，32 位小写 hex；输出数组已按 dedupId 去重（同键保留先到者）；
- publishTime 统一为 ISO8601（`YYYY-MM-DDTHH:MM:SS`）；amount/summary 为 nullable，无值输出 null，**不造假**；
- region 取值链：city > province > region_text。

**两处如实说明（不视为 schema 违约，但需总设计师知晓）：**

1. **publishTime 缺日期时输出空串**。契约该字段非 nullable；个别源站条目无日期（如 ccgp 解析不到日期），外壳选择保条目、输出 ""，并在报告 `missingPublishTimeCount` 计数。本次两轮验证该计数均为 0。建议总设计师在后续版本把该字段改为 nullable（按规范属 MAJOR，需走变更流程）。
2. **summary 恒为 null**。内核目前只有列表字段+详情金额回填，无正文摘要能力；契约允许 nullable，故 schema 符合，但属能力缺口（见第 5 节）。

## 4. 观测指标是否都能上报

六项指标全部实现并在真实运行中验证（见 reports/collector-report.json）：

| 指标 | 验证结果 |
|---|---|
| fetched_count | ✅ 第一轮 6（chinabidding 6 + ccgp 0）；第二轮 2 |
| dedup_new_count | ✅ 第一轮 0（均为上轮已入库，真实反映）；第二轮 2（新词「绿植租赁」实增 2 条，证明增量口径正确） |
| platform_success_rate | ✅ {chinabidding: 1.0, ccgp: 1.0}；口径：1.0=success/partial，0.0=failed/error |
| empty_platforms | ✅ 第一轮 ["ccgp"]——ccgp 本轮抓了 20 条原始但全部落于 8 城之外被城市过滤，如实报空（selector 未失效信号，但有 0 结果即上报） |
| blocked_count | ✅ 0（本轮未触封禁）；口径已写入报告 notes：按源站最终错误串中 403/频控/封禁 信号计数（内核内部重试期的 403 不对外可见） |
| elapsed_ms | ✅ 第一轮 23437ms；第二轮 8912ms |

报告每次运行覆写 reports/collector-report.json（契约 reportPath），另含 runId/startedAt/input/effectiveFilters/perPlatform/skipped/filterDrops/missingPublishTimeCount 等增量字段（观测指标按规范可增量加，不破坏契约）。

## 5. 还差什么（如实清单）

1. **summary 能力缺口**：内核无正文摘要抓取（chinabidding 详情登录墙、cebpub 验证码、ggzy JS 渲染）；现按契约 nullable 输出 null。补法：详情页可抓的源（如 ccgp）先落摘要。
2. **amount 依赖详情回填**：chinabidding 为 list_only，amount 恒为 null（契约允许）；登录墙 Cookie 配置后可补。
3. **外壳过滤只能「收窄」**：内核 crawl_config.json 的 only_target_cities/publish_date_range 是硬前置过滤，契约 input.regionFilter/dateRange 在此之上叠加，不能拓宽。缓解：config/filters.json 默认值与内核口径一致；若总设计师要求 input 完全支配过滤，需再开一个内核 seam。
4. **blocked_count 粒度**：内核重试循环内部的 403 未外显计数，当前按最终错误串统计；如需精确到每次请求，需在 HttpSession 加计数器（小改动，待总设计师定优先级）。
5. **registry 注册**：按规范 registry.json 属总设计师工作区维护，本工作区已在代码与报告声明 implements: collector/v1.0.0，等待总设计师写入注册表。
6. **dedup 双键并存**：输出去重键按契约 md5(title+platform+url)，入库去重仍用内核 content_hash（source|external_id）——契约定格式、内核管实现，两者各司其职；dedup_new_count 以内核入库键口径统计（= 本次新增入库数）。

## 6. 验证记录

- 测试：python scripts/run_tests.py → 71 用例全过（含新增 27 个契约用例；skipped=3 为需 SPIDER_LIVE_TESTS 的既有用例）。
- 真实抓取两轮（均走真实网络+真实 MySQL，非 mock）：
  - 轮 1（绿植租摆 × chinabidding+ccgp）：output 6 条真实公告，全字段齐全；
  - 轮 2（绿植租赁 × chinabidding）：output 2 条，dedup_new_count=2 证明增量链路；
  - 输入输出证据：data/collector/verify_input.json、verify_output.json、verify_stdout.txt；观测报告：reports/collector-report.json。
- 红线自查：未改契约任何字段；未做任何业务决策（报价/投标/客户关系）；内核未重写，仅 2 处增量 seam。
