"""瑞达恒（标慧帮，bid.rccchina.com）—— 手机号+短信注册/登录墙源站。

三级探路结论（2026-08 实测）：
  ① HTTP：www 首页即营销页；招标产品在 bid.rccchina.com（SPA，/login 路由）；
      搜索接口需登录态（checkLoginStatus 门槛），未登录不可直取；
  ② Playwright：同墙（渲染后仍只见营销/注册页）；
  ③ WebBridge：真实浏览器无账号同样被墙。

登录闭环（2026-08 落地）：
  采集员撞墙 → 登记 captcha 待办（ledger「验证码待办」tab）→ 用户点「打开」，
  桥把 https://bid.rccchina.com/login 开到固定会话 → 用户手机号+短信完成注册/登录 →
  点「已解决」→ CDP Network.getCookies 导出全量 Cookie（含 HttpOnly）→
  cookie_store 落 data/sessions/rccchina.cookies.json → HTTP 源自动复用。
  Cookie 失效撞墙 → 自动重新登记待办，闭环。

搜索接口接线：登录态实测后补（fetch 有 cookie 时如实报 cookie_ok_api_unmapped，
绝不编造 0 结果；接口形态用桥 network 工具从真实会话抓包确认）。
"""
from __future__ import annotations

from typing import Iterable

from crawl import cookie_store
from crawl.captcha_queue import open_todo
from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError

LOGIN_URL = "https://bid.rccchina.com/login"


class RccchinaSource(BaseSource):
    source_id = "rccchina"
    source_name = "瑞达恒标慧帮"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cookie = cookie_store.cookie_header(self.source_id)
        if not cookie:
            # 幂等登记：同一 source+url 只留一条 open 待办
            open_todo(
                self.source_id,
                LOGIN_URL,
                title="瑞达恒(标慧帮)需手机号+短信注册/登录",
                note=(
                    "请在打开的页面完成手机号+短信登录；完成后点「已解决」，"
                    "系统自动保存全量 Cookie（含 HttpOnly）供 HTTP 抓取复用。"
                ),
            )
            raise SourceError(
                "rccchina register_wall: 招标数据需手机号+短信注册/登录，已登记待办；"
                "登录后点「已解决」保存 Cookie，下一轮自动带 Cookie 抓取"
            )
        # 有 Cookie：真实抓取（搜索接口需登录态实测接线，见模块说明）
        raise SourceError(
            "rccchina cookie_ok_api_unmapped: 已有登录 Cookie，但 bid.rccchina.com 搜索接口"
            "待登录态实测后接线（如实报错，不编造 0 结果）"
        )
