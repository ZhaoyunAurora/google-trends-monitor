#!/usr/bin/env python3
"""
Google Trends 直抓可行性测试（免费方案第 0 步）
用法：
    apt install -y python3-requests
    python3 test_trends.py

它会：先拿 Google 的 cookie（裸 curl 没有这一步，所以容易直接 429），
然后慢速查 3 个词根的「上升相关词」，每次请求之间等 40 秒。
把整段输出发回来即可。
"""
import json
import time
import urllib.parse

import requests

ROOTS = ["ai video", "ai image", "generator"]
SLEEP = 40  # 每次请求间隔（秒）
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def strip_prefix(text):
    # Google 在 JSON 前面加了 )]}' 防劫持前缀，去掉第一行
    return json.loads(text.split("\n", 1)[1])


def get_cookie():
    r = s.get("https://trends.google.com/?geo=US", timeout=30)
    print(f"[cookie] 状态码 {r.status_code}，拿到 cookie: {list(s.cookies.keys())}")


def explore(keyword):
    req = {
        "comparisonItem": [{"keyword": keyword, "geo": "", "time": "now 7-d"}],
        "category": 0,
        "property": "",
    }
    url = ("https://trends.google.com/trends/api/explore?hl=en-US&tz=0&req="
           + urllib.parse.quote(json.dumps(req)))
    r = s.get(url, timeout=30)
    print(f"[explore] {keyword!r} 状态码 {r.status_code}")
    if r.status_code != 200:
        return None
    for w in strip_prefix(r.text)["widgets"]:
        if w.get("id") == "RELATED_QUERIES":
            return w
    return None


def related(widget):
    url = ("https://trends.google.com/trends/api/widgetdata/relatedsearches"
           "?hl=en-US&tz=0&req=" + urllib.parse.quote(json.dumps(widget["request"]))
           + "&token=" + widget["token"])
    r = s.get(url, timeout=30)
    print(f"[related] 状态码 {r.status_code}")
    if r.status_code != 200:
        return []
    lists = strip_prefix(r.text)["default"]["rankedList"]
    rising = lists[1]["rankedKeyword"] if len(lists) > 1 else []
    return [(k["query"], k.get("formattedValue", k.get("value"))) for k in rising]


def main():
    get_cookie()
    ok = fail = 0
    for kw in ROOTS:
        time.sleep(SLEEP)
        w = explore(kw)
        if not w:
            fail += 1
            continue
        time.sleep(SLEEP)
        items = related(w)
        if items:
            ok += 1
            print(f"  -> {kw} 上升词 {len(items)} 个，前 5 个：")
            for q, v in items[:5]:
                print(f"     {q}  {v}")
        else:
            fail += 1
    print(f"\n结果：成功 {ok} / {len(ROOTS)}，失败 {fail}")


if __name__ == "__main__":
    main()
