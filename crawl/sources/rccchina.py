"""瑞达恒（标慧帮，bid.rccchina.com / rccchina.com）—— 注册墙占位源站。

三级探路结论（2026-08 实测）：
  ① HTTP：首页 200，但招标数据全部会员墙内（首页即营销页，搜索需 checkLoginStatus，
     免费试用表单 trialForm 需手机号 + 短信验证码）→ 不可直取；
  ② Playwright：同墙（渲染后仍只见营销/注册页）；
  ③ WebBridge：真实浏览器无账号同样被墙。
结论：需要注册账号（手机号+人工短信验证码）。本源站如实返回空 + 登记待办，
等账号/验证码就位后补 fetch 实现（结构与其余 HTTP 源一致）。
"""
from __future__ import annotations

from typing import Iterable

from crawl.captcha_queue import open_todo
from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError

REGISTER_URL = "http://www.rccchina.com/"


class RccchinaSource(BaseSource):
    source_id = "rccchina"
    source_name = "瑞达恒标慧帮"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        # 幂等登记：同一 source+url 只留一条 open 待办
        open_todo(
            self.source_id,
            REGISTER_URL,
            title="瑞达恒(标慧帮)需注册账号（手机号+短信验证码）",
            note="招采数据在会员墙内；提供账号 Cookie 或完成免费试用后，再实现列表/详情抓取（结构同 HTTP 源）。",
        )
        raise SourceError(
            "rccchina register_wall: 招采数据需注册账号（手机号+短信验证码），已登记待办"
        )
