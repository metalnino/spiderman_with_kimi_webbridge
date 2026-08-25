# 瑞达恒「邮件验证码回传」登录闭环

> 目标：人不在爬虫电脑旁也能完成瑞达恒（bid.rccchina.com）的手机号+短信登录。
> 原理：短信到用户手机（号码在 .env）；验证码从人回传到机器走**邮件回路**——
> 机器发请求邮件 → 用户手机回复邮件附验证码 → 机器 IMAP 收取 → 桥自动填码登录 → Cookie 落盘。

## 流程

```
采集员发现 rccchina 撞墙（register_wall / cookie_ok_api_unmapped）
  → scripts/jobs/rccchina_email_auth.py auto（≤8 分钟，含轮询）
      1) 桥开 bid.rccchina.com/login → 填手机号 → 点「获取验证码」（短信到用户手机）
      2) Gmail SMTP 发「【爬虫验证码】瑞达恒登录 #rcv<ts>」到 EMAIL_TO（默认 279152260@qq.com）
      3) 用户手机收到邮件 → 直接回复，内容只写 4~6 位验证码（5 分钟有效）
      4) 机器 IMAP 每 30s 轮询带 #tag 主题的未读回复 → NFKC 提取验证码（跳过 19xx/20xx 年份）
      5) 桥填手机号+验证码 → 提交 → CDP Network.getCookies 导出全量 Cookie
         → data/sessions/rccchina.cookies.json → captcha 待办关闭 → 回发「登录完成」确认邮件
```

- 同一封回复只尝试一次（尝试后标已读），绝不重放过期验证码；
- 8 分钟没收到回复 → 本轮放弃，marker 保留 ≤6 小时；下一轮调度自动重新发请求邮件（每轮最多一封）；
- Cookie 失效再撞墙 → 自动再走一轮，无需人工记忆。

## 配置（全部在 .env，不进 git）

| 键 | 说明 |
|---|---|
| GMAIL_USER / GMAIL_APP_PASSWORD | Gmail 账号 + 应用专用密码（**Gmail 设置需开启 IMAP**；可与发日报的复用） |
| RCCCHINA_PHONE | 瑞达恒登录手机号（短信发到此号） |
| EMAIL_TO | 收请求/回复的邮箱，默认 279152260@qq.com |
| EMAIL_PROXY | 可选；Gmail 走代理隧道（国内直连 Gmail 不稳，填本机代理 http://127.0.0.1:端口；不填则按系统代理→直连） |

## 运维

- 手动触发：`python scripts/jobs/rccchina_email_auth.py --auto`（request+轮询+登录一条龙）
  - 单步：`--request`（只发请求邮件）/ `--complete`（只轮询收信并完成登录）
- 采集员自动挂接：rccchina 撞墙时 run() 末尾自动跑 auto（≤8 分钟；`SPIDER_NO_EMAIL_AUTH=1` 可关）。
- 邮件网关：scripts/email_gateway.py（SMTP 465 直连→走代理隧道；IMAP 993 同；主题 #tag 过滤，不读无关邮件）。
- 安全：应用专用密码只存 .env；收信仅匹配 #tag 主题；验证码只用于瑞达恒登录，不落库。

## 仍待实网验证（凭据配齐后）

1. Gmail SMTP/IMAP 经本机代理隧道的连通性（eg.send / eg.poll_replies）；
2. bid.rccchina.com 登录页真实 DOM 的填表/按钮选择器（当前为通用占位匹配，实测后微调）；
3. 登录后搜索接口接线（RccchinaSource 目前如实报 cookie_ok_api_unmapped，接口形态待登录态抓包）。
