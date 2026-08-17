"""Solve first-stage __jsl_clearance_s cookie from HTTP 521 HTML (zhaobiao CDN)."""
from __future__ import annotations

import re
from http.cookiejar import Cookie


_COOKIE_ASSIGN_RE = re.compile(
    r"document\.cookie\s*=\s*(.+?);\s*location\.href",
    re.I | re.S,
)


def _split_top(expr: str, ops: tuple[str, ...]) -> tuple[str, str, str] | None:
    """Split expr by first top-level operator in ops (scan right-to-left for precedence helpers)."""
    depth = 0
    i = len(expr) - 1
    while i >= 0:
        ch = expr[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
        elif depth == 0:
            for op in ops:
                if i >= len(op) - 1 and expr[i - len(op) + 1 : i + 1] == op:
                    # avoid matching unary at start
                    left = expr[: i - len(op) + 1].strip()
                    right = expr[i + 1 :].strip()
                    if left == "" and op in {"+", "-"}:
                        break
                    # for multi-char already matched end
                    return left, op, right
        i -= 1
    return None


def _js_numish(expr: str):
    """Evaluate a tiny subset of JS number/string expressions used by jsl challenges."""
    e = (expr or "").strip()
    if not e:
        raise ValueError("empty")

    # string literal
    m = re.fullmatch(r"""(['"])(.*)\1""", e)
    if m:
        return m.group(2)

    # strip one layer of balanced outer parens
    while e.startswith("(") and e.endswith(")"):
        inner = e[1:-1].strip()
        depth = 0
        balanced = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
        if balanced and depth == 0:
            e = inner
            m = re.fullmatch(r"""(['"])(.*)\1""", e)
            if m:
                return m.group(2)
        else:
            break

    if re.fullmatch(r"-?\d+(?:\.\d+)?", e):
        return float(e) if "." in e else int(e)
    if re.fullmatch(r"\[\d+\]", e):
        return int(e[1:-1])

    # stringify concat: <expr>+'' 
    if e.endswith("+''") or e.endswith('+""'):
        v = _js_numish(e[:-3].strip())
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v)

    # unary / known atoms
    known = {
        "+!+[]": 1,
        "+!![]": 1,
        "+[]": 0,
        "+false": 0,
        "+true": 1,
        "-~[]": 1,
        "-~{}": 1,
        "-~false": 1,
        "-~true": 0,
        "-~0": 1,
        "~~''": 0,
        "~~[]": 0,
        "~~{}": 0,
        "[]": 0,
        "{}": 0,
        "false": 0,
        "true": 1,
        "''": 0,
        '""': 0,
    }
    if e in known:
        return known[e]
    if e.startswith("-~"):
        return int(_js_numish(e[2:])) + 1
    if e.startswith("~~"):
        v = _js_numish(e[2:])
        return int(v or 0)
    if e.startswith("+!") or e.startswith("+"):
        # +!+[] already in known; generic +x
        if e.startswith("+!"):
            return 1 if not _js_numish(e[2:]) else 0
        return _js_numish(e[1:])

    # JS 运算符优先级（从低到高）：| < ^ < <<,>> < +,- < *,/  （>> 比 + 低，故先拆 >>）
    for ops in (("|",), ("^",), ("<<", ">>"), ("+", "-"), ("*", "/")):
        sp = _split_top(e, ops)
        if not sp:
            continue
        left, op, right = sp
        a = _js_numish(left)
        b = _js_numish(right)
        if isinstance(a, str) and a.isdigit():
            a = int(a)
        if isinstance(b, str) and b.isdigit():
            b = int(b)
        if op == "|":
            return int(a) | int(b)
        if op == "^":
            return int(a) ^ int(b)
        if op == "<<":
            return int(a) << int(b)
        if op == ">>":
            return int(a) >> int(b)
        if op == "*":
            def to_num(x):
                if isinstance(x, str):
                    try:
                        return float(x) if "." in x else int(x)
                    except ValueError:
                        return float("nan")
                return x

            return to_num(a) * to_num(b)
        if op == "+":
            # JS: if either side is string/array, concatenate
            def as_js_str(x):
                if isinstance(x, str):
                    return x
                if isinstance(x, float) and x.is_integer():
                    return str(int(x))
                return str(x)

            # detect array operand in original sides
            left_is_arr = bool(re.fullmatch(r"\[\d+\]", left.strip()))
            right_is_arr = bool(re.fullmatch(r"\[\d+\]", right.strip()))
            if left_is_arr or right_is_arr or isinstance(a, str) or isinstance(b, str):
                # array toString in JS is join without brackets for single elem
                def arr_or_val(raw, val):
                    raw = raw.strip()
                    if re.fullmatch(r"\[\d+\]", raw):
                        return raw[1:-1]
                    return as_js_str(val)

                return arr_or_val(left, a) + arr_or_val(right, b)
            return a + b
        if op == "-":
            return a - b
        if op == "/":
            # JS divides after ToNumber
            def to_num(x):
                if isinstance(x, str):
                    try:
                        return float(x) if "." in x else int(x)
                    except ValueError:
                        return float("nan")
                return x

            return to_num(a) / to_num(b)

    raise ValueError(f"unsupported js atom: {expr}")


def _eval_cookie_concat(expr: str) -> str:
    """Evaluate ('a')+('b')+(1+2+'')... into final cookie assignment string."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
            if depth == 0:
                atom = "".join(buf)
                buf = []
                val = _js_numish(atom)
                parts.append(str(val))
        elif depth > 0:
            buf.append(ch)
    if buf:
        parts.append(str(_js_numish("".join(buf))))
    return "".join(parts)


def extract_clearance_cookie(html: str) -> str | None:
    """Return 'name=value' (no attrs) or None."""
    m = _COOKIE_ASSIGN_RE.search(html or "")
    if not m:
        return None
    try:
        assigned = _eval_cookie_concat(m.group(1).strip())
    except Exception:
        return None
    name_val = assigned.split(";", 1)[0].strip()
    if "=" not in name_val:
        return None
    return name_val


def apply_cookie_header_to_jar(cj, name_val: str, url: str) -> None:
    name, value = name_val.split("=", 1)
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    c = Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=host,
        domain_specified=bool(host),
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=urlparse(url).scheme == "https",
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None, "SameSite": "None"},
        rfc2109=False,
    )
    cj.set_cookie(c)


def try_solve_521(html: str, cj, url: str) -> bool:
    nv = extract_clearance_cookie(html)
    if not nv:
        return False
    apply_cookie_header_to_jar(cj, nv, url)
    return True
