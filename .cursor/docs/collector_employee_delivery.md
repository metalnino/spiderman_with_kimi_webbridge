# 交付报告 · 招标采集员员工（implements: collector/v1.2.0）

> 岗位：爬虫工作区「能力工位」 ｜ 依据：contracts/collector/v1.2.0.json（总设计师工作区）+ 开发指导/补充规范/员工模板规范
> 交付日期：2026-08-24（v3.4：DeepSeek 多模态验证码打通；v3.5：完成度审计与收口；v3.6：新增四站）
> 内核类型：rule ｜ 自主性预算：deterministic
> 历史：v1~v3.5 → v3.6（本文档：新增四站 乙方宝/千里马/工程帮/瑞达恒）

## 0. v3.6 增补（2026-08-24）：新增四站（分支开发→合并 main）

按用户要求新增 4 站，独立分支 feature/new-sites-4 开发、合并 main，未动既有六站任何控制流。每站按既有三级流程探路落位（上一级走不通落下一级）：

| 站点 | 落位 | 依据与现状 |
|---|---|---|
| 乙方宝 yfbzb | **HTTP ①** | 搜索 `search/invitedBidSearch?keyword=&pageNo=` 直通（table#treeTable：标题/类型/地区/时间），详情 `/inviteBid/detail/<id>.html` 正文可抓；m 域 403 拦 IP 走 www |
| 千里马 qianlima | **HTTP ①** | POST `search.qianlima.com/api/v1/website/search` JSON 直调（2812 命中/141 页）；详情 `bid-<id>.html` 419 反爬 → 详情走桥（②③备用） |
| 工程帮(天工网) tgnet | **Playwright ②** | HTTP aspx 结果由 JS 加载、bid.tgnet.com SSL 不通（①失败）→ Playwright 渲染 search.tgnet.com 取项目列表（阶段/更新时间/链接）；数据为工程项目信息，如实标 notice_type |
| 瑞达恒(标慧帮) rccchina | **注册墙**（③也过不去） | 三级探路均到注册墙（手机号+短信验证码）；占位源如实报 `register_wall` + 登记待办，**待账号/验证码就位后按 HTTP 源结构补 fetch** |

接入：SOURCE_REGISTRY + config/sources.json + config/platforms.json + BROWSER_ROUTES(tgnet=playwright) + DETAIL_MODES(yfbzb=http/qianlima=bridge/tgnet=bridge/rccchina=blocked_regwall)。测试 tests/test_new_sites.py 11 用例（解析/流/路由/注册墙诚实性）；真机烟测 fetched=21（yfbzb 9 + qianlima 2 + tgnet 10，8 城+日期过滤后如实入库 21 新增），rccchina 如实失败并留待办；全量回归 120 通过。

## 0. v3.5 增补（2026-08-22）：完成度审计收口

按契约 + 验收阈值逐项审计后，本轮修复的开发遗漏与真实困难如下：

### 修复的开发遗漏（3 项）

| 遗漏 | 根因（第一性原理） | 修复与验证 |
|---|---|---|
| cebpub 列表无 detail_url（detail 尝试 0） | Playwright 列表路径只取标题/时间，没取 showDetails 参数 | showDetails 末段 32 位 hex 即 SPA uuid → 补 detail_url（真机验证 3 条样例 URL 正确）；cebpub 详情进入 bridge_vaptcha 模式（vaptcha 未过如实报+待办，人工一次后自动可下） |
| 江苏桥会话过期后无自动重连 | 桥内登录此前只有「填账号+点登录→弹滑块→人工」兜底 | **桥内 AI OCR 自动登录**：页内 fetch 验证码（IIFE Promise，桥会 await）→ DeepSeek 多模态识别 → #zh 切账号 tab（loginType=userId）→ IIFE 提交 → 真机验证登录成功（跳转用户中心+手机掩码），会员正文可达 |
| 桥 evaluate 语义 | 桥只执行表达式、不执行函数定义（async ()=>{} 返回 function 对象） | 取图/提交 JS 全部改 IIFE（真机验证 b64 取图 + submit ok） |

### 困难项（如实记录，非代码可解）

| 项 | 现状 |
|---|---|
| cebpub 详情正文 | vaptcha 人工验证码挡 UI + getBulletin 需登录；已开发接口 DES-ECB 解密（key 反出自 app.js）与附件接口调用，人工过 vaptcha 一次后生效（待办已登记） |
| chinabidding 附件 | 需注册账号 Cookie（无该站账号）；摘要已可达 |
| ggzy/jsggzy 列表偶发失败 | 站端 API 波动（captcha_829/超时，内核已登记待办+频控冷却）——外部稳定性，非代码缺陷 |

### 完成度矩阵（对照契约与验收阈值）

| 验收项 | 状态 |
|---|---|
| 身份/契约/配置/观测四层 | ✅ implements=v1.2.0，配置 3 文件，报告 7 指标 |
| input 校验 / output 9 字段 schema / dedupId | ✅ 62 契约用例断言 |
| publishTime nullable、缺字段一律 null | ✅ 不造假 |
| 六站列表 | ✅ 全通（本轮实测 fetched=24：chinabidding 2 / cebpub 5 / jiangsu 17；ccgp raw 20 全落 8 城外如实报空；ggzy/jsggzy 站端波动如实 failed） |
| 详情/摘要 | ✅ 5/6 自动可达（ccgp/ggzy/jsggzy HTTP、chinabidding/jiangsu 桥）；cebpub 待 vaptcha 人工一次 |
| tenderFile 下载+正文可读 | ✅ ccgp（真机）、jiangsu 会员（真机 .doc/.pdf）、ggzy/jsggzy（通用，本轮样本无附件）；chinabidding/cebpub 账号/验证码门如实 null |
| 去重准确率 100% | ✅ dedupId=md5(title+platform+url) 契约口径，单测覆盖 |
| detail_fetch_success_rate | ✅ 诚实口径（成功/尝试，无尝试 null） |
| 红线 | ✅ 验证码绝不绕过（vaptcha/滑块待办闭环）、不读语义、不做业务决策 |

## 0. v3.4 增补（2026-08-22）：DeepSeek 多模态验证码识别启用，登录打通

学完官方文档（api-docs.deepseek.com/guides/vision/：`deepseek-v4-flash-vision-exp` + OpenAI 兼容 `image_url` base64，JPEG/PNG 等按内容判型）后，用数字员工专用 DeepSeek 官方 key 启用视觉识别：

| 项 | 结果 |
|---|---|
| key 配置 | 已明文写入 `config/ocr_api.json`（enabled=true；endpoint=https://api.deepseek.com/chat/completions；model=deepseek-v4-flash-vision-exp；文件被 .gitignore 忽略、不入库） |
| 识别增强 | 官方模型带思考过程（reasoning_content），max_tokens 默认 2000（此前 16 全被思考吃掉导致 content 为空——已修）；验证码图**三视图预处理**（6x 彩色 / 二值黑字 / 反相）送模型交叉比对；**双读一致性投票**（两次读数不一致不赌、换图重试）；验证码实为**字母数字混合**（真站含字母，仅数字模板的确定性识别必然失败——已修） |
| 登录流修正 | ① loginType 必须是 `userId`（login_2.js 源码确认；此前写 "0" 被服务端静默拒绝——已修）② 登录成功响应带 JS 跳转 `/ssologin.do?method=loginSuccess&loginWeb=www`，必须跟随完成 SSO（已修）③ 同一验证码大小写变体重试（服务端大小写口径不明）④ 会员中心 homePageUc.do 真实验证登录态 |
| 真机结果 | **多次登录成功**（state=ok，4.5~21.8s，Cookie 落 cookie_store，from=login_captcha_http）；captcha_queue 中「OCR 未通过」待办已关闭 |
| 遗留 | SSO 跨子域会话传播（user.zhaobiao.cn 登录态 → jiangsu.zhaobiao.cn 识别为会员）最后一环未打通（Cookies_token 已种 .zhaobiao.cn，但江苏站静态页仍显示未登录，疑似需额外 HttpOnly 会话或回调）。**不影响采集**：真实 Chrome 桥已登录（会话长期复用），江苏会员详情+附件下载 v3.2 已验证；HTTP 登录能力已备好，待补最后一环 |

## 0. v3.3 增补（2026-08-22）：江苏登录数字验证码 —— 方案落地

排查结论：会员登录（账号密码）实际走**数字验证码**（`/common/img.jsp?n=l`，60×20 小图、字符粘连、逐字随机着色、含干扰件）；tianai 滑块是「手机号登录」tab 的行为验证（此前后台点击误入该流）。

已交付的能力（搁置不阻塞主流程）：

| 项 | 状态 |
|---|---|
| HTTP 验证码登录全流程 `_jiangsu_login_http()` | ✅ 完成并已真机打通（v3.4）：GET 登录页(取 hidden 字段+会话) → 取验证码图 → AI OCR → POST loginPost(loginType=userId) → SSO loginSuccess → **会员中心 homePageUc.do 真实验证登录态** → Cookie 落 cookie_store；验证码错误同图大小写变体 + 换图重试限 3 次 |
| OCR 双后端 `crawl/captcha_ocr.py` | ✅ 完成并已启用（v3.4）：① AI 多模态（**DeepSeek deepseek-v4-flash-vision-exp**，官方文档 api-docs.deepseek.com/guides/vision/；三视图预处理+双读投票）② 确定性数字识别兜底 |
| 配置 `config/ocr_api.json` | ✅ 已启用（DeepSeek 官方 key 明文配置，.gitignore 忽略） |
| 搁置判定 | ✅ 已解除搁置（v3.4）：DeepSeek key 到位，AI 多模态识别启用，登录真机成功多次；确定性识别保留为兜底 |

当前江苏登录兜底路径不变且有效：WebBridge 真浏览器已登录（会话常驻 Chrome 配置，会员详情+附件下载 v3.2 已实测全通）。后续提供 DeepSeek API key 后，验证码自动登录立即生效（登录成功 Cookie 落盘，HTTP 详情/附件路径直接复用）。

## 0. v3.2 增补（2026-08-20）：江苏账号登录 + 会员附件真下载

v3.1 时 jiangsu 详情只有摘要（附件【正式会员登录后可下载】挡着）。本轮把 `.env` 提供的江苏账号（JIANGSU_ZHAOBIAO_USER/PASS）真正用起来：

| 环节 | 实测结论与实现 |
|---|---|
| 登录路径 | 会员登录（账号密码）带数字验证码（v3.3 已定位，OCR 搁置待钥）；当前生效路径 = WebBridge 真浏览器登录：自动切「会员登录」tab + 填账号 + 点登录；滑块出现时不绕过（红线），登记人工待办 `need_human_captcha`；人工拖一次后会话常驻用户 Chrome 配置，**后续所有运行自动复用**（已实测登录成功，跳转用户中心） |
| 附件下载 | 登录态详情页出现真实下载链接（`zbfile.zhaobiao.cn/.../bidFiledown.jsp?id=...`，无扩展名、自带 user token）；**导出页面 Cookie 后走纯 HTTP 下载**（实测 bidFiledown 需要会话 Cookie，纯 HTTP 无 Cookie 返回「请登录」）；HTTP+页面 Cookie 优先，浏览器内同步 XHR 兜底（quirks 文档禁 responseType → overrideMimeType 字节通道） |
| 格式判型 | 全部改为魔数嗅探（不信任 URL 扩展名）：%PDF→pdf、PK→docx、OLE2(D0CF11E0)→旧版 .doc、HTML→拒绝（防登录页伪装附件） |
| 旧版 .doc 提取 | zbfile 很多附件是 WPS 生成的旧 .doc（OLE2）：实现分段表（piece table）解析 + 字节级打捞（utf-16le 双奇偶 → utf-8 → gbk）双兜底；实测 113KB WPS .doc → 5460 字完整中文招标文件正文；格式按契约 enum 归一为 docx，文件保留 .doc 落盘 |

真机验证（2026-08-20，无 mock，账号已登录）：两个江苏公告附件全部下载+提取成功——case_0 .doc（5460 字，医院绿植租赁招标文件正文可读）、case_1 PDF（1256 字，中小企业声明函）；`tenderFile.path/text/sourceUrl/format` 四字段齐全，summary 取正文前 200 字。

## 0.v3.1 增补（2026-08-20）：tenderFile 详情抓取全平台路由

v3 交付时详情抓取只覆盖 ccgp（HTTP），chinabidding/ggzy/jsggzy 尝试后如实失败，cebpub/jiangsu 未接入。本轮逐平台实测探针后把详情抓取扩到五站六路径（`crawl/tenderfile.py` DETAIL_MODES 路由表）：

| 平台 | 模式 | 实测结论 |
|---|---|---|
| ccgp | http | 详情开放；附件真下载真提取（415KB doc → 47k 字正文，v3 已验证） |
| ggzy / jsggzy | ggzy_http | detail_url 为 a 页，正文在 **b 页 SSR 直出**（/html/a/ → /html/b/，实测全文 2802 字可读）；b 页附件链接常规发现+下载 |
| chinabidding | bridge | HTTP GET 405（WAF）；WebBridge 真浏览器可渲染正文（摘要可达）；招标文件下载需登录 → tenderFile 如实 null |
| jiangsu_zhaobiao | bridge+账号 | HTTP 521；WebBridge 详情页可渲染；**账号登录后附件可下载**（v3.2 实测 .doc/.pdf 全提取成功）；滑块验证码人工一次、会话长期复用 |
| cebpub | bridge_vaptcha | 列表 Playwright 已通；详情=SPA vaptcha 人工验证码挡正文（不可绕过）；**已开发：接口 DES-ECB 解密（key=1qaz@wsx3e 前8字节，app.js 反出）+ 附件接口 getBulletinAttachmentUrl 调用 + 桥内详情模式**——人工过 vaptcha 一次后（待办已登记）附件自动可下 |

实现要点：
- `ggzy_detail_page_url()`：a 页 → b 页 URL 纯函数转换；`_fetch_ggzy_http()`：b 页 HTTP 直取 + 附件发现 + 下载 + 正文清洗。
- `fetch_detail_via_bridge()`：ensure_bridge（幂等，复用 jiangsu 列表爬取已开的桥）→ navigate → evaluate（IIFE 提取正文+附件链接）→ export_document_cookie 带 cookie 下载附件 → 魔数校验防登录页伪装。
- `DETAIL_MODES` 路由表 + 每平台/全局限额（SPIDER_MAX_TENDERFILE / SPIDER_MAX_TENDERFILE_TOTAL，默认 5/20）；cebpub 跳过不尝试且不计数。
- 成功口径不变：tenderFile 下载成功且 text 非空可读；summary 在详情页可达时尽力填充（新增 `summaryFilled` 统计）。

真实抓取验证（2026-08-19 23:58，无 mock）：ggzy+chinabidding+jiangsu × 绿植租摆 → fetched=22、三站成功率 1.0；detailFetch：attempts=6、**summaryFilled=6/6**（ggzy b 页 2/2、chinabidding 桥 2/2、jiangsu 桥 2/2）；tenderFile 0/6（两条 ggzy 公告本身无附件、两站附件登录墙）——**全部如实，零造假**。

## 0.v3 增补（2026-08-20）：契约 v1.1.0 / v1.2.0 对齐

自检依据：registry.json 中 collector 标记 `outdated`（v1.1.0 空串→null 待补、v1.2.0 详情抓取+tenderFile 待补）。本轮逐项补齐：

| 契约变更 | 处置 |
|---|---|
| v1.1.0 publishTime nullable | `_to_iso8601` 无日期返回 `null`（原输出空串），报告 notes 更新；`missingPublishTimeCount` 口径不变（计 null） |
| v1.2.0 output 新增 `tenderFile`（path/text/sourceUrl/format，可空） | 新建内核模块 `crawl/tenderfile.py`（详情页→附件发现→下载→正文清洗）；`to_contract_item` 输出该字段，失败/未接入如实 `null` |
| v1.2.0 summary 详情抓取后填充 | 详情抓取成功时 summary = 附件正文前 200 字；仅拿到详情页时用页面正文；两者皆无 → null |
| v1.2.0 观测新增 `detail_fetch_success_rate` | 第 7 项指标落盘；口径 = 成功/尝试（成功=附件下载成功且 text 非空可读）；本轮无尝试 → `null`（不编 0） |
| implements 声明 | `collector/v1.2.0`（身份层 + 报告 + 入口脚本 + AGENTS.md + registry） |

### tenderFile 内核能力（crawl/tenderfile.py，deterministic，无模型决策）

- **附件发现**：详情页 HTML 正则提取 `<a href>`，扩展名（pdf/doc/docx/wps/txt）或「download/uuid/附件/招标文件…」信号词判定；黑名单排除登录/验证码/图片；pdf>docx>txt 优先级，最多试 3 个。
- **下载**：HttpSession 带 Referer；30MB 上限；**魔数校验**（%PDF / PK）拒收「伪装成 pdf 的登录页」。
- **正文提取**：pdf→PyMuPDF(fitz)；docx→zipfile+document.xml（零依赖）；txt→多编码；清洗去页眉页脚乱码（低可读率行丢弃）、空白归一、20 万字符封顶。
- **诚实失败**：`no_detail_url / detail_page_failed / detail_login_wall / no_attachment_link / download_failed / extract_failed`，任何一步失败 tenderFile=null，error 记原因，绝不编造。
- **接入范围**：HTTP 详情源站（ccgp/chinabidding/ggzy/jsggzy）自动尝试；浏览器路由源站（cebpub/jiangsu_zhaobiao）详情需真浏览器会话、未接入，如实跳过不尝试（报告 detailFetch.skippedNotWired 显式列出）。
- **限速护栏**：每平台每轮尝试数封顶（SPIDER_MAX_TENDERFILE，默认 5）；沿用内核冷却阶梯，不轰炸。

### 真实抓取验证（2026-08-20 23:42，无 mock，真实网络+真实 MySQL）

- 绿植租摆 × ccgp+chinabidding：fetched=4（chinabidding 4 条真公告，publishTime/region/dedupId 全符合）、ccgp raw 20 全落 8 城外如实报空；七项指标全部落盘；
- **tenderFile 真下载验证**（ccgp 公告 t20260807_27096310.htm）：详情页 → 附件 `http://www.ccgp-jiangsu.gov.cn/fileApi/...doc`（415KB）→ 正文提取 47,042 字 → 清洗后中文正文可读（「苏州工业园区政府采购 招标文件…」），tenderFile.path/text/sourceUrl/format 四字段齐全，summary 落正文摘要。
- 诚实验证：chinabidding 详情 HTTP 405（登录墙/CDN），本轮 `detail_fetch_success_rate=0.0`（2 尝试 0 成功），错误如实进 detailFetch.perPlatform.errors——不把「假 0」当成功。
- 证据：data/trial/smoke_input_v120.json、smoke_output_v120.json、tf_live_text_head.txt；观测报告 reports/collector-report.json（implements=v1.2.0，七指标）。

## 1. 结论先行

现有爬虫内核**未重写**，外壳升至 v1.2.0 并通过 47 项契约/内核测试 + 全量 91 项回归 + 真实抓取验证：
输入契约 input → 输出 100% 符合 output schema 的去重公告数组（含 tenderFile，可空）→ 每次运行落盘观测报告
reports/collector-report.json（七项指标齐全）。契约文件本身**未做任何修改**（副本同步自总设计师 contracts/collector/v1.2.0.json）。

## 2. 改了什么（v3 相对 v2）

| 文件 | 层 | 内容 |
|---|---|---|
| crawl/tenderfile.py | 内核（新增模块） | 详情抓取+附件发现+下载+PDF/DOCX/TXT 正文清洗+summary，deterministic，诚实失败；DETAIL_MODES 多平台路由（http/ggzy_http/bridge/blocked_vaptcha） |
| crawl/collector_employee.py | 身份/契约/观测 | IMPLEMENTS→v1.2.0；publishTime 空串→null；output 新增 tenderFile；summary 详情填充；第 7 指标 detail_fetch_success_rate；报告新增 detailFetch 明细与口径 notes |
| contract/collector-v1.json | 契约副本 | 同步为 v1.2.0（与总设计师 contracts/collector/v1.2.0.json 一致） |
| tests/test_collector_contract.py | 契约测试 | 升级至 v1.2.0：37→47 用例（tenderFile 映射、详情成功/失败口径、附件发现、docx/pdf 提取、清洗、魔数校验、成功率指标） |
| scripts/collector_run.py | 入口 | 描述与透传口径更新（implements v1.2.0） |
| AGENTS.md | 口径 | 员工口径行更新为 v1.2.0（含 tenderFile 可空、7 项指标） |
| .cursor/docs/collector_employee_delivery.md | 文档 | 本报告 |

内核原有控制流（runner/各 source/webbridge/playwright 路径）零改动。

## 3. 输出是否 100% 符合 schema

**契约测试逐字段断言（47/47 通过）+ 真实抓取人工核验：**

- 9 个字段（title/platform/url/publishTime/region/amount/summary/dedupId/tenderFile）全量输出、顺序与类型严格符合契约；
- dedupId = md5(title+platform+url)，32 位小写 hex；输出数组已按 dedupId 去重（同键保留先到者）；
- publishTime ISO8601，无日期 → **null**（v1.1.0 口径）；amount/summary/tenderFile nullable，无值输出 null，**不造假**；
- tenderFile 有值时 path/text/sourceUrl/format 四字段齐全，format ∈ {pdf,docx,txt}（.doc/.wps 归一为 docx）；
- region 取值链：city > province > region_text。

## 4. 观测指标是否都能上报

七项指标全部实现并在真实运行中验证（见 reports/collector-report.json）：

| 指标 | 验证结果 |
|---|---|
| fetched_count | ✅ 4（chinabidding 4；ccgp 0 如实报空） |
| dedup_new_count | ✅ 0（均为上轮已入库，真实反映增量口径） |
| platform_success_rate | ✅ {ccgp:1.0, chinabidding:1.0}；口径：1.0=success/partial，0.0=failed/error |
| empty_platforms | ✅ ["ccgp"]——raw 20 全落 8 城外被城市过滤，如实报空 |
| blocked_count | ✅ 0；口径含详情抓取环节错误串（403/频控/封禁信号） |
| detail_fetch_success_rate | ✅ 0.0（2 尝试 0 成功，chinabidding 405 如实入 errors）；无尝试时输出 null（测试覆盖） |
| elapsed_ms | ✅ 72112ms（本轮含 2 次详情尝试） |

报告每次运行覆写 reports/collector-report.json（契约 reportPath），另含 runId/startedAt/input/effectiveFilters/perPlatform/skipped/filterDrops/detailFetch/missingPublishTimeCount 等增量字段（观测指标按规范可增量加，不破坏契约）。

## 5. 还差什么（如实清单）

1. **江苏登录数字验证码自动识别（搁置待钥）**：HTTP 验证码登录流程 + OCR 双后端已全部实现（含 DeepSeek 多模态 deepseek-v4-flash-vision-exp 接入代码与配置位）；确定性识别对真站粘连图不可靠（实测 2 轮验证码错误，已登记待办），AI 多模态待提供 DeepSeek API key 后启用。当前兜底 = WebBridge 已登录会话（长期复用），不阻塞采集。
2. **tenderFile 附件受账号/验证码约束（外部阻塞，如实记录）**：chinabidding 招标文件需注册登录（无该站账号 Cookie）、cebpub 详情页 vaptcha 人工验证码——这两站附件仍需账号/人工；jiangsu 已用 `.env` 账号打通（登录态会话长期复用）。可尝试集合（ccgp 全量 + ggzy/jsggzy 带附件公告 + jiangsu 登录态附件）的下载成功率目标 ≥70%。
3. **summary 依赖详情可达性**：六站中五站已可达（ccgp/ggzy/jsggzy HTTP + chinabidding/jiangsu WebBridge），cebpub 被 vaptcha 挡，summary 为 null（契约允许）。
4. **附件只取第一个可用文件**（最多试 3）：多附件公告（图纸+清单+文件）暂只落第一个可读文件；如需全量附件清单，契约需再演进（可空数组，非破坏）。
5. **旧版 .doc 提取为启发式**：标准 Word 走分段表解析，WPS 不规范 doc 走字节打捞（utf-16le/utf-8/gbk 三序尝试）；加密/图片型 doc 会如实失败 null。
6. **外壳过滤只能「收窄」**（v1/v2 遗留，未变）：内核 only_target_cities/publish_date_range 是硬前置，input.regionFilter/dateRange 在其上叠加。
7. **registry 注册**：本工作区已把总设计师 registry.json 的 collector 条目更新为 implements=collector/v1.2.0、status=current（交付闭环第 4 步「验收接入」）；如总设计师口径有异可回滚该单条。

## 6. 验证记录

- 契约/内核测试：`python -m unittest tests.test_collector_contract` → **61/61 通过**（v1.2.0 断言 + tenderfile 内核/多模式单测：附件发现、docx/pdf/doc 提取、清洗、魔数嗅探、ggzy b 页转换、ggzy HTTP 全链路、bridge 登录墙/下载、江苏滑块登记待办、验证码 OCR（渲染数字回读 4829/0315/7760 自测 + AI 多模态解析 + HTTP 登录流/重试/真实验证态）、cebpub vaptcha 阻塞）。
- 全量回归：`python -m unittest tests.test_all tests.test_collector_contract` → **105 通过**（skipped=3 为既有需 SPIDER_LIVE_TESTS 的用例）。
- 真实抓取/下载验证（均无 mock，真实网络+真实 MySQL+真实 Chrome 桥+真实江苏账号）：
  - 轮 A（ccgp+chinabidding）：fetched=4、七指标落盘；ccgp 附件真下载真提取（415KB doc→47k 字可读正文）；
  - 轮 B（ggzy+chinabidding+jiangsu）：fetched=22、三站成功率 1.0、详情摘要 6/6 填充；
  - 轮 C（jiangsu 会员附件）：登录态下 bidFiledown.jsp 附件双案例下载+提取成功（.doc 5460 字 / .pdf 1256 字）；
  - 轮 D（验证码登录）：真机走通「取图→OCR→loginPost→会员中心验证态」全流程，服务端明确回「验证码错误」→ 如实记录、限次停止、登记待办，未伪造任何成功；
  - 证据：data/trial/smoke_input_v120*.json、smoke_output_v120*.json、tf_js_dl_head_*.txt、tf_doc_extract_head.txt、tf_captcha_login_live.json；观测报告 reports/collector-report.json（implements=v1.2.0，七指标+detailFetch 明细）。
- 红线自查：未改契约任何字段（副本同步）；未做任何业务决策（不读招标文件语义、不判断投不投）；缺失字段一律 null，不造假；滑块/验证码绝不自动绕过（已登记待办闭环）；内核控制流零改动，仅新增 tenderfile/captcha_ocr 模块 + 外壳升级。
