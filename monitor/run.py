"""主流程（全部是全球数据）：
  第 0 层：每天把所有词根查一遍近 7 天「相关查询 - 搜索量上升」，飙升或涨幅 ≥ 500% 的进入第 1 层。
  第 1~4 层的每个词：
    1. 和 GPTs 一起看近 7 天，同时拿到它自己的近 7 天上升相关词（1 次查询，3 个请求）
       → GPTs 倍数、估算日搜索量、7 天在涨还是在落
    2. 不管它本身新不新，它的飙升 / ≥500% 相关词都进入下一层（最多 4 层）；相关词全是谜题答案 / 新闻等垃圾的，这条线剪掉
    3. 7 天量级够大（估算 ≥ 100 次/天）或 7 天在涨，再单独看 1 个月（2 个请求）
       → 新词 / 老词二次爆火 / 待观察 / 短时尖峰 / 老词，起来时间、峰值日、现在是峰值的百分之几
  跨天追踪：记录每个词第一次出现在上升列表的日期、出现过几天、连续几天。

环境变量：
  RUN_MINUTES       本次最多跑多少分钟（默认 20）
  REQUEST_INTERVAL  两次请求的基础间隔秒数（默认 25）
  CANDIDATE_MIN     上升幅度达到多少 % 才往下看（默认 300，「飙升」一律看）
  MAX_DEPTH         从词根往下挖几层（默认 3：词根 → 第 1 层 → 第 2 层 → 第 3 层）
  ROOT_SHARE        每次运行用多少比例的时间查词根，剩下的往下挖（默认 0.35）
  REVIEW_TTL_DAYS   查过的词几天内不重复查（默认 3）
  ROTATE_PER_RUN    每次运行最多查几个轮换词根（默认 15）
  ROTATE_DAYS       轮换词根隔几天查一次（默认 3）
"""
import datetime as dt
import json
import os
import time

from . import classify, feishu, report, rules
from .trends import RateLimited, Trends

DATA = rules.OUT_DIR / "data"
REF = "gpts"  # 参照词，和手工对比时用的 GPTs 一致
REF_DAILY = int(os.getenv("REF_DAILY", "5000"))  # GPTs 每天大约多少次搜索，用来估算日搜索量
MONTH_MIN = int(os.getenv("MONTH_MIN", "100"))  # 7 天估算日搜达到多少才看 1 个月


def now():
    return dt.datetime.now(dt.timezone.utc)


def today():
    return now().date().isoformat()


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


QUIET = os.getenv("QUIET") == "1"  # 公开仓库的运行日志谁都能看，带关键词的行不打印


def log(msg, private=False):
    if private and QUIET:
        return
    print(f"{now():%H:%M:%S} {msg}", flush=True)


class Runner:
    def __init__(self, client=None):
        self.minutes = float(os.getenv("RUN_MINUTES", "20"))
        self.cand_min = int(os.getenv("CANDIDATE_MIN", "500"))
        self.max_depth = int(os.getenv("MAX_DEPTH", "4"))
        self.root_share = float(os.getenv("ROOT_SHARE", "0.35"))
        self.ttl = int(os.getenv("REVIEW_TTL_DAYS", "3"))
        self.rotate_n = int(os.getenv("ROTATE_PER_RUN", "15"))
        self.client = client or Trends(interval=float(os.getenv("REQUEST_INTERVAL", "25")), log=log)
        self.deadline = time.time() + self.minutes * 60 - 90
        if hasattr(self.client, "deadline"):
            self.client.deadline = self.deadline
        self.state_path = DATA / "state.json"
        self.state = load_json(self.state_path, {"roots": {}, "reviewed": {}, "pending": {}})
        self.day_path = DATA / "daily" / f"{today()}.json"
        self.day = load_json(self.day_path, {"date": today(), "rising": {}, "expanded": {}, "candidates": {},
                                             "filtered": {}, "runs": []})
        self.day.setdefault("expanded", {})
        self.root_set = set()
        self.root_words = set()
        self.rotate_days = int(os.getenv("ROTATE_DAYS", "3"))
        self.skip = set()  # 本次运行请求失败的词，下次再试

    # ---------- 收集飙升词 ----------
    def take_rising(self, parent, items, path, depth):
        """把某个词（词根或上一层的词）的飙升相关词放进待查队列。返回进队列的个数。"""
        hits = 0
        for it in items:
            if not (it["breakout"] or it["value"] >= self.cand_min):
                continue
            kw = it["query"]
            if kw == parent or kw in self.root_set or kw in path:
                continue
            reason = rules.filter_reason(kw)
            if reason:
                self.day["filtered"][kw] = reason
                continue
            hits += 1
            self.track(kw, it)
            c = self.day["candidates"].setdefault(
                kw, {"roots": [], "value": 0, "formatted": "", "path": path + [parent], "depth": depth})
            root = path[0] if path else parent
            if root not in c["roots"]:
                c["roots"].append(root)
            if depth < c.get("depth", depth):
                c["depth"], c["path"] = depth, path + [parent]
            if it["breakout"] or it["value"] > c["value"]:
                c["value"] = 99999 if it["breakout"] else it["value"]
                c["formatted"] = it["formatted"]
            if not self.fresh(kw) and kw not in self.state["pending"]:
                self.state["pending"][kw] = {"roots": c["roots"], "value": c["value"],
                                             "path": c["path"], "depth": c["depth"], "added": today()}
        return hits

    def track(self, kw, it):
        """跨天追踪：这个词哪天第一次出现在上升列表、出现过哪些天、最高涨幅。"""
        t = self.state.setdefault("seen", {}).setdefault(kw, {"first": today(), "days": [], "max": 0})
        if today() not in t["days"]:
            t["days"] = (t["days"] + [today()])[-30:]
        v = 99999 if it["breakout"] else it["value"]
        if v > t["max"]:
            t["max"], t["max_fmt"] = v, it["formatted"]

    def seen_info(self, kw):
        t = self.state.get("seen", {}).get(kw)
        if not t:
            return {}
        days = sorted(t["days"])
        streak = 1
        for a, b in zip(days[::-1], days[-2::-1]):
            if (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days == 1:
                streak += 1
            else:
                break
        if days and days[-1] < (now().date() - dt.timedelta(days=1)).isoformat():
            streak = 0  # 最近两天没再出现
        return {"seen_first": t["first"], "seen_days": len(days), "streak": streak}

    GENERIC = set("""ai video videos image images photo photos pic picture song songs music version app apps free online
        generator maker editor tool tools new trend trends prompt prompts the a an of to for and in on with how what is
        download edit edits effect effects filter style art create make model v1 v2 v3 2 3 pro vs""".split())

    def core_words(self, kw):
        """去掉通用词和词根里的词，剩下真正区分这个词的部分。"""
        return {w for w in kw.split() if w not in self.GENERIC and w not in self.root_words and len(w) > 2}

    def family_words(self):
        """最近复核过的词的核心词。新词和它们有交集，就算同一个话题的变体，排到后面。"""
        words = set()
        cutoff = (now() - dt.timedelta(days=2)).isoformat()
        for k, r in self.state["reviewed"].items():
            if r.get("reviewed_at", "") >= cutoff:
                words |= self.core_words(k)
        return words

    # ---------- 阶段 1：查词根 ----------
    def pick_roots(self):
        daily, rotate = rules.load_roots()
        self.root_set = set(daily) | set(rotate)
        self.root_words = {w for r in self.root_set for w in r.split()}
        last = self.state["roots"]
        todo = [r for r in daily if not last.get(r, "").startswith(today())]
        # 轮换词根每隔 ROTATE_DAYS 天查一次，把请求省给往下挖
        cutoff = (now() - dt.timedelta(days=self.rotate_days)).isoformat()
        rotate_sorted = sorted(rotate, key=lambda r: last.get(r, ""))
        todo += [r for r in rotate_sorted if last.get(r, "") < cutoff][: self.rotate_n]
        return todo

    def scan_roots(self, budget_until):
        for root in self.pick_roots():
            if time.time() > budget_until:
                log("词根阶段时间用完，剩下的下次查")
                break
            items = self.client.related_rising(root)
            if items is None:
                continue
            self.state["roots"][root] = now().isoformat()
            self.day["rising"][root] = items
            hits = self.take_rising(root, items, [], 1)
            log(f"[词根] {root}: 飙升/上升词 {len(items)} 个，进队列 {hits} 个")

    def fresh(self, kw):
        r = self.state["reviewed"].get(kw)
        if not r:
            return False
        reviewed = dt.datetime.fromisoformat(r["reviewed_at"])
        if r.get("kind") == "待观察":  # 刚冒头的词，隔几个小时再看一次形状
            return now() - reviewed < dt.timedelta(hours=5)
        return (now().date() - reviewed.date()).days < self.ttl

    # ---------- 阶段 2：逐个查词，并往下挖 ----------
    def review_one(self, kw):
        """返回 (结果, 这个词自己的上升相关词)。"""
        # 1. 和 GPTs 一起看近 7 天 + 它自己的近 7 天上升相关词（3 个请求）
        p = self.client.probe(kw, REF)
        if p is None:
            return None, None
        children = p.get("rising") or []
        res = classify.classify_7d(p["series"]) if p.get("series") else {}
        res["reviewed_at"] = now().isoformat()
        ratio = res.get("gpts_ratio")
        if ratio:
            est = ratio * REF_DAILY
            res["est_daily"] = int(round(est, -1)) if est >= 100 else int(round(est))

        # 2. 相关词全是谜题答案 / 新闻 / 体育之类：这条线剪掉
        junk = classify.junk_from_children(children, rules.filter_reason)
        if junk:
            res.update(kind="已过滤", filter=junk,
                       note=f"它的上升相关词多是「{junk}」类：" + "、".join(c["query"] for c in children[:3]))
            return res, []

        # 3. 7 天量级够大或者在涨，再单独看 1 个月（2 个请求）
        if (res.get("est_daily") or 0) >= MONTH_MIN or (res.get("rising_7d") and ratio):
            d = self.client.timeseries([kw], "today 1-m")
            if d:
                dates, k = classify.complete(d)
                m = classify.classify_month(dates, k, classify.partial_tail(d))
                res.update(m)
        if "kind" not in res:
            res["kind"] = "量太小" if not ratio or (res.get("est_daily") or 0) < MONTH_MIN else "数据不足"
            if ratio == 0:
                res["note"] = f"热度不到 GPTs 的 1%（每天少于约 {REF_DAILY // 100} 次）"
        return res, children

    def queue_order(self):
        family = self.family_words()

        seen = self.state.get("seen", {})

        def key(kv):
            kw, meta = kv
            # 快车道：连续 2 天以上都出现在上升列表里的词，不管方向先查（例如 pokemon › pokesurvivor 连续上榜却一直排队）
            # 只给有价值的方向（AI 视频/图片、AI 工具、工具站、小游戏）开快车道，避免新闻、体育连续上榜占位
            days = len(seen.get(kw, {}).get("days", []))
            # 方向优先级：AI 视频/图片 > AI 工具 > 工具站 > 小游戏 > ……；同方向里，同一话题的变体靠后、层级浅和涨幅大的靠前
            pri = rules.TAG_PRIORITY.get(rules.tag(kw, meta.get("path", [])), 5)
            lane = 0 if days >= 2 and pri <= 3 else 1
            variant = 1 if self.core_words(kw) & family else 0
            return (lane, -days, pri, variant, meta.get("depth", 1), -meta.get("value", 0))
        return sorted(((k, m) for k, m in self.state["pending"].items() if k not in self.skip), key=key)

    def review_pending(self):
        done = 0
        while True:
            queue = self.queue_order()
            if not queue:
                break
            if time.time() > self.deadline:
                log(f"时间用完，队列里还剩 {len(self.state['pending'])} 个词，下次继续")
                break
            # AI 方向优先，但每查 3 个词留 1 个名额给工具站 / 小游戏 / 其他方向，避免它们一直排不上
            kw, meta = queue[0]
            if done % 3 == 2:
                other = [kv for kv in queue
                         if rules.TAG_PRIORITY.get(rules.tag(kv[0], kv[1].get("path", [])), 5) >= 2]
                if other:
                    kw, meta = other[0]
            res, children = self.review_one(kw)
            if res is None:
                self.skip.add(kw)
                meta["fails"] = meta.get("fails", 0) + 1
                if meta["fails"] >= 3:
                    self.state["pending"].pop(kw, None)
                continue
            self.state["pending"].pop(kw, None)
            res["roots"] = meta.get("roots", [])
            res["path"] = meta.get("path", [])
            res["depth"] = meta.get("depth", 1)
            res["tag"] = rules.tag(kw, res["path"])
            res.update(self.seen_info(kw))
            self.state["reviewed"][kw] = res
            done += 1
            if res["kind"] == "已过滤":
                self.day["filtered"][kw] = res["filter"] + "（看相关词判断）"
                log(f"[过滤] {kw}: {res['note']}", private=True)
                continue
            log(f"[复核] {'  ' * (res['depth'] - 1)}{kw}: {res['kind']} {res.get('status', '')} "
                f"GPTs×{res.get('gpts_ratio')}", private=True)
            # 往下挖：不管这个词本身新不新，它的上升相关词都进入下一层
            if children:
                self.day["expanded"][kw] = children
            if children and res["depth"] < self.max_depth:
                n = self.take_rising(kw, children, res["path"], res["depth"] + 1)
                if n:
                    log(f"        └ 往下一层：{n} 个新飙升词进队列", private=True)
        return done

    # ---------- 主入口 ----------
    def run(self):
        start = time.time()
        stopped = ""
        try:
            self.scan_roots(budget_until=start + (self.deadline - start) * self.root_share)
            self.review_pending()
        except RateLimited:
            stopped = "连续 429，提前收工"
            log(stopped)
        finally:
            self.cleanup()
            feishu.digest(self.state)
            self.day["runs"].append({
                "at": now().isoformat(timespec="minutes"),
                "requests": self.client.requests,
                "http_429": self.client.count_429,
                "stopped": stopped,
                "queue_left": len(self.state["pending"]),
            })
            save_json(self.state_path, self.state)
            save_json(self.day_path, self.day)
            report.build(self.day, self.state)
        kinds = {}
        for r in self.state["reviewed"].values():
            kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
        log(f"累计复核结果：{kinds}")
        log(f"完成：请求 {self.client.requests} 次，429 {self.client.count_429} 次，队列剩 {len(self.state['pending'])}")

    def cleanup(self):
        """复核缓存只留 30 天；队列只保留 7 天内发现的词，避免无限变长。"""
        cutoff = (now().date() - dt.timedelta(days=30)).isoformat()
        self.state["reviewed"] = {k: v for k, v in self.state["reviewed"].items()
                                  if v.get("reviewed_at", "") >= cutoff}
        self.state["notified"] = {k: v for k, v in self.state.get("notified", {}).items() if v >= cutoff}
        # 超过 7 天还没轮到的词丢掉
        old = (now().date() - dt.timedelta(days=7)).isoformat()
        self.state["pending"] = {k: m for k, m in self.state["pending"].items()
                                 if m.get("added", today()) >= old}
        seen_cut = (now().date() - dt.timedelta(days=30)).isoformat()
        self.state["seen"] = {k: t for k, t in self.state.get("seen", {}).items()
                              if t["days"] and t["days"][-1] >= seen_cut}


if __name__ == "__main__":
    Runner().run()
