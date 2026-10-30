"""读飞书群里发给机器人的反馈，写进私有仓库的 feedback.md，并在群里回一句。

需要一个飞书「企业自建应用」（开启机器人能力并拉进群），GitHub Secrets：
  FEISHU_APP_ID / FEISHU_APP_SECRET   应用凭证
  FEISHU_CHAT_ID                      可选；不填就读机器人所在的所有群
权限：im:message:readonly、im:message.group_msg（读群消息）、im:message:send_as_bot（回复）、im:chat:readonly（找群）

群里的写法（@ 机器人或不 @ 都行，一条消息可以写多行）：
  + pokesurvivor 做了站
  - dodgers game 体育不要
  root+ ai effect / root- writer
  撤销 dodgers game        删掉之前关于这个词的反馈
  反馈列表                  机器人回复当前全部反馈

复盘群（群名里带「复盘」的群，把同一个机器人拉进去就行；关键字可用 FEISHU_RETRO_KEYWORD 改）：
  随手发的碎片都原样存进 feedback_inbox.md，前面标「[复盘群]」。雷达的 Claude 从里面挑跟词 / 站有关的反馈，
  复盘仓库 work-retro 的 Claude 读全部碎片做当天复盘。
  发「claude复盘」= 让复盘 Claude 在下一个整点（北京时间 19–24 点）开始复盘。
"""
import datetime as dt
import json
import os
import re
import time

import requests

from . import rules

API = "https://open.feishu.cn/open-apis"
AT = re.compile(r"@_user_\d+|@_all")
RETRO_CMD = re.compile(r"^\s*claude\s*复盘\s*[:：,，。!！]?\s*", re.I)
TZ8 = dt.timezone(dt.timedelta(hours=8))


def enabled():
    return bool(os.getenv("FEISHU_APP_ID") and os.getenv("FEISHU_APP_SECRET"))


def _token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal", timeout=20,
                      json={"app_id": os.getenv("FEISHU_APP_ID"), "app_secret": os.getenv("FEISHU_APP_SECRET")})
    js = r.json()
    if js.get("code") != 0:
        raise RuntimeError(f"拿 token 失败 code={js.get('code')} {js.get('msg')}")
    return js["tenant_access_token"]


def _api(method, path, token, **kw):
    r = requests.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=20, **kw)
    js = r.json()
    if js.get("code") != 0:
        raise RuntimeError(f"{path.split('?')[0]} 失败 code={js.get('code')} {js.get('msg')}")
    return js.get("data") or {}


def _retro_keyword():
    return os.getenv("FEISHU_RETRO_KEYWORD", "").strip() or "复盘"


def _chats(token):
    """返回 [(chat_id, 是不是复盘群)]。设了 FEISHU_CHAT_ID 时只读它 + 群名带「复盘」的群。"""
    fixed = os.getenv("FEISHU_CHAT_ID", "").strip()
    try:
        items = _api("GET", "/im/v1/chats?page_size=50", token).get("items", [])
    except Exception:  # noqa: BLE001  列群失败时退回只读固定的群
        if fixed:
            return [(fixed, False)]
        raise
    kw = _retro_keyword()
    out = []
    for c in items:
        cid, retro = c.get("chat_id"), kw in (c.get("name") or "")
        if cid and (not fixed or cid == fixed or retro):
            out.append((cid, retro and cid != fixed))
    if fixed and all(cid != fixed for cid, _ in out):
        out.insert(0, (fixed, False))
    return out


def _text(m):
    """取出消息里的文字：普通文本，或富文本（post，多段落 / 带格式时飞书会发成这种）。"""
    try:
        body = json.loads(m["body"]["content"])
    except Exception:  # noqa: BLE001
        return ""
    if m.get("msg_type") == "text":
        return body.get("text", "")
    if m.get("msg_type") != "post":
        return ""
    if "content" not in body:  # 有的版本外面包一层语言：{"zh_cn": {...}}
        body = next((v for v in body.values() if isinstance(v, dict)), {})
    lines = [body.get("title") or ""]
    for para in body.get("content") or []:
        lines.append("".join(x.get("text") or x.get("href") or "" for x in para if isinstance(x, dict)))
    return "\n".join(x for x in lines if x.strip())


def _react(token, mid):
    """给消息点个表情表示记下了；没有表情权限就回一句话。"""
    try:
        _api("POST", f"/im/v1/messages/{mid}/reactions", token, json={"reaction_type": {"emoji_type": "OK"}})
    except Exception:  # noqa: BLE001
        _reply(token, mid, "✍️ 记下了")


def _append_inbox(line):
    p = rules.OUT_DIR / "feedback_inbox.md"
    old = p.read_text(encoding="utf-8") if p.exists() else (
        "# 飞书里收到的反馈（原话），Claude 每份报告会把 [ ] 的整理成 feedback.md 的规则，然后改成 [x]\n"
        "# 「[复盘群]」开头的是复盘群里的碎片：雷达只挑跟词 / 站有关的，复盘 Claude 读全部\n\n")
    if old and not old.endswith("\n"):
        old += "\n"
    p.write_text(old + line + "\n", encoding="utf-8")


def _messages(token, chat, start_sec):
    out, page = [], ""
    for _ in range(10):
        q = (f"/im/v1/messages?container_id_type=chat&container_id={chat}&start_time={start_sec}"
             f"&sort_type=ByCreateTimeAsc&page_size=50" + (f"&page_token={page}" if page else ""))
        d = _api("GET", q, token)
        out += d.get("items", [])
        if not d.get("has_more"):
            break
        page = d.get("page_token", "")
    return out


def _reply(token, mid, text):
    try:
        _api("POST", f"/im/v1/messages/{mid}/reply", token,
             json={"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)})
    except Exception:  # noqa: BLE001  回复失败不影响记录
        pass


def _path():
    return rules.OUT_DIR / "feedback.md"


def _read():
    p = _path()
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else ["# 我的反馈"]


def _write(lines):
    _path().write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    rules._FEEDBACK = None  # 让本次运行马上用上新反馈


def _active(lines):
    return [ln for ln in lines if rules.FEEDBACK_LINE.match(ln.strip().lstrip("*").strip())]


def handle(text, date):
    """处理一条消息，返回回复内容；不是反馈就返回 None。"""
    text = AT.sub(" ", text).strip()
    lines = _read()
    added, removed = [], []
    for raw in text.splitlines():
        ln = re.sub(r"\s+", " ", raw).strip()
        ln = re.sub(r"^＋", "+", re.sub(r"^[－—]", "-", ln))  # 全角符号
        if not ln:
            continue
        if ln in ("反馈列表", "列表", "list"):
            act = _active(lines)
            return "当前反馈（共 %d 条）：\n%s" % (len(act), "\n".join(act) or "（空）")
        m = re.match(r"^(撤销|删除|undo)\s*(.+)$", ln, re.I)
        if m:
            kw = m.group(2).strip().lower()
            keep = []
            for x in lines:
                fm = rules.FEEDBACK_LINE.match(x.strip())
                if fm and fm.group(2).strip().lower() == kw:
                    removed.append(x)
                else:
                    keep.append(x)
            lines = keep
            continue
        fm = rules.FEEDBACK_LINE.match(ln)
        if fm and fm.group(2).strip():
            op = fm.group(1).lower()
            # 统一成「符号 空格 词 两个空格 备注」
            entry = f"{op} {fm.group(2).strip().lower()}  {fm.group(3).strip()}".rstrip() + f"  （{date} 飞书）"
            lines.append(entry)
            added.append(entry)
    if not added and not removed:
        return None
    _write(lines)
    msg = []
    if added:
        msg.append("已记下：\n" + "\n".join(added))
    if removed:
        msg.append("已撤销：\n" + "\n".join(removed))
    msg.append("下一轮抓取（十几分钟内）开始生效，Claude 下一份报告也会按这个判断。")
    return "\n".join(msg)


def _retro_message(token, mid, text, body, stamp):
    """复盘群的一条消息：全部原样进 inbox（复盘 Claude 读全部），返回 1。"""
    cmd = RETRO_CMD.match(text)
    if cmd:
        rest = body[cmd.end():].strip(" /")
        _append_inbox(f"- [ ] {stamp} | [复盘群] 【claude复盘】{rest}".rstrip())
        _reply(token, mid, "收到 🫡 下一个检查点（北京时间每晚 19–24 点的整点）开始复盘，写好后发到这个群。"
                           "在那之前补充的碎片也会算进去。")
        return 1
    # 复盘群不按「+ 词 / - 词」固定格式解析：碎片常写成「- 修了登录 bug」这种列表，会被误当成「不要这个词」。
    # 全部交给 Claude 理解。
    _append_inbox(f"- [ ] {stamp} | [复盘群] {body}")
    _react(token, mid)
    return 1


def poll(state, log=print):
    """每轮抓取开始时调用一次。返回处理了几条反馈。"""
    if not enabled():
        return 0
    token = _token()
    since = state.get("inbox_since") or int(time.time()) - 6 * 3600
    done = set(state.get("inbox_done", []))
    today = dt.datetime.now(TZ8).strftime("%m-%d")
    n, newest = 0, since
    for chat, retro in _chats(token):
        for m in _messages(token, chat, since):
            mid = m.get("message_id")
            newest = max(newest, int(m.get("create_time", "0")) // 1000)
            if mid in done or m.get("msg_type") not in ("text", "post") or \
                    (m.get("sender") or {}).get("sender_type") == "app":
                continue
            done.add(mid)
            text = AT.sub(" ", _text(m)).strip()
            if not text:
                continue
            stamp = dt.datetime.fromtimestamp(int(m.get("create_time", "0")) // 1000, TZ8).strftime("%m-%d %H:%M")
            body = text.replace("\n", " / ")
            if retro:
                n += _retro_message(token, mid, text, body, stamp)
                continue
            reply = handle(text, today)
            if not reply:
                # 不是固定格式的话（大多数时候你会直接说人话）：存进 feedback_inbox.md，交给 Claude 下一份报告理解成规则
                _append_inbox(f"- [ ] {stamp} | [雷达群] {body}")
                reply = ("收到 👌 已转给 Claude：下一份判断报告（北京时间 1:20 / 7:20 / 13:20 / 19:20）"
                         "会把这条理解成筛词规则，并在报告开头告诉你它是怎么理解的。理解错了直接再发一条纠正就行。")
            _reply(token, mid, reply)
            n += 1
    state["inbox_since"] = newest
    state["inbox_done"] = sorted(done)[-300:]
    log(f"[飞书反馈] 处理了 {n} 条")  # 公开日志里不打内容
    return n
