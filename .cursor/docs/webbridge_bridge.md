# WebBridge 本地桥服务端（127.0.0.1:10086）

## 一句话

「打开 webbridge」= 启动本机桥服务端（标准库脚本，零安装）+ 浏览器里 Kimi WebBridge 扩展自动连上。
Chrome 和 Edge 均已装扩展（Chrome=v1.11.5），无需再装任何东西。

## 架构

- 爬虫（crawl/webbridge_client.py）→ HTTP POST http://127.0.0.1:10086/command
- 桥服务端（scripts/webbridge_server.py）→ WebSocket ws://127.0.0.1:10086/ws
- Kimi WebBridge 扩展（Chrome/Edge，MV3 + chrome.debugger）→ 驱动真实浏览器执行 navigate/evaluate/list_tabs 等
- 扩展为 WS 客户端：浏览器开着就会自动连接；断开后每 30s 对账自动重连（无需点扩展图标）

## 启动 / 停止（一键，标准能力，勿再逆向）

**日常不需要手工操作**：采集员（crawl/collector_employee.py）跑 webbridge 源前会自动调用
ensure_bridge() —— 桥服务没起就起、浏览器没开就开、等扩展连上，全自动、幂等。

手工运维一条命令（scripts/wb_bridge.py）：

```
python scripts/wb_bridge.py status    # 桥 + 扩展连接状态
python scripts/wb_bridge.py start     # 起桥服务 + 开浏览器 + 等扩展（缺啥补啥，幂等）
python scripts/wb_bridge.py stop      # 停桥服务（pidfile）
```

兜底：Windows 任务 SpidermanWebBridge（登录自启，长驻）。

状态自检：GET http://127.0.0.1:10086/ → {ok:true, extensions_connected:N}；N≥1 即桥通。

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


