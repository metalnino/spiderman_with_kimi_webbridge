# 江苏招标网（jiangsu.zhaobiao.cn）

## 接入方式

- `source_id`: `jiangsu_zhaobiao`
- 列表：`GET /psearch/Dqsearch?page=&queryword=&field=all&attachment=1`（可匿名拿到标题/链接）
- 登录：`https://user.zhaobiao.cn/login.html` → `ssologin.do?method=loginPost`
- 凭证：`.env` 中 `JIANGSU_ZHAOBIAO_USER` / `JIANGSU_ZHAOBIAO_PASS`（勿提交仓库）

## 登录与验证码

登录页含**滑块/行为验证码**。自动登录失败时：

1. 写入 `captcha_todos`
2. 同事打开登录页划码
3. `solve_captcha.py done` 或台账「已解决」回灌 Cookie 到 `data/sessions/jiangsu_zhaobiao.cookies.json`

未登录时仍可跑列表入库；详情/会员字段依赖登录 Cookie。

## 运行

```
python scripts/jobs/run_one_source.py jiangsu_zhaobiao --keywords 绿化养护 --pages 1
```
