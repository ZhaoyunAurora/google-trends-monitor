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


def _chats(token):
    if os.getenv("FEISHU_CHAT_ID"):
        return [os.getenv("FEISHU_CHAT_ID")]
    return [c["chat_id"] for c in _api("GET", "/im/v1/chats?page_size=50", token).get("items", [])]


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


def poll(state, log=print):
    """每轮抓取开始时调用一次。返回处理了几条反馈。"""
    if not enabled():
        return 0
    token = _token()
    since = state.get("inbox_since") or int(time.time()) - 6 * 3600
    done = set(state.get("inbox_done", []))
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%m-%d")
    n, newest = 0, since
    for chat in _chats(token):
        for m in _messages(token, chat, since):
            mid = m.get("message_id")
            newest = max(newest, int(m.get("create_time", "0")) // 1000)
            if mid in done or m.get("msg_type") != "text" or (m.get("sender") or {}).get("sender_type") == "app":
                continue
            done.add(mid)
            try:
                text = json.loads(m["body"]["content"]).get("text", "")
            except Exception:  # noqa: BLE001
                continue
            reply = handle(text, today)
            if reply:
                _reply(token, mid, reply)
                n += 1
    state["inbox_since"] = newest
    state["inbox_done"] = sorted(done)[-300:]
    log(f"[飞书反馈] 处理了 {n} 条")  # 公开日志里不打内容
    return n
