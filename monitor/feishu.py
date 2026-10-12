"""飞书群机器人推送。没有设置 FEISHU_WEBHOOK 时什么也不做。"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request


def send(text):
    hook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not hook:
        return False
    msg = {"msg_type": "text", "content": {"text": text}}
    secret = os.getenv("FEISHU_SECRET", "").strip()
    if secret:
        ts = str(int(time.time()))
        sign = base64.b64encode(hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()
        msg.update(timestamp=ts, sign=sign)
    req = urllib.request.Request(hook, data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=20).read().decode()
        print("[飞书]", resp[:200])
        return json.loads(resp).get("code", 0) == 0
    except Exception as e:  # 推送失败不影响抓取
        print("[飞书] 推送失败:", e)
        return False


# 新词汇总：每 6 小时（北京时间 2、8、14、20 点之后的第一次运行）把这段时间的新词合并成一条推送。
# 平时只存结果，不打扰。
import datetime as _dt

ALERT_KINDS = {"新词", "老词二次爆火"}
ALERT_TAGS = {"AI 视频/图片", "AI 工具", "工具站", "小游戏", "AI 相关（词根）",
              "AI 工具/模型/玩法", "工具站需求"}  # 后两个是旧版标签
DIGEST_HOURS = 6
DIGEST_OFFSET = 2  # 时段从北京时间 2 点开始：2、8、14、20
BJ = _dt.timezone(_dt.timedelta(hours=8))


def _slot(now):
    bj = now.astimezone(BJ) - _dt.timedelta(hours=DIGEST_OFFSET)
    return bj.strftime("%Y-%m-%d") + f"-{bj.hour // DIGEST_HOURS}"


def trends_link(kw):
    q = urllib.parse.urlencode({"date": "today 1-m", "q": kw})
    return f"https://trends.google.com/trends/explore?{q}"


def digest(state, now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    slot = _slot(now)
    last_slot = state.get("digest_slot")
    if last_slot is None:  # 第一次运行：只记下时段，从现在开始累计
        state["digest_slot"], state["digest_at"] = slot, now.isoformat()
        return
    if slot == last_slot:
        return
    since = state.get("digest_at", "")
    sent = state.setdefault("notified", {})
    checked = [r for r in state["reviewed"].values() if r.get("reviewed_at", "") >= since]
    items = []
    for kw, r in state["reviewed"].items():
        if kw in sent or r.get("kind") not in ALERT_KINDS or r.get("tag") not in ALERT_TAGS:
            continue
        if r.get("status") == "已明显回落":
            continue
        items.append((kw, r))
    from .rules import TAG_PRIORITY
    items.sort(key=lambda x: (TAG_PRIORITY.get(x[1].get("tag"), 1), -(x[1].get("gpts_ratio") or 0)))

    start_bj = _dt.datetime.fromisoformat(since).astimezone(BJ) if since else now.astimezone(BJ)
    head = (f"【Trends 新词汇总】{start_bj:%m-%d %H:%M} ~ {now.astimezone(BJ):%m-%d %H:%M}（北京时间）\n"
            f"这段时间查了 {len(checked)} 个词，值得看的新词 {len(items)} 个（全球数据）")
    blocks = []
    for kw, r in items:
        ratio = r.get("gpts_ratio")
        blocks.append(
            f"· {kw}｜{r.get('tag', '')}｜{r['kind']}｜{r.get('status') or '—'}"
            f"\n  vs GPTs {ratio if ratio is not None else '?'}×"
            + (f"（约 {r['est_daily']} 次/天）" if r.get("est_daily") is not None else "")
            + (f"｜{r['burst_date'][5:]} 起来" if r.get("burst_date") else "")
            + (f"｜现在是峰值的 {r['now_pct']}%" if r.get("now_pct") is not None else "")
            + f"\n  来源：{' › '.join(r.get('path', []))}"
            f"\n  {trends_link(kw)}")
    tail = "能不能做，看每天北京时间 7:20 和 19:20 的 Claude 判断报告。"
    # 全部列出；飞书单条消息有大小限制，太长就拆成几条
    msgs, cur = [], head
    for b in blocks:
        if len((cur + "\n\n" + b).encode()) > 15000:
            msgs.append(cur)
            cur = "（续）"
        cur += "\n\n" + b
    msgs.append(cur + "\n\n" + tail)
    if len(msgs) > 1:
        msgs[0] = msgs[0].replace("（全球数据）", f"（全球数据，分 {len(msgs)} 条发送）", 1)
    ok = all([send(m) for m in msgs])
    if ok:
        today = now.astimezone(BJ).strftime("%Y-%m-%d")
        for kw, _ in items:
            sent[kw] = today
        state["digest_slot"], state["digest_at"] = slot, now.isoformat()
