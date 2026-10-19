"""早期信号源：比 Google 趋势「相关查询」更早看到苗头的地方。

每个来源返回 [{source, name, keyword, url, score, note}]：
  name     展示用的名字
  keyword  拿去 Google Trends 验证的词（小写）；为空表示只展示、不验证
所有来源都是免费公开接口；任何一个失败都不影响其他来源和主流程。
"""
import base64
import datetime as dt
import io
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def _get(url, timeout=40):
    r = S.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def _clean(name):
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


# ---------------------------------------------------------------- 新注册域名
# whoisds 每天免费公布前一天新注册的域名（约 7~10 万个）。
# 同一个名字一天里被注册了好几个后缀 / 变体（pokesurvivor.com / .io / .org），说明一批人已经在抢这个词。
AFFIX = ["ai", "app", "online", "free", "game", "games", "play", "official", "hq", "hub", "pro", "tool", "tools",
         "the", "get", "try", "my", "use", "go", "io", "web", "site", "gen", "generator", "maker", "video", "unblocked"]
NRD_SKIP = re.compile(r"(casino|bet|slot|loan|porn|sex|xxx|cbd|vape|crypto|token|coin|shop|store|mall|outlet|"
                      r"hotel|travel|law|dental|clinic|realty|homes|plumb|roof|\d{4,})")


GENERIC_CORE = set("""video image photo music games online studio global group service services digital media
    design market capital health energy travel global world consulting solutions systems network academy
    agency homes realty beauty fashion""".split())


def _core(label):
    core = label
    changed = True
    while changed and len(core) > 4:
        changed = False
        for a in AFFIX:
            if core.startswith(a) and len(core) - len(a) >= 5:
                core, changed = core[len(a):], True
            if core.endswith(a) and len(core) - len(a) >= 5:
                core, changed = core[:-len(a)], True
    return core


BUILDER_TLDS = {"com", "io", "ai", "app", "org", "net", "co", "xyz", "online", "site", "pro", "gg", "me", "cc",
                "top", "fun", "games", "game", "tv", "so", "dev", "studio", "art", "video", "tools", "space", "click",
                "live", "world", "info", "us", "uk", "ca", "au", "de", "fr", "es", "it", "jp", "in", "lol", "wiki"}


def _nrd_day(day):
    name = base64.b64encode(f"{day.isoformat()}.zip".encode()).decode()
    url = f"https://www.whoisds.com//whois-database/newly-registered-domains/{name}/nrd"
    r = _get(url, timeout=120)
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    return zf.read(zf.namelist()[0]).decode("utf-8", "ignore").splitlines()


def nrd(window=7, top=60):
    """最近 window 天新注册的域名里，同一个名字被注册成多个常用后缀 / 多个写法（多半是不同的人在抢）。
    只统计做站常用的后缀（.com .io .ai .app .org …），一个人把同一个名字买遍几十个冷门后缀的不算。"""
    today = dt.datetime.now(dt.timezone.utc).date()
    groups = defaultdict(lambda: {"domains": set(), "labels": set(), "days": set()})
    got_days = []
    for i in range(1, window + 1):
        day = today - dt.timedelta(days=i)
        try:
            lines = _nrd_day(day)
        except Exception:  # noqa: BLE001  某天的列表拿不到就跳过
            continue
        got_days.append(day.isoformat())
        for line in lines:
            d = line.strip().lower()
            parts = d.split(".")
            if len(parts) != 2 or parts[1] not in BUILDER_TLDS:
                continue
            label = parts[0]
            if len(label) < 6 or len(label) > 24 or label.count("-") > 2 or not label.replace("-", "").isalnum():
                continue
            label = label.replace("-", "")
            if NRD_SKIP.search(label) or label.isdigit():
                continue
            core = _core(label)
            if len(core) < 5 or core in GENERIC_CORE:
                continue
            g = groups[core]
            g["domains"].add(d)
            g["labels"].add(label)
            g["days"].add(day.isoformat())
    out = []
    for core, g in groups.items():
        b, v = len(g["domains"]), len(g["labels"])
        if not (b >= 3 or (v >= 2 and b >= 2)):
            continue
        doms = sorted(g["domains"])
        days = sorted(g["days"])
        out.append({"source": "新注册域名", "name": core, "keyword": core, "url": "https://" + doms[0],
                    "score": b + v, "first": days[0], "last": days[-1],
                    "note": f"{days[0][5:]}~{days[-1][5:]} 注册了 {b} 个（{v} 种写法）：" + "、".join(doms[:6])})
    out.sort(key=lambda x: (-x["score"], x["first"]))
    if not got_days:
        raise RuntimeError("新注册域名列表一天都没拿到")
    return out[:top]


# ---------------------------------------------------------------- Google 实时热搜
def trending_now(geos=("US", "GB", "CA", "AU")):
    out, seen = [], set()
    for geo in geos:
        r = _get(f"https://trends.google.com/trending/rss?geo={geo}")
        root = ET.fromstring(r.content)
        ns = {"ht": "https://trends.google.com/trending/rss"}
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            traffic = item.findtext("ht:approx_traffic", default="", namespaces=ns)
            kw = title.lower()
            if not kw or kw in seen:
                continue
            seen.add(kw)
            q = urllib.parse.urlencode({"q": title, "date": "now 7-d"})
            out.append({"source": f"实时热搜 {geo}", "name": title, "keyword": kw,
                        "url": f"https://trends.google.com/trends/explore?{q}", "score": traffic,
                        "note": f"{geo} 过去 24 小时约 {traffic} 次搜索"})
    return out


# ---------------------------------------------------------------- Hugging Face
def huggingface(limit=40, max_age_days=21):
    out = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
    for kind, url in (("模型", f"https://huggingface.co/api/models?sort=trendingScore&limit={limit}"),
                      ("Space", f"https://huggingface.co/api/spaces?sort=trendingScore&limit={limit}")):
        for m in _get(url).json():
            mid = m.get("id") or m.get("modelId") or ""
            created = m.get("createdAt") or ""
            try:
                is_new = dt.datetime.fromisoformat(created.replace("Z", "+00:00")) >= cutoff
            except ValueError:
                is_new = False
            if not is_new:
                continue
            short = mid.split("/")[-1]
            out.append({"source": f"Hugging Face {kind}", "name": mid, "keyword": _clean(short),
                        "url": f"https://huggingface.co/{'spaces/' if kind == 'Space' else ''}{mid}",
                        "score": m.get("likes", 0),
                        "note": f"{created[:10]} 发布，{m.get('likes', 0)} 赞" +
                                (f"，{m.get('pipeline_tag')}" if m.get("pipeline_tag") else "")})
    return out


# ---------------------------------------------------------------- itch.io 网页游戏
def itch(limit=30):
    out = []
    for label, url in (("新游戏热门", "https://itch.io/games/new-and-popular/platform-web.xml"),
                       ("热门", "https://itch.io/games/platform-web.xml")):
        root = ET.fromstring(_get(url).content)
        for item in list(root.iter("item"))[:limit]:
            title = (item.findtext("plainTitle") or item.findtext("title") or "").strip()
            link = item.findtext("link") or ""
            if not title:
                continue
            out.append({"source": f"itch.io {label}", "name": title, "keyword": _clean(title),
                        "url": link, "score": "", "note": "网页可玩"})
    return out


# ---------------------------------------------------------------- Reddit（只展示，交给 Claude 读）
SUBS = ["aivideo", "StableDiffusion", "ChatGPT", "singularity", "AIArt", "WebGames", "incremental_games",
        "SideProject", "InternetIsBeautiful"]


def reddit(per_sub=15):
    out = []
    for sub in SUBS:
        try:
            data = _get(f"https://www.reddit.com/r/{sub}/hot.json?limit={per_sub}").json()
        except Exception:  # noqa: BLE001  某个版块失败不影响其他版块
            continue
        for c in data.get("data", {}).get("children", []):
            p = c.get("data", {})
            if p.get("stickied"):
                continue
            out.append({"source": f"Reddit r/{sub}", "name": p.get("title", "")[:140], "keyword": "",
                        "url": "https://www.reddit.com" + p.get("permalink", ""), "score": p.get("score", 0),
                        "note": f"{p.get('score', 0)} 赞 · {p.get('num_comments', 0)} 评论"})
    return out


# ---------------------------------------------------------------- Product Hunt（只展示）
def producthunt():
    root = ET.fromstring(_get("https://www.producthunt.com/feed").content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("a:entry", ns)[:30]:
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
        link = e.find("a:link", ns)
        out.append({"source": "Product Hunt", "name": title, "keyword": "",
                    "url": link.get("href") if link is not None else "", "score": "", "note": ""})
    return out


# Reddit 拒绝 GitHub 机房的 IP（实测 0 条），先不抓
SOURCES = {"nrd": nrd, "trending": trending_now, "hf": huggingface, "itch": itch, "producthunt": producthunt}


def fetch_all(log=print, skip=()):
    """抓所有来源。返回 (items, status)，status = {来源: 条数 或 错误信息}。"""
    items, status = [], {}
    for key, fn in SOURCES.items():
        if key in skip:
            continue
        try:
            got = fn()
            items += got
            status[key] = len(got)
        except Exception as e:  # noqa: BLE001
            status[key] = f"失败：{type(e).__name__}"
        log(f"[信号] {key}: {status[key]}")
    return items, status
