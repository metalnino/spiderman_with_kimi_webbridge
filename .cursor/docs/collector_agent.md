# 采集员 agent 化：从「爬中介层」到「追原发真实数据」

> 背景：确认采集员目前仍停留在「中介层」，要把纵向链补成「详情 → 原发寻址 → 原发转爬 → AI 字段抽取」。
> 配套：岗位分层见 `.cursor/docs/pipeline.md`；交付与自评见本文。

## 一、结论（确认你的判断）

你的判断**对**，且代码为证：

| 环节 | 现状 | 判定 |
|---|---|---|
| 详情抓取 | `tenderfile.py` 有 DETAIL_MODES 路由，但只对可投标阶段回填、每站限额 | 🔶 半接 |
| 原发寻址 | `origin.py` 有，但只是 `backfill` 里的兜底，非采集员主循环一等步骤 | 🔶 半接 |
| 原发转爬 | `is_http_fetchable` 只认 ccgp/ggzy/jszwfw 三个域，是兜底 | 🔶 很窄 |
| AI 详情分析 | `ai_hooks.py` 是占位（extract_buyer 恒返回 None），只有验证码 OCR 用了 DeepSeek | ❌ 缺 |

所以：**采集员确实还在「中介层命中」，没系统追到「原发真实数据」；AI 详情分析此前是空壳。** 这次补上纵向链的 AI 一段，并把已有的详情/原发/转爬能力收编成一个独立补全入口。

## 二、设计（第一性原理）

采集员的完整职责 = 从「中介层命中」出发，追到「原发真实数据」：

```
S1 入口（已闭环）      聚合站关键词 → 命中条目（title/url/time/region）
S2 详情（半接→收编）   详情页正文/附件 → summary + tenderFile + 结构化字段
S3 原发寻址（半接）     正文「信息来源：…http…」→ original_url + origin_source
S4 原发转爬（很窄）     原发 URL 可直取 → 直抓原发站真实字段（采购人/代理/金额/截止/附件）
S5 AI 字段抽取（本次补） 规则抓不到的字段 → DeepSeek 文本 → JSON；失败降级规则
S6 落库 + 观测         字段/summary/tenderfile/original_url/origin_source/ai_fields
```

红线：AI 只「抽取」不「判断」；失败降级规则；抽不到 null 不编造；不碰业务决策。

## 三、本次落地

| 文件 | 内容 |
|---|---|
| `crawl/ai_extract.py` | AI 详情字段抽取（DeepSeek 文本 → JSON），只抽 buyer/agency/amount_text/deadline/winner；失败/禁用/坏输出 → `{}` 降级规则 |
| `config/ai_extract.json` | AI 抽取配置（model=deepseek-chat，api_key 复用 ocr_api.json，不重复存密钥） |
| `crawl/backfill.py` | `_save_result` 增 `ai_fields`；新增 `ai_enrich_notice()`（AI 只补规则缺失字段，绝不覆盖）；ccgp 详情回填 summary |
| `crawl/detail.py` | `parse_ccgp_detail` 增加详情正文 summary（供 AI/原发寻址）；`update_notice_detail` 允许 winner |
| `scripts/collector_detail.py` | 详情补全独立入口：缺详情公告 → backfill（详情/原发/转爬）→ AI 兜底；单轮/每站限额 |
| `sql/schema.sql` + `scripts/migrate_ops.py` | 新增 `notices.ai_fields JSON` 列 |
| `tests/test_ai_extract.py` | 12 用例（JSON 解析/清洗/成功/禁用/网络失败/坏输出） |
| `tests/test_collector_detail.py` | 3 用例（编排/每站封顶/关 AI；mock DB/backfill/AI）；`collector_detail.run()` 输出每条的决策链留痕 `traces[]` |
| `config/origin_fetch_routes.json` + `crawl/origin.py` | 原发转爬路由配置化：`fetch_route_for()` 域名→模式；补 ccgp 区域站（ccgp-jiangsu 等） |
| `tests/test_origin.py` | 6 用例（ccgp 中央/区域、ggzy、jszwfw、未知域、wrapper） |

**真机验证（DeepSeek 实调，非 mock）**：喂一段合成公告正文，5 个字段全抽对——
`buyer=南京某医院、agency=某招标代理有限公司、amount_text=12.5万元、deadline=2026年9月1日 10:00、winner=某园林工程有限公司`。证明 `deepseek-chat` 模型可用、prompt/JSON 清洗正确。

**真机跑批（`collector_detail.py --limit 4 --per-source 2`）**：4 条全部详情回填成功，AI 2 条成功（yfbzb）2 条诚实空（tgnet）。落库抽查证实链闭环且诚实：
- yfbzb → `ai_fields={"buyer":"中航测…公司",…}`（列表页摘要，只抽到采购人，其余 null）；
- tgnet → `ai_fields={}`（登录墙摘要，无内容可抽，如实空）。
- 关键发现：**聚合站的「详情页」经常是列表页/登录墙，而非真实公告正文**——这正是「还停在中介层」的根因，光靠 AI 抽不出被登录墙挡住的字段，必须靠「原发转爬」去原发站拿真实数据。

## 四、自评（思辨是否达到设计要求）

**达到：**
- AI 字段抽取能力落地 + 真机验证 + 失败降级 + 测试 ✅
- 详情/原发/转爬能力收编成独立补全入口，不破坏定时任务 ✅
- schema 扩容（winner + ai_fields）✅

**还没达到（诚实记录，下一步）：**
1. **原发转爬是最大瓶颈（真机已证）**：聚合站「详情页」常是列表页/登录墙，不是真实公告正文，AI 抽不出被登录墙挡住的字段。`is_http_fetchable` 只认 ccgp/ggzy/jszwfw，各市政府采购网/单位官网无直取能力——要「追到原发真实数据」，扩展原发域直取是主线。
2. **AI 仍是「兜底抽取」，决策链是顺序脚本**：`collector_detail.py` 已输出每条的决策留痕 `traces[]`（详情/原发/转爬/AI 逐段），但「发现原发→判断可直取→决定转爬」仍是写死的顺序，未做成可编排的 agent 循环。
3. **AI 未接自动流程**：`collector_detail.py` 是手动入口（刻意，避免影响 11:00/22:00 定时任务）；要自动需另配定时或接到采集员出勤后钩子。
4. **AI 抽取真实抽取率样本还小**：真机跑 4 条（2 成 2 诚实空），样本不足；扩大原发转爬后才有真实正文可抽。

**红线守住：** AI 只抽取不判断、失败降级规则、诚实 null、不破坏现有任务。

## 五、运行方式

```powershell
python scripts/migrate_ops.py            # 建 ai_fields 列（幂等）
python scripts/collector_detail.py       # 详情补全（默认 20 条/每站 5/开 AI）
python scripts/collector_detail.py --limit 50 --per-source 10
python scripts/collector_detail.py --no-ai   # 只做规则详情补全
```

## 六、原发转爬可扩展化（round 2）

- 路由从硬编码 `HTTP_FETCHABLE_SUFFIXES` 改为 `config/origin_fetch_routes.json`（域名后缀 → 模式）+ `origin.fetch_route_for()`；新增原发域 = 加一条 suffix + 在 backfill 按 mode 加抓取函数。
- 补 ccgp 区域站点：`www.ccgp-jiangsu.gov.cn` 等各省政府采购网与中央同平台，`fetch_route_for` 命中 `ccgp-` 即归 `ccgp_http`。
- 真机发现：1276 条公告里只有 2 条有原发 URL，且此前 0 条可直取——一条 `ccgp-jiangsu.gov.cn`（本次已可直取）、一条 `ciesco.com.cn`（中国招标投标，不可直取）。**根因：原发寻址常给出「平台首页」而非「具体详情 URL」**（`match_entity_map` 命中主体→平台映射时兜底给首页）。

## 七、下一步迭代（按优先级）

1. **站内检索（真瓶颈）**：原发寻址给出平台首页时，需要在原发站按标题/项目编号检索到具体详情页，再直取。这是「追到原发真实数据」缺失的最后一环，需逐站点实现（先对 ccgp-jiangsu / 各市交易中心探针站内搜索接口）；
2. **把决策链做成显式 agent loop**：`详情 → 原发寻址 → (有具体URL? 直取 : 站内检索) → 回填/AI 兜底` 做成可编排循环；
3. 扩大真机跑批样本，观察 AI 抽取率。
