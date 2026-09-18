# WebBridge 本地桥（127.0.0.1:10086）

## 一句话

「打开 webbridge」= 启动**官方 daemon**（`~/.kimi-webbridge/bin/kimi-webbridge.exe`）+ 浏览器里 Kimi 扩展自动连上。

> **2026-09-18 换桥（重要）**：桥服务端从旧 Python 脚本 `scripts/webbridge_server.py`（只服务 `/command`）
> 换成**官方 daemon**（服务 `/status`）。旧脚本**已弃用，不能再让它占 10086** ——
> 它一占，官方 daemon 起不来、扩展连不上，表现为**所有 WebBridge 源静默 0 条**
> （2026-09-18 江苏站空跑 47 分钟就是此因，详见 changelog）。

## 架构

- 爬虫（crawl/webbridge_client.py）→ HTTP POST http://127.0.0.1:10086/command
- **官方 daemon**（`kimi-webbridge.exe`，v2.0.15）→ WebSocket；扩展为 WS 客户端，浏览器开着自动连
- Kimi 扩展（Chrome，MV3 + chrome.debugger）→ 驱动真实浏览器执行 navigate/evaluate/cdp 等
- 状态：GET http://127.0.0.1:10086/**status** → `{running, extension_connected, extension_version, ...}`

## 可用性判定（严格）

`wb.available()` = **daemon 在线 且 `extension_connected=true`**。
只看端口（旧实现）会在扩展掉线时误报「可用」→ 采集源每词空跑、最后 0 条却当正常返回。

## 启动 / 停止 / 保活（一键，标准能力，勿再逆向）

**日常不需要手工操作**：采集员跑 webbridge 源前会**等桥就绪**（`_wait_bridge_ready`：掉线时等它恢复，默认上限 `SPIDER_BRIDGE_WAIT_SEC`=300s，恢复即继续；HTTP 源不受影响）。

```
python scripts/wb_bridge.py status         # 桥 + 扩展连接状态
python scripts/wb_bridge.py start          # 起 daemon + 开浏览器 + 等扩展（一次性，缺啥补啥）
python scripts/wb_bridge.py stop           # 停桥
python scripts/wb_bridge.py watch          # 常驻保活：每 120s 巡检，掉了自动拉起（单例，写心跳）
python scripts/wb_bridge.py ensure-daemon   # 确保保活进程在跑（心跳判断；死了就后台拉起）
```

**保活三层（口径："wb 不该出现挂掉的状态"）**：

1. 常驻 `watch`（Windows 任务 SpidermanWebBridge 的动作）做细粒度自愈；每轮写心跳
   `data/web/wb_watch_heartbeat.json`；**单次巡检异常绝不杀死保活**；**单例**（心跳新鲜即退出）。
2. `ensure-daemon` 解「守护者自己挂了没人管」：心跳新鲜 → no-op，陈旧 → 后台 detached 重拉；
   采集员每次跑会调它。
3. 采集时 `_wait_bridge_ready` 再等一道。

> 为什么不只靠常驻守护进程：**谁来守护守护者？** 不依赖"改任务触发器"（需提权，实测被拒），
> 用「心跳 + 按需拉起」让任意调用点都能自愈。

## 故障恢复（实测）

杀 `kimi-webbridge.exe` → 保活 **106 秒**自动拉起并恢复（巡检间隔 120s，故一个周期内）。

## 协议（自扩展 background.js v1.11.5 逆向，供维护）

| 方向 | 消息 |
|---|---|
| 扩展→服务 | {type:hello, payload:{extensionVersion}} |
| 服务→扩展 | {type:tool_call, requestId, payload:{name,args}} |
| 扩展→服务 | {type:tool_result, responseToRequestId, payload:{data}|{error}} |
| 服务→扩展 | {type:ping} → 扩展回 {type:pong} |

HTTP /command：body {action,args,session} → {ok:true,data:...}；
无扩展连接时返回 503 {ok:false,error:{code:no_extension}}（jiangsu 爬虫据此如实报 webbridge_not_available）。

## 注意

- 两个浏览器都装扩展时都连同一桥：命令路由到先连上的扩展。跑浏览器源时只开一个浏览器最稳。
- 桥命令串行执行（服务端加锁），符合反爬串行纪律；jiangsu 仍按 4~6 小时一轮的节奏跑。
- 桥不在线 ≠ 站点封禁：观测报告里不计 blocked_count，只在 empty_platforms/错误串里体现。

## 扩展工具清单（2026-08-25 实测，v1.11.6；未知工具名会回错并附此清单）

navigate, find_tab, evaluate, network, snapshot, click, fill, mouse_click, cdp,
key_type, send_keys, screenshot, save_as_pdf, upload, close_tab, list_tabs, close_session

## CDP 透传（全量 Cookie 导出，含 HttpOnly）

`document.cookie` 拿不到 HttpOnly；扩展的 `cdp` 工具支持白名单 CDP 方法，可直取全量：

```python
from crawl import webbridge_client as wb
out = wb.export_cookies("https://bid.rccchina.com/", session="captcha-<todo_id>")
# → {ok, cookie: "a=1; SESSION=...", cookies: [{name,value,httpOnly,...}]}
```

- 可用：`Network.getCookies`（按 urls 过滤，实测通）、`Runtime.evaluate`；
- **不可用**：`Browser.getVersion`（回 -32601）、`Network.getAllCookies`（整浏览器导出，会挂起超时）—— 一律用 getCookies + 按站点 url 过滤。
- 接线点：crawl/captcha_flow.resolve_todo —— CDP 全量 → document.cookie → warm 会话，三级兜底存 cookie_store。
- 登录待办闭环：源站撞登录墙登记 captcha_todos → ledger「验证码待办」点「打开」（桥开登录页）→ 人工手机号+短信登录 → 点「已解决」→ 全量 Cookie 落 data/sessions/<source>.cookies.json → HTTP 源自动复用（cookie 失效再撞墙自动重新挂待办）。


