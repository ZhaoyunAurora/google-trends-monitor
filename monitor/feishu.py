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


# 及时提醒：每次抓取后，把「第一次出现」的新词 / 老词二次爆火推到群里
ALERT_KINDS = {"新词", "老词二次爆火"}
ALERT_TAGS = {"AI 工具/模型/玩法", "AI 相关（词根）", "工具站需求"}


def alert_new(state):
    sent = state.setdefault("notified", {})
    items = []
    for kw, r in state["reviewed"].items():
        if kw in sent or r.get("kind") not in ALERT_KINDS or r.get("tag") not in ALERT_TAGS:
            continue
        if r.get("status") == "已明显回落":
            continue
        items.append((kw, r))
    if not items:
        return
    items.sort(key=lambda x: -(x[1].get("gpts_ratio") or 0))
    lines = [f"【Trends 新词提醒】{len(items)} 个（全球，近 7 天）"]
    for kw, r in items[:15]:
        q = urllib.parse.urlencode({"date": "today 12-m", "q": kw})
        ratio = r.get("gpts_ratio")
        lines.append(
            f"\n· {kw}｜{r['kind']}｜{r.get('status') or '—'}｜vs GPTs {ratio if ratio is not None else '?'}×"
            f"\n  来源：{' › '.join(r.get('path', []))}"
            f"\n  https://trends.google.com/trends/explore?{q}")
    lines.append("\n能不能做看每天早上的 Claude 判断。")
    if send("\n".join(lines)):
        today = time.strftime("%Y-%m-%d")
        for kw, _ in items:
            sent[kw] = today
