"""源头追溯（源头追溯员的编排内核）—— 一条线索追到「发布主体自己的平台」的一手正文。

为什么必须是独立岗位（而不是塞回采集员）：
  1. **粒度不同**：采集员按「站 × 关键词」出勤，追的是广度与时效；追溯员按 **project_key**
     （同一招标项目在 4~9 个聚合站的重复条目）作业，产出的是「项目 → 源头」一对一映射。
     把追溯塞进采集员，等于同一条公告在 4 个站被追溯 4 次（用户担心的「重复工作量」正是这个）。
  2. **成本量级不同**：每条追溯要开真浏览器、跑检索、可能下载附件（秒级~分钟级）；
     采集员单轮要守住全站 42 词，两者预算模型不可混。
  3. **失败语义不同**：采集员必须「绝不阻塞出勤」；追溯员**允许**以「人工待办 / 平台侧故障」
     结束（登录墙、502、验证码），并且必须如实记录 —— 这正是需要独立台账的原因。

追溯三步（与用户口径一致）：
  ① 判断当前源是不是源头（域名定性 + 明确证据）——是则标记 sourceIsOrigin 直接收工；
  ② 不是源头 → 从正文抽锚点（采购人 / 邮箱域名 / 正文 URL / 项目编号 / 发布媒介行）；
  ③ 用锚点找源头（平台登记表命中 → 站内检索；未命中 → 外部检索定位 → 桥渲染）→
     取回一手正文 + 可下载采购文件 → 落库并写 handoff。

落库口径（回答「会不会和采集员重复」）：
  - 追溯结果写在**独立的 origin_\* 列**（level/portal/detail_url/status/confidence/evidence），
    不覆盖采集员的 detail_status；
  - 只有在源头正文**严格更好**时才覆写 summary / tenderfile_path（更长、或原先是乱码/空）；
  - 同一 project_key 只追一次，结果广播给该组的全部 notice（含后续新增的同项目公告）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DEFAULT_CFG = {
    "enabled": True,
    "limit_total": 3,
    "max_seconds": 900,
    "min_title_score": 0.55,
    "max_candidates": 4,
    "download": True,
}


def _log(msg: str) -> None:
    print(f"[origin-trace] {msg}", flush=True)


# ---------------------------------------------------------------- 文本工具 ---

def garbled_ratio(text: str | None) -> float:
    """乱码率（不可打印/替换符/控制符占比）。用于识别「假 ok」的正文（yfbzb 实测写入过二进制垃圾）。"""
    s = text or ""
    if not s:
        return 0.0
    bad = sum(1 for ch in s if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\t\n\r") or 0xE000 <= ord(ch) <= 0xF8FF)
    return bad / len(s)


def is_usable_body(text: str | None, *, min_chars: int = 300) -> bool:
    """正文可用：够长、中文占比正常、不是乱码、不是登录墙占位。"""
    s = (text or "").strip()
    if len(s) < min_chars:
        return False
    if garbled_ratio(s) > 0.02:
        return False
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    if cjk / max(len(s), 1) < 0.15:
        return False
    if re.search(r"立即注册|免费注册.*登录|登录后查看", s[:400]):
        return False
    return True


def title_score(a: str, b: str) -> float:
    """标题核心名的 Dice 相似度（2|A∩B| / (|A|+|B|)，基于字符集）。

    为什么不用「交集/len(A)」：那样「上海职场绿植租摆服务」(10字) 与
    「华能天成融资租赁有限公司上海职场绿植租摆服务项目」(25字) 会双双得 1.0，
    无法把同一项目的「变更公告」和「原公告」区分开（实测踩过：会抓错详情 id）。
    Dice 对短标题的额外内容做惩罚：原公告=1.0，变更公告≈0.65。
    """
    from crawl.stage import project_core

    ca, cb = project_core(a or ""), project_core(b or "")
    if not ca or not cb:
        return 0.0
    inter = len(set(ca) & set(cb))
    return 2 * inter / (len(set(ca)) + len(set(cb)))


# ---------------------------------------------------------------- 候选选取 ---

_GROUP_SQL = """
SELECT project_key, COUNT(*) AS n,
       MIN(publish_date) AS first_date, MAX(publish_date) AS last_date,
       GROUP_CONCAT(DISTINCT source_id) AS srcs
FROM notices
WHERE project_key IS NOT NULL AND project_key <> '' AND origin_status IS NULL
GROUP BY project_key
ORDER BY MAX(publish_date) DESC
LIMIT %s
"""


def pick_groups(limit: int = 20, *, db=None, only_keywords: str | None = "绿植租摆|绿植租赁|植物租摆|植物租赁") -> list[dict]:
    """取待追溯的项目组（按发布时间倒序）。only_keywords=None 时不限关键词。"""
    from db import connect

    conn = db or connect()
    try:
        with conn.cursor() as cur:
            if only_keywords:
                cur.execute(
                    "SELECT project_key, COUNT(*) AS n, MAX(publish_date) AS last_date,"
                    " GROUP_CONCAT(DISTINCT source_id) AS srcs"
                    " FROM notices WHERE project_key IS NOT NULL AND project_key <> ''"
                    " AND origin_status IS NULL AND title RLIKE %s"
                    " GROUP BY project_key ORDER BY MAX(publish_date) DESC LIMIT %s",
                    (only_keywords, int(limit)),
                )
            else:
                cur.execute(_GROUP_SQL, (int(limit),))
            return [dict(r) for r in cur.fetchall()]
    finally:
        if db is None:
            conn.close()


def load_group(project_key: str, *, db=None) -> list[dict]:
    """取一个项目组的全部公告行（含正文/详情状态/已有原发线索）。"""
    from db import connect

    conn = db or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, title, city, publish_date, notice_stage, detail_url,"
                " summary, tenderfile_path, detail_status, original_url, origin_source,"
                " buyer, project_code FROM notices WHERE project_key=%s ORDER BY id",
                (project_key,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        if db is None:
            conn.close()


def load_notice(notice_id: int, *, db=None) -> dict | None:
    from db import connect

    conn = db or connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM notices WHERE id=%s", (int(notice_id),))
            row = cur.fetchone()
            if not row:
                return None
            out = dict(row)
            if not out.get("project_key"):
                from crawl.stage import project_key

                out["project_key"], out["project_name"] = project_key(out.get("title") or "", out.get("city"))
            return out
    finally:
        if db is None:
            conn.close()


def _body_of(row: dict) -> str:
    """一行的可用正文：summary 优先，其次已落盘附件正文（不重复解析，读文件头 20KB 足够取锚点）。"""
    s = row.get("summary") or ""
    if is_usable_body(s):
        return s
    p = row.get("tenderfile_path")
    if p:
        f = ROOT / str(p)
        if f.exists():
            try:
                from crawl.tenderfile import extract_text, clean_extracted_text

                txt = clean_extracted_text(extract_text(f, f.suffix.lstrip(".") or "txt"))
                if txt:
                    return txt[:6000]
            except Exception:  # noqa: BLE001
                pass
    return s if s and garbled_ratio(s) < 0.02 else ""


def pick_seed(rows: list[dict]) -> dict:
    """组内选种子行：正文可用者优先（最长），否则任取其一（标题仍能提供主体锚点）。"""
    if not rows:
        return {}
    usable = [(len(_body_of(r)), r) for r in rows]
    usable.sort(key=lambda x: -x[0])
    if usable and usable[0][0] >= 300:
        return usable[0][1]
    return rows[0]


def sibling_rows(seed: dict, *, db=None, limit: int = 30) -> list[dict]:
    """同城「近同标题」的兄弟公告。

    为什么需要：同一项目的**招标公告 / 变更公告 / 结果公告**在 project_core 上核心名不同
    （阶段词被剥离后主名也可能不同），会落进不同 project_key，于是「招标公告」那一行的标题里
    可能压根没有采购人名字（实测 50343「上海职场绿植租摆服务采购询比采购公告」无主体，
    而兄弟行 50344「华能天成融资租赁有限公司…变更询比采购公告」有）。
    追溯的锚点必须能跨这些兄弟行汇聚，否则第一条公告永远找不到源头。
    """
    from crawl.stage import project_core
    from db import connect

    frag = project_core(seed.get("title") or "")[:8]
    if len(frag) < 4:
        return []
    conn = db or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, title, summary, tenderfile_path, city FROM notices"
                " WHERE id<>%s AND title LIKE %s"
                " ORDER BY (CHAR_LENGTH(COALESCE(summary,''))>=300) DESC, id DESC LIMIT %s",
                (int(seed.get("id") or 0), f"%{frag}%", int(limit)),
            )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        if db is None:
            conn.close()
    # Dice 阈值放到 0.5：兄弟行本来就要求「同城 + 标题含同一核心片段」，
    # 而带主体名前缀的兄弟（华能天成…上海职场绿植租摆服务项目）Dice 只有 ~0.59。
    return [r for r in rows if title_score(seed.get("title") or "", r.get("title") or "") >= 0.5]


# 「自有/法定发布平台」——它们本身即源头（或最接近源头），且我们已经在采。
# szexgrp 必须在内：深圳阳光采购平台就是深圳交易集团自己的平台（实测
# szexgrp.com/jyfw/ygcgDetail.html?... 是一手页，而 chinabidding/qianlima 那几行是转载）。
# 判据不是「名单长」，而是「这个源站的域名是不是发布方自己的」：10 站里
# ccgp/ggzy/jsggzy/cebpub（法定）+ szexgrp（自有）算源头；chinabidding/qianlima/
# yfbzb/jiangsu_zhaobiao/tgnet 是转卖信息的聚合站。
HEAD_GOV_SOURCES = ("ccgp", "ggzy", "jsggzy", "cebpub", "szexgrp")


def library_origin(seed: dict, *, db=None, limit: int = 40) -> dict | None:
    """**库内通道**：源头可能已经躺在我们自己的库里，只是没和聚合站那条建立链接。

    第一性原理：聚合站的钱是「把一手的公告抄过来卖」，所以我们采的聚合站行天然是
    二手的；但我们的十站里本来就有 ccgp / ggzy / jsggzy / cebpub（法定发布平台），
    以及 szexgrp（深圳交易集团自有平台）。同一个项目在这些站上也有一行时，
    **那一行的 detail_url 就是源头**——不需要任何网络请求。

    实测：深圳国际交流中心会议酒店绿植租赁 的 szexgrp 行即一手
    （szexgrp.com/jyfw/ygcgDetail.html?...），而 chinabidding/qianlima/yfbzb 那三行是转载。
    """
    from db import connect

    from crawl.stage import project_core

    frag = project_core(seed.get("title") or "")[:10]
    if len(frag) < 4:
        return None
    marks = ",".join(["%s"] * len(HEAD_GOV_SOURCES))
    conn = db or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, title, detail_url, official_url, summary, tenderfile_path"
                f" FROM notices WHERE source_id IN ({marks})"
                " AND COALESCE(detail_url, official_url) IS NOT NULL AND detail_url <> ''"
                " AND (project_key=%s OR title LIKE %s OR title LIKE %s)"
                " ORDER BY id DESC LIMIT %s",
                (*HEAD_GOV_SOURCES, seed.get("project_key"),
                 f"%{frag}%", f"%{frag[:6]}%", int(limit)),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 —— 库内通道失败不影响主链
        return None
    finally:
        if db is None:
            conn.close()
    best, best_sc = None, 0.0
    for r in rows:
        sc = title_score(seed.get("title") or "", r.get("title") or "")
        if sc > best_sc:
            best, best_sc = r, sc
    if best and best_sc >= 0.6:
        best["_score"] = round(best_sc, 3)
        return best
    return None


# ---------------------------------------------------------------- 追溯主流程 ---

def _candidate_filter(results: list[dict], *, registry: dict) -> list[dict]:
    """外部检索结果 → 源头候选（排除镜像/聚合站，保留未知域与官方域）。"""
    from crawl.origin_portals import classify_domain, domain_of, is_mirror_title

    out: list[dict] = []
    seen: set[str] = set()
    from urllib.parse import urlparse

    for r in results or []:
        u = str(r.get("url") or "")
        if not u.startswith("http"):
            continue
        d = domain_of(u)
        if not d:
            continue
        # 去重键必须**带端口**：温州银行的采购栏目挂在 www.wzbank.cn:8087，
        # 若按端口无关的域名去重，它会被 80 端口的主站 URL 挤掉（实测真源头就是这样丢的）。
        try:
            netloc = urlparse(u).netloc.lower()
        except Exception:  # noqa: BLE001
            netloc = d
        if netloc in seen:
            continue
        if any(d == nd or d.endswith("." + nd) for nd in NON_SOURCE_DOMAINS):
            continue  # 企业信息站/门户转载：不是发布源，直接不进候选
        seen.add(netloc)
        level = classify_domain(u, registry=registry)
        if level in ("aggregator",):
            continue
        score = {"head": 1.0, "gov": 0.9, "platform": 0.8}.get(level, 0.45)
        if is_mirror_title(r.get("title") or "", registry):
            score -= 0.25
        out.append({**r, "domain": d, "level": level, "score": round(max(score, 0.1), 2)})
    out.sort(key=lambda x: -x["score"])
    return out


# 镜像站正文特征：命中即判定「这还是转载页，不是源头」。
# 直接后果：即便标题相似度满分也拒绝认源（防止把另一个聚合站当成一手发布）。
MIRROR_BRANDS = (
    "招标采购导航网", "比地招标", "采招网", "千里马招标", "剑鱼标讯", "物业招标",
    "标通通", "电力能源招标网", "中国采购与招标网", "招标采购网", "中招联合",
    "标讯订阅", "招标网", "采购与招标网", "发布专栏", "招标信息专栏",
)
MIRROR_GATES = ("登录后查看", "注册后查看", "开通会员", "升级会员", "付费会员",
                "成为会员", "会员可见", "立即注册查看", "仅限会员")

# 列表页判据：一手公告详情页只有这一条公告，正文里「公告/公示」类词出现个位数到十几次；
# 聚合站的「某公司专栏 / 列表页」会在一页里堆几十条（实测 m.bidnews.cn/q-xxx 一页 22 次）。
# 双阈值：绝对量 ≥20 判定列表页；≥12 且正文很短（<2000 字，说明整页几乎都是标题链接）也算 ——
# 政府站详情页侧栏常挂一堆公告链接（实测 ccgp 详情页 15 次但正文长），单看绝对量会误杀。
LIST_PAGE_HARD = 20
LIST_PAGE_SOFT = 12
LIST_PAGE_SHORT_CHARS = 2000

# 企业信息站（企查查/天眼查…）：正文里必然含采购人全称，靠「主体名命中」会误判成源头（实测踩过）。
NON_SOURCE_DOMAINS = (
    "qcc.com", "tianyancha.com", "qixin.com", "aiqicha.baidu.com", "maimai.cn",
    "kanzhun.com", "zhipin.com", "gsxt.gov.cn", "creditchina.gov.cn", "baidu.com",
    "zhihu.com", "sohu.com", "163.com", "douyin.com", "xiaohongshu.com",
)

_DATE_PAT = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")


def extract_dates(text: str | None, *, limit: int = 40) -> list[str]:
    """页面正文里的日期（YYYY-MM-DD）。"""
    out: list[str] = []
    for m in _DATE_PAT.finditer(text or ""):
        try:
            d = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            continue
        if d not in out:
            out.append(d)
        if len(out) >= limit:
            break
    return out


def date_consistent(text: str | None, publish_date, *, window_days: int = 45) -> bool:
    """源头页日期与聚合站公告日期是否同一次采购。

    为什么必须查：同一采购人每年发同名项目（实测「南京师范大学相城实验小学室内绿植租赁服务」
    2026-07 与 2026-09 各一次），标题/主体全对，只有日期能区分 —— 不查就会把去年的公告
    当成今年的源头写进库。页面上找不到任何日期时不做否决（避免误杀）。
    """
    import datetime as _dt

    if not text:
        return True
    base = None
    if isinstance(publish_date, _dt.datetime):
        base = publish_date.date()
    elif isinstance(publish_date, _dt.date):
        base = publish_date
    else:
        s = str(publish_date or "")
        m = _DATE_PAT.search(s)
        if m:
            try:
                base = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                base = None
    if base is None:
        return True
    dates = extract_dates(text[:2000]) or extract_dates(text)
    if not dates:
        return True
    for d in dates:
        try:
            dd = _dt.date(*[int(x) for x in d.split("-")])
        except ValueError:
            continue
        if abs((dd - base).days) <= window_days:
            return True
    return False


# 一手公告详情页的「正文特征」：采购人要让供应商联系得上/报得了名，这些词必然出现。
# 用它来对冲「列表页」判据 —— 见 mirror_signals 的说明（温州银行官网曾被 list_page 误杀）。
DETAIL_SIGNALS = (
    "投标人资格", "供应商资格", "资格要求", "获取招标文件", "获取采购文件", "获取交易文件",
    "递交截止", "开标时间", "报名", "联系人", "联系电话", "电子邮箱", "项目编号",
    "招标人", "采购人", "一、", "二、", "三、",
)

# 未知域（既不在登记表、又不是 gov、也不是采购人自己的域）只能算「疑似」：
# 实测 www.diuta.com/caigou_xxx.html 就是一个不在名单里的镜像详情页，正文完整、标题也对得上，
# 靠「不是列表页 + 标题相似 + 含项目名」全都拦不住。判据要换成「这页是不是采购人自己发的」。
TRUE_HEAD_HINT = "自域邮箱"


# 标题/正文净化：project_core 会剥掉标点，所以拿它去原文里做子串匹配会失败
# （实测「安徽交控…花卉绿植租赁、养管服务采购（三次）项目」的 core 去掉「、（）」后
# 在页面原文里根本不是连续子串 → hard_hit 判否，真源头页被丢掉）。两边都净化后再比。
_PUNCT_STRIP = re.compile(r"[\s（）()【】\[\]{}：:，,。.、/\\\-—–_+|·《》\"'“”]+")


def _norm_text(s: str | None) -> str:
    return _PUNCT_STRIP.sub("", s or "")


def _title_stage(t: str) -> str:
    try:
        from crawl.stage import classify_stage

        return classify_stage(t or "")[0]
    except Exception:  # noqa: BLE001
        return "other"


def _is_site_root(url: str) -> bool:
    """URL 是否只是「站点/栏目首页」（路径段 ≤2）——那种页面才值得往下钻一层。"""
    from urllib.parse import urlparse

    try:
        segs = [x for x in urlparse(url or "").path.split("/") if x]
    except Exception:  # noqa: BLE001
        return False
    return len(segs) <= 2


def detail_page_signals(text: str | None) -> list[str]:
    t = text or ""
    return [s for s in DETAIL_SIGNALS if s in t]


def self_published_email(text: str | None, host: str) -> list[str]:
    """页面里的联系邮箱域名 == 页面域名 → 这页就是采购人自己发的（不是转载）。

    第一性原理：一手发布页的**义务**是让供应商联系得上采购人，所以它必然给出采购人域名的
    邮箱/电话；而镜像站的商业模式是「把联系方式藏起来卖会员」，不会给可用的直接邮箱。
    实测：温州银行页给的是 07077@wzbank.cn，而页面正是 wzbank.cn —— 一手性由此确证。
    """
    h = (host or "").lower()
    if not h:
        return []
    root = ".".join(h.split(".")[-3:]) if h.count(".") >= 3 else h
    core = ".".join(h.split(".")[-2:])
    hits = []
    for d in re.findall(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text or ""):
        d = d.lower()
        if d.endswith(core) or core.endswith(d) or d.endswith(root):
            hits.append(d)
    return hits


def mirror_signals(text: str | None) -> list[str]:
    """页面文本里的镜像信号（品牌名任一命中，或会员门 ≥2 处，或公告类词堆量）。

    `list_page:` 只是**弱信号**：政府站/企业官网的详情页侧栏也常挂一堆公告链接
    （实测温州银行一手详情页 page_id/36919 命中 list_page:21，被误判成列表页而丢掉真源头）。
    调用方必须用 detail_page_signals 对冲：有正文特征就不是列表页。
    """
    t = text or ""
    hits = [b for b in MIRROR_BRANDS if b in t]
    gates = [g for g in MIRROR_GATES if g in t]
    if len(gates) >= 2:
        hits += gates
    n = t.count("公告") + t.count("公示")
    if n >= LIST_PAGE_HARD or (n >= LIST_PAGE_SOFT and len(t) < LIST_PAGE_SHORT_CHARS):
        hits.append(f"list_page:{n}")
    return hits


def _fetch_and_verify(url: str, *, title: str, hints: dict, publish_date=None, portal_id: str,
                      wait_sec: float, download: bool, min_score: float, fetch_fn=None) -> dict:
    """打开候选页并验证「确实是这条公告，且确实是源头页」。

    四道关：① 排除企业信息站等非发布源 ② 排除镜像页（品牌名/会员门）
    ③ 标题相似度达标 ④ 正文能对上**项目核心名或项目编号**（仅命中采购人名不算数）
    ⑤ 页面日期与该次采购同期（防同年同名的另一次采购）。
    """
    from crawl.origin_portals import classify_domain, domain_of

    fetch = fetch_fn or _default_fetch
    host = domain_of(url)
    if any(host == d or host.endswith("." + d) for d in NON_SOURCE_DOMAINS):
        return {"ok": False, "error": f"non_source_domain:{host}", "url": url, "score": 0.0}
    page = fetch(url, portal_id=portal_id, wait_sec=wait_sec, download=download)
    if page.get("error"):
        return {"ok": False, "error": page["error"], "url": url}
    text = page.get("text") or ""
    pt = page.get("pageTitle") or ""
    mirror = mirror_signals(text)
    dsignals = detail_page_signals(text)
    # 列表页判据只保留「品牌/会员门」；`list_page:` 是弱信号，被正文特征对冲掉
    hard_mirror = [m for m in mirror if not m.startswith("list_page")]
    if [m for m in mirror if m.startswith("list_page")] and len(dsignals) < 2:
        hard_mirror += [m for m in mirror if m.startswith("list_page")]
    score = max(title_score(title, pt), title_score(title, text[:400]))
    from crawl.stage import project_core

    core = project_core(title or "")
    code = str((hints or {}).get("projectCode") or "").strip()
    # 硬锚点只认「项目核心名/完整标题」或「项目编号」：采购人名太容易在别处出现（企查查页、往年公告页）。
    # 注意核心名（project_core）会**连阶段词一起剥掉**，而页面原文里是有阶段词的 ——
    # 只比核心名会在带「、（三次）」这类写法的标题上失败（实测安徽交控被误判 no_project_anchor）。
    # 所以两边都用「只去标点、不删词」的同一函数归一化，并额外比一次完整标题。
    ntext = _norm_text(text)
    ncore = _norm_text(core)
    ntitle = _norm_text(title)
    title_hit = bool(len(ntitle) >= 10 and ntitle in ntext)   # 页面上有**完整标题**：最强证据
    hard_hit = bool(title_hit or (len(ncore) >= 6 and ncore in ntext)
                    or (code and code in text))
    date_ok = date_consistent(text, publish_date)
    # 一手性：已登记平台/gov 天然可信；未知域必须有「自域邮箱」这类一手证据，否则只能算疑似
    level = classify_domain(url)
    self_mail = self_published_email(text, host)
    trust = "high" if (level in ("head", "gov", "platform") or self_mail) else "low"
    # 页面含完整标题 = 这就是那条公告，**不再要求标题相似度达标**：
    # 很多一手详情页的 <title>/首屏是「询比采购公告 - XX集团」这类站点级文案，
    # Dice 天然低，用它当关卡会把已经命中的真源头又挡回去（实测安徽交控/温州银行都死在这）。
    verified = (not hard_mirror) and date_ok and (title_hit or (hard_hit and score >= min_score))
    if hard_mirror:
        err = "mirror_page:" + "/".join(hard_mirror[:3])
    elif not hard_hit:
        err = "no_project_anchor"
    elif not date_ok:
        err = "date_mismatch"
    elif not verified:
        err = "title_mismatch"
    else:
        err = None
    return {"ok": bool(verified and (page.get("summary") or text)), "verified": verified,
            "score": round(score, 3), "hardHit": hard_hit, "titleHit": title_hit,
            "dateOk": date_ok, "mirror": hard_mirror[:3], "detailSignals": len(dsignals),
            "trust": trust, "selfMail": self_mail[:2], "url": url, "page": page,
            "error": err, "level": level}


def _default_fetch(url: str, *, portal_id: str, wait_sec: float, download: bool) -> dict:
    """取一手页：**HTTP 直取优先，桥兜底**。

    为什么这个顺序是关键：一手源头里有大量「企业官网自建采购栏目」（温州银行 wzbank.cn、
    安徽交控 ahjg.com）、政府站（czju.suzhou.gov.cn）、自有交易平台（szexgrp.com）——
    它们全是静态/半静态、无 WAF 的普通 HTTP 站。而需要真浏览器的只有 SPA + WAF 那一小撮
    （华能 ec.chng.com.cn 纯 HTTP 412）。实测：候选预筛若一律开浏览器，8 个候选要 80 秒；
    走 HTTP 只要几秒，且能顺带直接发现附件直链（温州银行 4 个 docx 就在 HTML 里）。
    """
    from crawl.origin_portals import fetch_origin_page
    from crawl.tenderfile import (
        _download_and_extract, _page_summary, _plain, discover_attachment_urls,
    )

    out: dict = {"ok": False, "error": None, "text": "", "summary": None,
                 "pageTitle": "", "attachments": [], "links": [], "session": None, "via": None}
    try:
        from crawl.http_session import HttpSession

        http = HttpSession("origin")
        html = http.get_text(url, headers={"Referer": url})
        if html and len(html) >= 400:
            text = _page_summary(html) or ""
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            title = _plain(m.group(1)) if m else ""
            out.update(ok=True, text=text, summary=text, pageTitle=title, via="http",
                       links=extract_links(html, url))
            if download:
                atts = discover_attachment_urls(html, url) or []
                if atts:
                    tf, err = _download_and_extract(http, f"origin/{portal_id}", url, atts)
                    if tf:
                        out["attachments"] = [tf]
                    else:
                        out["attachmentError"] = err
            return out
    except Exception as e:  # noqa: BLE001 —— 直取失败（WAF/超时/502）→ 桥兜底
        out["error"] = f"http_failed:{str(e)[:80]}"

    page = fetch_origin_page(url, portal_id=portal_id, wait_sec=wait_sec, download=download)
    if page.get("ok"):
        page["via"] = "bridge"
        return page
    merged = dict(out)
    merged.update(page)
    merged["via"] = "bridge_failed"
    return merged


_LINK_RE = re.compile(r"<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
# 站点内「采购栏目」的入口名（企业官网/政府站叫法各异，实测覆盖这三类就够）
NAV_KEYWORDS = ("采购信息", "采购公告", "招标公告", "招采", "招标采购", "询比采购", "询价",
                "招标信息", "采购公示", "招标询价", "供应商", "信息公开", "公告公示", "交易信息")


def extract_links(html: str, base_url: str) -> list[dict]:
    """页面所有可用链接 [{t,h}]（文本短、可点击）。用于站点内逐层下降。"""
    from urllib.parse import urljoin

    out: list[dict] = []
    seen: set[str] = set()
    for href, label in _LINK_RE.findall(html or ""):
        h = (href or "").strip()
        if not h or h.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        u = urljoin(base_url, h)
        if not u.startswith("http"):
            continue
        t = re.sub(r"\s+", " ", _TAG_RE.sub("", label or "")).strip()[:200]
        if len(t) < 2 or u in seen:
            continue
        seen.add(u)
        out.append({"t": t, "h": u})
        if len(out) >= 400:
            break
    return out


_NEXT_TEXT_RE = re.compile(r"^\s*(下一页|下页|后一页|next|more|»|›|>)\s*$", re.I)
_NEXT_HREF_RE = re.compile(r"[?&](?:page|p|pageno|pageNo|pageNum)=\d+", re.I)
_PAGE_PATH_RE = re.compile(r"/page/(\d+)", re.I)


def _next_page_link(links: list[dict], cur_url: str, max_page: int = 5) -> str | None:
    """栏目页 → 下一页 URL。找不到返回 None。

    三种真实形态都要认（实测踩过第三种）：
      ① 文本就是「下一页/下页/»」的链接；
      ② `?page=2` 查询参数；
      ③ **路径分页** `/purchase_info/list/page/2`（温州银行）—— 没有 `?page=`，也没有「下一页」二字，
         只有一排 `[1] [2] … [10]`，靠前两种判据全部识别不到，翻页直接失效。
    """
    for l in links or []:
        if _NEXT_TEXT_RE.match(l.get("t") or "") and l.get("h") != cur_url:
            return l["h"]
    for l in links or []:
        h = l.get("h") or ""
        if h != cur_url and _NEXT_HREF_RE.search(h):
            return h
    nums = [int(m.group(1)) for m in
            (_PAGE_PATH_RE.search(l.get("h") or "") for l in (links or [])) if m]
    if nums:
        m = _PAGE_PATH_RE.search(cur_url or "")
        nxt = (int(m.group(1)) if m else 1) + 1
        if nxt > max(nums) or nxt > max_page:
            return None
        return _PAGE_PATH_RE.sub("", cur_url or "").rstrip("/") + f"/page/{nxt}"
    return None


def _passed_target_date(page_text: str | None, publish_date) -> bool:
    """栏目页是否已翻过头：本页**最新**日期都早于目标公告日期 → 再往后只会更旧。

    列表按时间倒序，用它替代「翻 N 页就停」的死上限：既不漏（目标在深处也能翻到），
    也不无限翻（一旦越过目标日期立刻停）。
    """
    import datetime as _dt

    base = None
    if isinstance(publish_date, _dt.datetime):
        base = publish_date.date()
    elif isinstance(publish_date, _dt.date):
        base = publish_date
    else:
        m = _DATE_PAT.search(str(publish_date or ""))
        if m:
            try:
                base = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                base = None
    if base is None:
        return False
    dates = []
    for d in extract_dates(page_text, limit=60):
        try:
            dates.append(_dt.date(*[int(x) for x in d.split("-")]))
        except ValueError:
            continue
    if not dates:
        return False
    return max(dates) < base - _dt.timedelta(days=2)


def descend(site_url: str, *, title: str, hints: dict, wait_sec: float, download: bool,
            fetch_fn=None, max_navs: int = 3, min_link_score: float = 0.7,
            max_cands: int = 8, max_pages: int = 8, publish_date=None,
            log=lambda m: None) -> list[dict]:
    """**站点级下降**：候选是站点/栏目首页时，往下找一层，返回**按相似度排序的详情页候选列表**。

    为什么必须有这一层（实测的病根）：搜索引擎对「企业官网/政府站」返回的常常是**站点首页或
    栏目首页**，不是公告详情页 —— 温州银行采购栏目在 `wzbank.cn/purchase_info/`、安徽交控在
    `info.php?class_id=104101`、相城区政采在 `czju.suzhou.gov.cn/zfcg/`。
    只判断「这一个 URL 是不是详情页」必然全判 no_project_anchor，真源头就在眼前也抓不到。

    为什么返回**列表**而不是单个：栏目页里同主体、同阶段的**别的项目**标题相似度也很高
    （实测温州银行栏目里第一个高分命中是「12台鲲鹏芯片服务器采购公告」，不是绿植租摆），
    只取第一个就会拿着错的项目去验证然后整条链失败。返回候选列表让上层逐个验证，成本只是几次 HTTP。

    下降三步：① 首页链接里直接有标题匹配的详情链接；② 进「采购/招标」栏目页再匹配列表链接；
    ③ 栏目页正文本身就含项目核心名（有些站栏目=详情）。
    """
    fetch = fetch_fn or _default_fetch
    seed_stage = _title_stage(title)
    from crawl.stage import project_core

    core = project_core(title or "")
    root = fetch(site_url, portal_id="origin", wait_sec=wait_sec, download=False)
    if root.get("error"):
        return []
    cands: list[dict] = []

    def _take(links, via):
        for l in links or []:
            # 阶段不能**冲突**（结果公告不能顶替招标公告），但不能要求严格相等：
            # 栏目列表里的链接文本常常只有项目名、没有「公告」二字 → classify_stage 判 other，
            # 严格相等会把正确的那条直接过滤掉（实测温州银行/安徽交控都死在这一步）。
            ls = _title_stage(l["t"])
            if ls != "other" and seed_stage != "other" and ls != seed_stage:
                continue
            sc = title_score(title, l["t"])
            if sc >= min_link_score:
                cands.append({"url": l["h"], "via": via, "score": round(sc, 3),
                              "label": l["t"][:60]})

    _take(root.get("links"), "site_link")
    navs = [l for l in (root.get("links") or [])
            if any(k in l["t"] for k in NAV_KEYWORDS) and len(l["t"]) <= 24]
    for nav in navs[:max_navs]:
        page = fetch(nav["h"], portal_id="origin", wait_sec=wait_sec, download=False)
        if page.get("error"):
            continue
        _take(page.get("links"), f"nav:{nav['t'][:16]}")
        # 栏目页分页：一手栏目的首页只列**最新**公告，目标公告常在后面几页
        # （实测温州银行采购信息首页列的是 page_id 37462…，目标 36919 在第 2~3 页）。
        # 只跟进「下一页 / 页码」类链接，最多 max_pages 页，够覆盖常见翻页深度。
        # 栏目页分页：一手栏目的首页只列**最新**公告，目标公告常在后面几页
        # （实测温州银行采购信息第 1 页是 2026-09-09 的，目标是 2026-08-28 的第 3 页往后）。
        # 用「发布日期」做早停：列表按时间倒序，某页**最新**的日期都已经早于目标日期时，
        # 说明已经翻过头了 → 停。这样翻页深度有界（不设死上限也不无限翻）。
        cur, cur_url, pages = page, nav["h"], 0
        while pages < max_pages:
            nxt = _next_page_link(cur.get("links") or [], cur_url)
            if not nxt:
                break
            pages += 1
            cur_url = nxt
            cur = fetch(cur_url, portal_id="origin", wait_sec=wait_sec, download=False)
            if cur.get("error"):
                break
            _take(cur.get("links"), f"nav:{nav['t'][:16]}+p{pages + 1}")
            if len(core) >= 6 and _norm_text(core) in _norm_text(cur.get("text") or ""):
                cands.append({"url": cur_url, "via": f"nav_page{pages + 1}", "score": 0.7,
                              "label": f"{nav['t'][:12]} p{pages + 1}"})
            if _passed_target_date(cur.get("text"), publish_date):
                log(f"翻页到第 {pages + 1} 页已早于目标日期，停止")
                break
        if len(core) >= 6 and _norm_text(core) in _norm_text(page.get("text") or ""):
            cands.append({"url": nav["h"], "via": "nav_direct", "score": 0.7,
                          "label": nav["t"][:60]})
    if cands:
        log(f"站点级下降候选 {len(cands)} 个，首个={cands[0]['label'][:34]}")
    # 去重 + 按分排序
    seen: set[str] = set()
    out: list[dict] = []
    for c in sorted(cands, key=lambda x: -x["score"]):
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        out.append(c)
    return out[:max_cands]


def trace_one(*, project_key: str | None = None, notice_id: int | None = None,
              origin_url: str | None = None,
              use_ai: bool = True, allow_discovery: bool = True, download: bool = True,
              min_title_score: float = 0.55, max_candidates: int = 4,
              search_web_fn=None, search_portal_fn=None, fetch_fn=None, descend_fn=None,
              db=None) -> dict:
    """追溯单个项目（project_key 或 notice_id 二选一）。永不抛，失败如实落 status/error。

    origin_url：人工已确认的源头链接（人在环）。给了就跳过「找源头」，只做取回 + 校验 + 落库 ——
    这是「AI 找不到、但人一眼就看到了」时把结果沉淀进库的正规通道。
    """
    from crawl import origin_hints
    from crawl.origin_portals import (
        classify_domain, detail_url_for, match_portal, portal_wait, search_portal,
    )

    t0 = time.time()
    rec: dict = {
        "projectKey": project_key, "projectName": None, "noticeIds": [], "seedNoticeId": None,
        "sourceIsOrigin": False, "originLevel": "unknown", "portalId": None, "portalName": None,
        "portalHome": None, "searchUrl": None, "detailUrl": None, "matchScore": 0.0,
        "confidence": 0.0, "status": "not_found", "method": None, "hints": {},
        "candidates": [], "body": {"chars": 0, "path": None}, "attachments": [],
        "notes": [], "error": None, "elapsedMs": 0,
    }
    rows: list[dict] = []
    try:
        if notice_id and not project_key:
            seed_row = load_notice(int(notice_id), db=db)
            if not seed_row:
                rec["status"] = "not_found"
                rec["error"] = "notice_not_found"
                return rec
            project_key = seed_row.get("project_key")
            rows = load_group(project_key, db=db) if project_key else [seed_row]
        elif project_key:
            rows = load_group(project_key, db=db)
        if not rows:
            rec["status"] = "not_found"
            rec["error"] = "no_rows"
            return rec

        seed = pick_seed(rows)
        rec["seedNoticeId"] = seed.get("id")
        rec["noticeIds"] = [r.get("id") for r in rows]
        rec["projectName"] = seed.get("title")

        # ---- ① 现源是否已是源头 ----
        # 判据是「采集时这条公告**从哪来**」（detail_url），不能用 original_url：
        # original_url 可能是上一轮追溯自己写进去的，用它会把「已追溯」误判成「采集源即源头」而空转。
        seed_url = seed.get("detail_url") or seed.get("original_url") or ""
        seed_level = classify_domain(seed_url)
        if seed_level in ("head", "gov"):
            rec.update(sourceIsOrigin=True, originLevel=seed_level, detailUrl=seed_url,
                       status="ok", method="source_is_origin", confidence=0.9)
            rec["notes"].append(f"现源域名定性={seed_level}，判定自身即源头")
            return _finish(rec, t0)

        # ---- ② 锚点抽取（本行 → 兄弟行汇聚） ----
        # 注意顺序：①b 库内通道必须排在锚点抽取**之后**（它要用 hints 做平台匹配；
        # 实测把它写在前面会 UnboundLocalError: hints referenced before assignment）。
        body = _body_of(seed)
        hints = origin_hints.extract(body, seed.get("title") or "", use_ai=use_ai)
        rec["hints"] = hints
        if not body:
            rec["notes"].append("组内无可用正文：仅凭标题推导主体锚点")
        if not (hints.get("buyer") and hints.get("projectCode")):
            pooled, sib_n = 0, 0
            for s in sibling_rows(seed, db=db):
                sib_n += 1
                h2 = origin_hints.rule_hints(_body_of(s) or s.get("title") or "", s.get("title") or "")
                hints = origin_hints.fill_missing(hints, h2)
                pooled += 1
                if hints.get("buyer") and hints.get("projectCode"):
                    break
            if pooled:
                rec["hints"] = hints
                rec["notes"].append(f"兄弟公告补锚点：扫描 {sib_n} 条，命中 buyer={bool(hints.get('buyer'))}")

        # ---- ①b 库内通道：源头可能已经在我们自己采的 gov/法定平台行里（零检索成本） ----
        lib = library_origin(seed, db=db) if not (origin_url or "").startswith("http") else None
        lib_url = None
        if lib and lib.get("source_id") != seed.get("source_id"):
            lib_url = lib.get("detail_url") or lib.get("official_url")
            rec.update(originLevel=classify_domain(lib_url), method="in_library",
                       matchScore=lib.get("_score") or 0.0, sourceIsOrigin=False)
            from crawl.origin_portals import match_portal as _mp

            p2 = _mp(seed.get("title") or "", {**hints, "urls": [lib_url]})
            if p2:
                rec.update(portalId=p2.get("id"), portalName=p2.get("name"), portalHome=p2.get("home"))
            rec["notes"].append(
                f"库内通道命中：本库已有 {lib.get('source_id')} 行（{str(lib.get('title'))[:40]}）"
                "属法定/自有发布平台，零检索成本")

        # ---- ③ 找源头 ----
        portal = match_portal(seed.get("title") or "", hints)
        detail_url = (origin_url if (origin_url or "").startswith("http")
                      else lib_url if (lib_url or "").startswith("http") else None)
        if detail_url and (origin_url or "").startswith("http"):
            rec["method"] = "manual_url"
            rec["originLevel"] = classify_domain(detail_url)
            if not portal:
                portal = match_portal(seed.get("title") or "", {**hints, "urls": [detail_url]})
            if portal:
                rec.update(portalId=portal.get("id"), portalName=portal.get("name"),
                           portalHome=portal.get("home"))
            rec["notes"].append("源头链接由人工提供（人在环），跳过自动发现")
        if not detail_url and portal:
            rec.update(portalId=portal.get("id"), portalName=portal.get("name"),
                       portalHome=portal.get("home"), originLevel=portal.get("level") or "platform")
            if portal.get("status") == "down":
                rec["status"] = "portal_down"
                rec["method"] = "portal_registry"
                rec["error"] = "portal_registered_down"
                rec["notes"].append(portal.get("note") or "平台登记为不可用")
                return _finish(rec, t0)
            from crawl.stage import project_core

            # 站内检索词：**项目核心名优先**，其次项目编号。
            # 为什么不是编号优先：绝大多数源头平台的检索框是「按标题检索」，项目编号
            # （HNFZ2026-09-2-00396）不在标题里 → 直接 0 条（实测踩过）；核心名才稳。
            # 编号留作第二选择，用于标题被改写过的情况。两个都试，命中即停（有界）。
            core_kw = project_core(seed.get("title") or "")[:20]
            kws: list[str] = []
            for k in (core_kw, hints.get("projectCode"), hints.get("buyer")):
                k = str(k or "").strip()
                if k and k not in kws:
                    kws.append(k)
            sfn = search_portal_fn or search_portal
            best, best_sc, kw_used, rows_found = None, 0.0, None, []
            for kw in kws[:2]:
                rows_found = sfn(portal, kw) or []
                b, bsc = None, 0.0
                for r in rows_found:
                    sc = title_score(seed.get("title") or "", r.get("title") or "")
                    if sc > bsc:
                        b, bsc = r, sc
                if b and bsc >= min_title_score:
                    best, best_sc, kw_used = b, bsc, kw
                    break
                if bsc > best_sc:
                    best, best_sc, kw_used = b, bsc, kw
            rec["searchUrl"] = ((portal.get("search") or {}).get("url") or "").replace(
                "{kw}", kw_used or (kws[0] if kws else ""))
            if best and best_sc >= min_title_score:
                detail_url = detail_url_for(portal, best)
                rec["matchScore"] = round(best_sc, 3)
                rec["method"] = "portal_registry"
                rec["notes"].append(f"平台站内检索命中（词={kw_used}）：{best.get('title')}")
            else:
                rec["notes"].append(
                    f"平台站内检索无匹配（试 {len(kws[:2])} 个词，候选 {len(rows_found)} 条，"
                    f"最高 {round(best_sc, 3)}）")

        if not detail_url and allow_discovery:
            queries = origin_hints.search_queries(hints, seed.get("title") or "", max_queries=5)
            sfn = search_web_fn
            if sfn is None:
                from crawl.origin_portals import search_web

                sfn = search_web
            results: list[dict] = []
            seen_urls: set[str] = set()
            used_queries: list[str] = []
            for q in queries:
                # 不做早停：实测早停会造成「一个疑似 gov 候选就掐掉后面更有效的词」
                # （相城实验小学只跑了项目编号那一个词就停，真正命中的政府采购词没跑）。
                # 改为固定跑前 3 个词（顺序已按实测命中率排：{主体} 采购公告 排第一）；
                # 候选预筛改走 HTTP 后成本已经很低，不值得用召回换这点时间。
                if len(used_queries) >= 3:
                    break
                batch = sfn(q) or []
                used_queries.append(q)
                for r in batch:
                    u = str(r.get("url") or "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        results.append(r)
            rec["notes"].append(f"外部检索词 {len(used_queries)}/{len(queries)}：{' | '.join(used_queries)}")
            from crawl.origin_portals import load_registry

            cands = _candidate_filter(results, registry=load_registry())
            rec["candidates"] = [{k: c.get(k) for k in ("title", "url", "domain", "level", "score")}
                                 for c in cands[:max_candidates]]
            if not rec.get("method"):
                rec["method"] = "web_search"
            ff = fetch_fn or _default_fetch
            tried = 0
            descend_budget = 4
            _descend_fn = descend_fn or descend
            for c in cands[:max_candidates]:
                tried += 1
                got = _fetch_and_verify(c["url"], title=seed.get("title") or "", hints=hints,
                                        publish_date=seed.get("publish_date"),
                                        portal_id=(portal or {}).get("id") or "origin",
                                        wait_sec=portal_wait(portal or {}, "detail", 10.0),
                                        download=download, min_score=min_title_score,
                                        fetch_fn=ff)
                c["reject"] = got.get("error")
                c["score"] = round(float(got.get("score") or c.get("score") or 0), 3)
                if (not got.get("ok") and descend_budget > 0
                        and (_is_site_root(c["url"]) or got.get("error") in
                             ("no_project_anchor", "date_mismatch"))):
                    # 站点级下降：候选若是站点/栏目首页，往下找一层（返回候选列表，逐个验证）
                    descend_budget -= 1
                    d_list = _descend_fn(c["url"], title=seed.get("title") or "", hints=hints,
                                         wait_sec=portal_wait(portal or {}, "detail", 6.0),
                                         download=download, fetch_fn=ff,
                                         publish_date=seed.get("publish_date"),
                                         log=lambda m: rec["notes"].append(m)) or []
                    picked = None
                    rejects = []
                    for d in d_list[:6]:
                        got2 = _fetch_and_verify(d["url"], title=seed.get("title") or "", hints=hints,
                                                 publish_date=seed.get("publish_date"),
                                                 portal_id=(portal or {}).get("id") or "origin",
                                                 wait_sec=portal_wait(portal or {}, "detail", 6.0),
                                                 download=download, min_score=min_title_score,
                                                 fetch_fn=ff)
                        if got2.get("ok"):
                            picked = (d, got2)
                            break
                        rejects.append(f"{d['via']}={got2.get('error')}")
                    if picked:
                        d, got2 = picked
                        detail_url = d["url"]
                        rec["matchScore"] = got2.get("score") or 0.0
                        rec["_trust"] = got2.get("trust") or "low"
                        if not rec.get("originLevel") or rec["originLevel"] == "unknown":
                            rec["originLevel"] = got2.get("level") or c["level"]
                        rec["notes"].append(
                            f"站点级下降命中（{d['via']}）：{c['domain']} → {d['url'][:80]}"
                            f"（一手性={rec['_trust']}）")
                        got = got2
                        c["reject"] = None
                    else:
                        c["reject"] = (f"{got.get('error')};descend:"
                                       + ("/".join(rejects) if rejects else "no_candidate"))
                        rec["notes"].append(f"站点级下降未命中：{c['domain']}（{c.get('reject')}）")
                if got.get("ok"):
                    detail_url = c["url"]
                    rec["matchScore"] = got.get("score") or 0.0
                    rec["_trust"] = got.get("trust") or "low"
                    rec["_selfMail"] = got.get("selfMail") or []
                    if not rec.get("originLevel") or rec["originLevel"] == "unknown":
                        rec["originLevel"] = got.get("level") or c["level"]
                    rec["notes"].append(
                        f"外部检索命中源头：{c['domain']}（{tried} 次尝试内，一手性={rec['_trust']}）")
                    break
            if not detail_url:
                rec["notes"].append(
                    f"外部检索候选 {len(cands)} 个（试 {tried} 个）均未通过源头校验："
                    + "；".join(f"{c['domain']}={c.get('reject')}" for c in cands[:tried]))
            rec["candidates"] = [{k: c.get(k) for k in ("title", "url", "domain", "level", "score", "reject")}
                                 for c in cands[:max_candidates]]

        if not detail_url:
            rec["status"] = "not_found" if rec["candidates"] or portal else "no_hint"
            rec["error"] = rec.get("error") or "origin_not_located"
            return _finish(rec, t0)

        # ---- 取回一手正文 + 附件 ----
        rec["detailUrl"] = detail_url
        if not rec.get("originLevel") or rec["originLevel"] == "unknown":
            rec["originLevel"] = classify_domain(detail_url)
        ff = fetch_fn or _default_fetch
        page = ff(detail_url, portal_id=(portal or {}).get("id") or "origin",
                  wait_sec=portal_wait(portal or {}, "detail", 10.0), download=download)
        if page.get("error"):
            # 库内行已有一手正文时，抓取失败也能交付（例如源头站临时 502）
            lib_body = _body_of(lib) if lib else ""
            if lib_body:
                rec["_summary"] = lib_body[:5000]
                rec["body"] = {"chars": len(rec["_summary"]), "path": lib.get("tenderfile_path")}
                rec["_tenderfilePath"] = lib.get("tenderfile_path")
                rec["status"] = "ok"
                rec["confidence"] = 0.7
                rec["notes"].append(f"源头站抓取失败（{page['error']}），回退到库内行已有正文")
                return _finish(rec, t0)
            rec["status"] = "fetch_failed"
            rec["error"] = page["error"]
            return _finish(rec, t0)
        summary = page.get("summary") or ""
        atts = page.get("attachments") or []
        if atts:
            rec["attachments"] = [{"path": a.get("path"), "sourceUrl": a.get("sourceUrl"),
                                   "format": a.get("format")} for a in atts]
            # 附件（原始采购文件/签章版公告）正文优先于页面摘要：
            # 页面摘要只是网页壳（导航+字段），附件才是真正的一手招标文件（含限价/资格/评分）。
            if atts[0].get("text"):
                summary = atts[0]["text"][:2000]
        rec["body"] = {"chars": len(summary), "path": None}
        rec["_summary"] = summary
        rec["_attachmentText"] = (atts[0].get("text") if atts else "") or ""
        rec["_tenderfilePath"] = (atts[0].get("path") if atts else None)
        if rec["_tenderfilePath"]:
            rec["body"]["path"] = rec["_tenderfilePath"]

        # 人工提供的链接也要过一道锚点校验：人工可能给错（给成同项目的另一年/另一个标段）
        from crawl.stage import project_core as _pc

        _core = _pc(seed.get("title") or "")
        anchor_ok = bool(atts or (len(_core) >= 6 and _core in (page.get("text") or "")))
        if rec.get("method") == "manual_url" and not anchor_ok:
            rec["notes"].append("人工提供的源头页未命中项目核心名，标为 partial 待人工复核")

        # 置信度：命中平台登记 + 标题高 → 高；仅外部检索命中 → 中；人工给链接 → 中
        base = {"manual_url": 0.7}.get(rec.get("method"), 0.85 if rec.get("portalId") else 0.65)
        rec["confidence"] = round(min(0.98, base * 0.6 + rec.get("matchScore", 0) * 0.4
                                      + (0.1 if rec["body"]["chars"] >= 300 else 0)), 3)
        rec["status"] = "ok" if (rec["body"]["chars"] >= 200 or atts) else "partial"
        if rec.get("method") == "manual_url" and not anchor_ok:
            rec["status"] = "partial"
            rec["error"] = rec.get("error") or "no_project_anchor"
        # 未知域且无一手证据（自域邮箱/登记平台/gov）→ 只敢标 partial：
        # 实测 www.diuta.com 这类「不在名单里的镜像详情页」正文完整、标题也对得上，
        # 靠内容判据拦不住，只能靠「它是不是采购人自己发的」来定级，宁可交人工复核。
        if rec.get("_trust") == "low" and rec["status"] == "ok":
            rec["status"] = "partial"
            rec["notes"].append("候选域未登记且页面无自域邮箱等一手证据，标 partial 待人工确认")
            rec["confidence"] = min(rec.get("confidence") or 0.5, 0.5)
        return _finish(rec, t0)
    except Exception as e:  # noqa: BLE001 —— 单条追溯异常绝不炸批次
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}:{str(e)[:180]}"
        return _finish(rec, t0)


def _finish(rec: dict, t0: float) -> dict:
    """收尾：只补耗时。`_` 前缀的字段是进程内载荷（正文/附件正文），由 public_record 在出 handoff 时剥掉。"""
    rec["elapsedMs"] = int((time.time() - t0) * 1000)
    return rec


def public_record(rec: dict) -> dict:
    """handoff/日志用：剥掉 `_` 开头的进程内大字段。"""
    return {k: v for k, v in (rec or {}).items() if not str(k).startswith("_")}


# ---------------------------------------------------------------- 落库 ---

def apply_record(rec: dict, *, db=None, overwrite_body: bool = True) -> dict:
    """追溯结果落库：origin_* 独立列 + （仅当更好时）summary/tenderfile_path + original_url/origin_source。

    返回 {"updated": n, "summaryWritten": n, "filesWritten": n}
    """
    from db import connect

    ids = [int(i) for i in (rec.get("noticeIds") or []) if i]
    if not ids:
        return {"updated": 0, "summaryWritten": 0, "filesWritten": 0}
    evidence = {
        "method": rec.get("method"), "hints": rec.get("hints"),
        "candidates": rec.get("candidates"), "notes": rec.get("notes"),
        "matchScore": rec.get("matchScore"),
    }
    conn = db or connect(autocommit=True)
    stats = {"updated": 0, "summaryWritten": 0, "filesWritten": 0}
    try:
        with conn.cursor() as cur:
            for nid in ids:
                sets = [
                    "origin_level=%s", "origin_portal=%s", "origin_detail_url=%s",
                    "origin_status=%s", "origin_confidence=%s", "origin_evidence=%s",
                    "origin_traced_at=NOW()",
                ]
                params = [
                    (rec.get("originLevel") or "unknown")[:16],
                    (rec.get("portalName") or rec.get("originLevel"))[:120],
                    (rec.get("detailUrl") or "")[:1000] or None,
                    (rec.get("status") or "not_found")[:32],
                    float(rec.get("confidence") or 0),
                    json.dumps(evidence, ensure_ascii=False),
                ]
                if rec.get("detailUrl"):
                    sets += ["original_url=%s", "origin_source=%s"]
                    params += [(rec.get("detailUrl") or "")[:1000],
                               (rec.get("portalName") or "")[:120] or None]
                if overwrite_body and rec.get("status") in ("ok", "partial"):
                    cur.execute("SELECT summary, tenderfile_path FROM notices WHERE id=%s", (nid,))
                    cur_row = cur.fetchone() or {}
                    summary = rec.get("_summary") or rec.get("_attachmentText")
                    # 拿到原始采购文件时无条件覆写正文：附件正文是一手依据（含限价/资格/评分），
                    # 比聚合站摘要（可能还是登录墙/列表页垃圾）严格更有价值。
                    if summary and (rec.get("_tenderfilePath") or _better_than(summary, cur_row.get("summary"))):
                        sets.append("summary=%s")
                        params.append(summary[:5000])
                        stats["summaryWritten"] += 1
                    tf_path = rec.get("_tenderfilePath")
                    if tf_path and not str(cur_row.get("tenderfile_path") or "").strip():
                        sets.append("tenderfile_path=%s")
                        params.append(str(tf_path)[:500])
                        stats["filesWritten"] += 1
                params.append(nid)
                cur.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=%s", tuple(params))
                stats["updated"] += 1
    finally:
        if db is None:
            conn.close()
    return stats


def _better_than(new: str, old: str | None) -> bool:
    """新正文是否严格更好：旧为空/乱码，或新正文长度 >= 旧正文 * 1.2。"""
    if not new:
        return False
    if not old or not str(old).strip():
        return True
    if garbled_ratio(old) > 0.02:
        return True
    return len(new) >= len(str(old)) * 1.2


def trace_batch(*, limit: int = 3, keywords: str | None = "绿植租摆|绿植租赁|植物租摆|植物租赁",
                minutes: int = 20, use_ai: bool = True, download: bool = True,
                apply: bool = False, only_keys: list[str] | None = None,
                trace_fn=None) -> dict:
    """按项目组批量追溯（有界：条数 + 墙钟）。返回批次统计（可序列化为 handoff）。"""
    t0 = time.time()
    fn = trace_fn or trace_one
    groups = ([{"project_key": k} for k in only_keys] if only_keys
              else pick_groups(limit=max(limit * 3, limit), only_keywords=keywords))
    stats = {"enabled": True, "candidates": len(groups), "processed": 0, "ok": 0,
             "partial": 0, "not_found": 0, "blocked": 0, "elapsedMs": 0,
             "stoppedReason": None, "records": [], "applied": 0}
    deadline = t0 + minutes * 60
    for g in groups:
        if stats["processed"] >= limit:
            stats["stoppedReason"] = "limit_total"
            break
        if time.time() >= deadline:
            stats["stoppedReason"] = "time_budget"
            break
        rec = fn(project_key=g["project_key"], use_ai=use_ai, download=download)
        stats["processed"] += 1
        if rec.get("status") == "ok":
            stats["ok"] += 1
        elif rec.get("status") == "partial":
            stats["partial"] += 1
        elif rec.get("status") in ("portal_down", "fetch_failed", "no_bridge"):
            stats["blocked"] += 1
        else:
            stats["not_found"] += 1
        if apply and rec.get("status"):
            # 所有终态都落库（含 not_found/portal_down）：它们是「这轮已经查过、结论是什么」的证据，
            # 不落库就会导致每轮重复查同一条、且人工看不到待接手清单。
            apply_record(rec)
            stats["applied"] += 1
        stats["records"].append(public_record(rec))
        _log(f"{rec.get('status'):<11} {str(rec.get('projectName'))[:40]} → "
             f"{rec.get('portalName') or '-'} {rec.get('detailUrl') or rec.get('error') or ''}")
    stats["elapsedMs"] = int((time.time() - t0) * 1000)
    if not stats["stoppedReason"]:
        stats["stoppedReason"] = "candidates_exhausted"
    return stats
