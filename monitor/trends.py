"""Google Trends 抓取客户端：慢速、带 cookie、遇到 429 退避重试。"""
import datetime as dt
import json
import random
import time
import urllib.parse

import requests

BASE = "https://trends.google.com/trends/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


class RateLimited(Exception):
    """连续 429 太多次，本次运行应提前收工。"""


class Trends:
    def __init__(self, interval=25, max_consecutive_429=4, log=None):
        self.interval = interval
        self.max_429 = max_consecutive_429
        self.log = log or (lambda msg, private=False: print(msg))
        self.requests = 0
        self.count_429 = 0
        self._consec_429 = 0
        self._last = 0.0
        self.deadline = None      # 由 Runner 设置；冷却等待不会超过这个时间
        self.cooldowns = 0
        self.max_cooldowns = 3
        self.s = None
        self._new_session()

    # ---------- 底层 ----------
    def _new_session(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            self.s.get("https://trends.google.com/trends/", timeout=30)  # 只为拿 cookie；所有数据请求都是全球（geo 为空）
        except requests.RequestException as e:
            self.log(f"[cookie] 失败: {e}")

    def _throttle(self):
        wait = self.interval + random.uniform(0, 8) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)

    def _get(self, url):
        for attempt in range(3):
            self._throttle()
            try:
                r = self.s.get(url, timeout=40)
            except requests.RequestException as e:
                self.log(f"[net] {e}", private=True)
                self._last = time.time()
                continue
            self._last = time.time()
            self.requests += 1
            if r.status_code == 200:
                self._consec_429 = 0
                return json.loads(r.text.split("\n", 1)[1])
            if r.status_code == 429:
                self.count_429 += 1
                self._consec_429 += 1
                if self._consec_429 >= self.max_429:
                    # 连续被限速：歇 4~5 分钟、换新会话再试，最多 3 次；时间不够就收工
                    pause = 240 + random.uniform(0, 60)
                    if self.cooldowns >= self.max_cooldowns or (
                            self.deadline and time.time() + pause > self.deadline):
                        raise RateLimited()
                    self.cooldowns += 1
                    self.log(f"[429] 连续被限速，冷却 {pause:.0f}s（第 {self.cooldowns} 次）")
                    time.sleep(pause)
                    self._new_session()
                    self._consec_429 = 0
                    continue
                pause = 60 * (attempt + 1) + random.uniform(0, 20)
                self.log(f"[429] 等 {pause:.0f}s 后重试")
                time.sleep(pause)
                self._new_session()
                continue
            self.log(f"[http {r.status_code}] {url[:120]}", private=True)
            return None
        return None

    def _explore(self, items, geo=""):
        req = {
            "comparisonItem": [{"keyword": k, "geo": geo, "time": t} for k, t in items],
            "category": 0,
            "property": "",
        }
        url = f"{BASE}/explore?hl=en-US&tz=0&req=" + urllib.parse.quote(json.dumps(req))
        data = self._get(url)
        return data.get("widgets", []) if data else []

    def _widget(self, path, widget):
        url = (f"{BASE}/widgetdata/{path}?hl=en-US&tz=0&req="
               + urllib.parse.quote(json.dumps(widget["request"]))
               + "&token=" + widget["token"])
        return self._get(url)

    # ---------- 对外 ----------
    @staticmethod
    def _parse_rising(data):
        lists = data.get("default", {}).get("rankedList", [])
        rising = lists[1].get("rankedKeyword", []) if len(lists) > 1 else []
        out = []
        for k in rising:
            fv = k.get("formattedValue", "")
            out.append({
                "query": k["query"].strip().lower(),
                "value": int(k.get("value", 0)),
                "breakout": fv.lower() == "breakout" or "飙升" in fv,
                "formatted": "Breakout" if fv.lower() == "breakout" else fv,
            })
        return out

    @staticmethod
    def _parse_series(data, hourly=False):
        pts = []
        for p in data.get("default", {}).get("timelineData", []):
            t = dt.datetime.fromtimestamp(int(p["time"]), dt.timezone.utc)
            pts.append({
                "date": t.isoformat(timespec="minutes") if hourly else t.date().isoformat(),
                "values": [int(v) for v in p.get("value", [])],
                "partial": bool(p.get("isPartial")),
            })
        return pts

    @staticmethod
    def _widget_keyword(w):
        try:
            return w["request"]["restriction"]["complexKeywordsRestriction"]["keyword"][0]["value"].lower()
        except (KeyError, IndexError, TypeError):
            return ""

    def related_rising(self, keyword, time_range="now 7-d"):
        """全球、近 7 天的「相关查询 - 搜索量上升」。返回 [{query, value, breakout, formatted}]；None 表示失败。"""
        widgets = self._explore([(keyword, time_range)])
        w = next((x for x in widgets if x.get("id", "").startswith("RELATED_QUERIES")), None)
        if not w:
            return None
        data = self._widget("relatedsearches", w)
        return self._parse_rising(data) if data else None

    def probe(self, keyword, ref="gpts"):
        """模拟手工操作：把词和 GPTs 放一起看近 7 天（全球），同时拿这个词自己的飙升相关词。
        一次 explore 拿两个面板，共 3 次请求。返回 {"series": 小时级对比曲线, "rising": [...]}，失败的部分为 None。"""
        widgets = self._explore([(keyword, "now 7-d"), (ref, "now 7-d")])
        if not widgets:
            return None
        out = {"series": None, "rising": None}
        ts = next((x for x in widgets if x.get("id") == "TIMESERIES"), None)
        if ts:
            data = self._widget("multiline", ts)
            if data:
                out["series"] = self._parse_series(data, hourly=True)
        rel = [x for x in widgets if x.get("id", "").startswith("RELATED_QUERIES")]
        rel_w = next((x for x in rel if self._widget_keyword(x) == keyword.lower()), rel[0] if rel else None)
        if rel_w:
            data = self._widget("relatedsearches", rel_w)
            if data:
                out["rising"] = self._parse_rising(data)
        return out

    def timeseries(self, keywords, time_range):
        """同一时间段对比多个词。返回 [{date, values[], partial}]；None 表示失败。"""
        widgets = self._explore([(k, time_range) for k in keywords])
        w = next((x for x in widgets if x.get("id") == "TIMESERIES"), None)
        if not w:
            return None
        data = self._widget("multiline", w)
        return self._parse_series(data) if data else None
