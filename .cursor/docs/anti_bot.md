# 反爬策略

## 一句话

HTTP 主爬；需要时 WebBridge 暖会话拿 Cookie，再限速 HTTP；假动作不带 Cookie 无意义。

## 标准流程

1. （可选）WebBridge 打开首页/搜索，短停留  
2. Cookie 交给 HTTP Session  
3. HTTP 带 UA + Referer + Cookie，随机间隔拉数  
4. 频控/403/验证码 → 写入 `captcha_todos`，本机同事划  
5. 仍失败 → 只入库列表字段，详情标待补  

## 本机同事划码（当前）

1. 台账打开 http://127.0.0.1:8765/ →「验证码待办」→「打开」  
   或：`python scripts/jobs/solve_captcha.py open --id <id>`  
2. 在 WebBridge/浏览器里完成滑块或输入  
3. 点「已解决」或：`python scripts/jobs/solve_captcha.py done --id <id>`  
4. Cookie 落到 `data/sessions/<source>.cookies.json`（gitignore），后续 HTTP 自动带上  
5. 若导出不到 Cookie，可：`done --id <id> --cookie "k=v; ..."` 手动粘贴  

说明：`document.cookie` 拿不到 HttpOnly；拿不到时待办仍可关闭，列表照进。

## 分站

| 站 | 主路径 | 备注 |
|----|--------|------|
| ggzy | HTTP getTradList | 829 停词/降速 |
| chinabidding | HTTP info_search | 详情登录墙，list_only |
| ccgp | WebBridge 或暖会话后慢 HTTP | 易频繁访问 |
| cebpub | HTTP 列表 | 详情 vaptcha 人工后复用 |

配置源：`config/anti_bot.json`
