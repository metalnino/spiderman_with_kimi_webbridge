# 反爬策略

## 一句话

HTTP 主爬；需要时 WebBridge 暖会话拿 Cookie，再限速 HTTP；假动作不带 Cookie 无意义。

## 标准流程

1. （可选）WebBridge 打开首页/搜索，短停留  
2. Cookie 交给 HTTP Session  
3. HTTP 带 UA + Referer + Cookie，随机间隔拉数  
4. 频控/403/验证码 → WebBridge 或人工  
5. 仍失败 → 只入库列表字段，详情标待补  

## 分站

| 站 | 主路径 | 备注 |
|----|--------|------|
| ggzy | HTTP getTradList | 829 停词/降速 |
| chinabidding | HTTP info_search | 详情登录墙，list_only |
| ccgp | WebBridge 或暖会话后慢 HTTP | 易频繁访问 |
| cebpub | HTTP 列表 | 详情 vaptcha 人工后复用 |

配置源：`config/anti_bot.json`
