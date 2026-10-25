"""竞品新页面监测：模板站 / 游戏站一加新内页，基本就是有新词的信号。

配置在 config/watch_sites.txt，每行：名字 | 模式 | 地址（多个用逗号）| 链接正则
  sitemap 模式：读站点地图（支持索引），收集符合正则的页面地址
  crawl   模式：页面列表是前端加载的、站点地图里没有时用。从种子页面和最近发现的新页面里，
                顺着「相关推荐」链接找符合正则的新页面（像 media.io 的 /ai/explore/zone/xxx）
第一次运行只记录现有页面（作为基线），之后每次只报告新出现的页面。
已知页面存在私有仓库 data/signals/watch/名字.json。
"""
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET

from . import rules
from .signals import _get

WATCH_DIR = rules.OUT_DIR / "data" / "signals" / "watch"
STOP = set("""ai video videos image images photo generator generators maker trend trends prompt prompts template templates
    effect effects online free editor app tool tools create creator filter style the a an of to for and with
    capcut html php en""".split())


def load_sites():
    sites = []
    for line in rules._lines("watch_sites.txt"):
        parts = [x.strip() for x in line.split("|", 3)]  # 正则放最后，里面可以有 |
        if len(parts) < 4:
            continue
        name, mode, urls, pattern = parts[:4]
        sites.append({"name": name, "mode": mode, "urls": [u.strip() for u in urls.split(",") if u.strip()],
                      "pattern": re.compile(pattern)})
    return sites


def slug_keyword(url):
    """页面地址 → 拿去 Google 趋势验证的词：bulin-47-rap-ai-trend → bulin 47 rap"""
    slug = url.rstrip("/").split("/")[-1]
    slug = re.sub(r"\.(html?|php)$", "", slug)
    words = [w for w in re.split(r"[-_]+", slug.lower()) if w]
    core = [w for w in words if w not in STOP]
    if len(" ".join(core)) < 5:  # 太短（例如 ai-hug → hug），保留原来的写法
        return " ".join(words[:4])
    return " ".join(core)


def _locs(xml_bytes):
    if xml_bytes[:2] == b"\x1f\x8b":  # .xml.gz
        import gzip
        xml_bytes = gzip.decompress(xml_bytes)
    root = ET.fromstring(xml_bytes.strip())
    tag = root.tag.split("}")[-1]
    locs = [e.text.strip() for e in root.iter() if e.tag.endswith("loc") and e.text]
    return tag, locs


def _robots_sitemaps(url):
    """入口站点地图读不到时，去 robots.txt 里找它声明的站点地图。"""
    base = re.match(r"https?://[^/]+", url).group(0)
    txt = _get(base + "/robots.txt", timeout=30).text
    return [ln.split(":", 1)[1].strip() for ln in txt.splitlines() if ln.lower().startswith("sitemap:")]


def from_sitemap(urls, pattern, max_children=30):
    ok = []
    for u in urls:
        try:
            _locs(_get(u, timeout=60).content)
            ok.append(u)
        except Exception:  # noqa: BLE001
            ok += _robots_sitemaps(u)
    urls = ok
    found, todo, seen = set(), list(urls), set()
    while todo and len(seen) < max_children + len(urls):
        u = todo.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            tag, locs = _locs(_get(u, timeout=60).content)
        except Exception:  # noqa: BLE001  某个子站点地图坏了就跳过；入口坏了才算失败
            if u in urls:
                raise
            continue
        if tag == "sitemapindex":
            todo += locs
        else:
            found |= {x for x in locs if pattern.search(x)}
    return found


HREF = re.compile(r"""href=["']([^"'#?]+)""")


def from_crawl(urls, pattern, known, per_run=12):
    found = set()
    # 种子页 + 最近发现的页面（新页面的「相关推荐」里最容易出现更新的页面）
    recent = sorted(known.items(), key=lambda kv: kv[1], reverse=True)[:per_run]
    for u in list(urls) + [k for k, _ in recent]:
        try:
            html = _get(u, timeout=40).text
        except Exception:  # noqa: BLE001
            continue
        for h in HREF.findall(html):
            if h.startswith("/"):
                h = re.match(r"https?://[^/]+", u).group(0) + h
            if pattern.search(h):
                found.add(h.rstrip("/"))
    return found


def check_all(log=print):
    """返回 (新页面信号列表, 每个站的状态)。"""
    items, status = [], {}
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    for site in load_sites():
        path = WATCH_DIR / f"{re.sub(r'[\\/:*?\"<>| ]', '_', site['name'])}.json"
        known = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        try:
            if site["mode"] == "crawl":
                found = from_crawl(site["urls"], site["pattern"], known)
            else:
                found = from_sitemap(site["urls"], site["pattern"])
        except Exception as e:  # noqa: BLE001
            status[site["name"]] = f"失败：{type(e).__name__}"
            log(f"[竞品] {site['name']}: {status[site['name']]}")
            continue
        new = sorted(u for u in found if u not in known)
        # 一次冒出很多「新页面」多半是站点改版 / 换了地址格式，不是新词，当作重新记基线
        baseline = not known or len(new) > 100
        for u in new:
            known[u] = today
        path.write_text(json.dumps(known, ensure_ascii=False, indent=0), encoding="utf-8")
        if baseline:
            status[site["name"]] = f"第一次运行，记录了 {len(found)} 个现有页面作为基线"
        else:
            status[site["name"]] = f"新页面 {len(new)} 个（已知 {len(known)} 个）"
            for u in new[:40]:
                items.append({"source": f"竞品新页面 {site['name']}", "name": u.split('/')[-1], "url": u,
                              "keyword": slug_keyword(u), "score": "", "note": f"{today} 新出现的页面"})
        log(f"[竞品] {site['name']}: {status[site['name']]}")
    return items, status
