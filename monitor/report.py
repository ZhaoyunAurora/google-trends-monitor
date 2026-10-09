"""根据当天数据生成 Markdown 日报 + 给 Claude 读的 JSON。"""
import json
import urllib.parse
from collections import defaultdict

from . import rules

REPORTS = rules.OUT_DIR / "reports"
DATA = rules.OUT_DIR / "data"

ORDER = ["新词", "老词二次爆火", "待观察", "短时尖峰"]
STATUS_RANK = {"上升中": 0, "高位": 1, "回落中": 2, "已明显回落": 3, "": 4}


def link(kw, span="today 12-m"):
    q = urllib.parse.urlencode({"date": span, "q": kw})
    return f"[{kw}](https://trends.google.com/trends/explore?{q})"


def fmt_path(path, kw):
    """来源链路：composer › yentl › (本词)"""
    return " › ".join(path[-3:]) if path else ""


def fmt_ratio(r):
    return "" if r is None else f"{r}×"


def rows_for(day, state):
    rows = []
    for kw, c in day["candidates"].items():
        r = state["reviewed"].get(kw)
        if not r:
            continue
        rows.append({**c, **r, "keyword": kw, "roots": c["roots"], "path": r.get("path") or c.get("path", [])})
    return rows


def build(day, state):
    rows = rows_for(day, state)
    by_kind = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    for k in by_kind:
        by_kind[k].sort(key=lambda r: (STATUS_RANK.get(r.get("status", ""), 4), -(r.get("gpts_ratio") or 0)))

    pending = [kw for kw in day["candidates"] if kw not in state["reviewed"]]
    pending.sort(key=lambda k: day["candidates"][k].get("depth", 1))
    runs = day.get("runs", [])
    reqs = sum(x["requests"] for x in runs)
    rising_n = sum(len(v) for v in day["rising"].values())

    L = [f"# {day['date']} 新词日报", ""]
    L.append(f"词根已查 {len(day['rising'])} 个 · 上升词 {rising_n} 条 → 候选 {len(day['candidates'])} 个 · "
             f"已复核 {len(rows)} 个 · **新词 {len(by_kind['新词'])} · 老词二次爆火 {len(by_kind['老词二次爆火'])} · "
             f"待观察 {len(by_kind['待观察'])}** · 今天运行 {len(runs)} 次，请求 {reqs} 次（UTC 时间）")
    L.append("")
    L.append("> 全部是**全球**数据。「vs gpts」= 和 GPTs 一起查近 7 天时，这个词的平均热度是 GPTs 的几倍（手工对比图左边的平均值柱子）。"
             "「来源链路」= 从哪个词根一层层点进来的。新词只说明刚出现，能不能做还要看 SERP 和变现。")
    L.append("")

    head = ("| 关键词 | 方向 | 首次出现 | 爆发日 | 走势 | vs gpts | 涨幅 | 来源链路 | 12 个月（周） | 30 天（天） "
            "| 7 天（每 6 小时） | 备注 |")
    sep = "|---|---|---|---|---|---|---|---|---|---|---|---|"
    for kind in ORDER:
        items = by_kind.get(kind, [])
        L.append(f"## {kind}（{len(items)}）")
        L.append("")
        if not items:
            L.append("暂无")
            L.append("")
            continue
        L += [head, sep]
        for r in items:
            L.append("| " + " | ".join([
                link(r["keyword"]), r.get("tag", ""), r.get("first_seen", ""), r.get("burst_date", ""),
                r.get("status", ""), fmt_ratio(r.get("gpts_ratio")), r.get("formatted", ""),
                fmt_path(r["path"], r["keyword"]), f"`{r.get('weekly_spark', '')}`", f"`{r.get('daily_spark', '')}`",
                f"`{r.get('spark_7d', '')}`",
                r.get("note", "").replace("|", "/"),
            ]) + " |")
        L.append("")

    others = by_kind.get("老词", []) + by_kind.get("数据不足", [])
    L.append(f"## 复核后是老词 / 数据不足（{len(others)}）")
    L.append("")
    L.append("、".join(f"{r['keyword']}（{r['kind']}）" for r in others) or "暂无")
    L.append("")
    L.append(f"## 还没轮到复核（{len(pending)}）")
    L.append("")
    L.append("、".join(f"{kw} {day['candidates'][kw]['formatted']}（第 {day['candidates'][kw].get('depth', 1)} 层）"
                      for kw in pending[:150]) or "暂无")
    if len(pending) > 150:
        L.append(f"…… 另有 {len(pending) - 150} 个")
    L.append("")

    filt = defaultdict(list)
    for kw, reason in day["filtered"].items():
        filt[reason].append(kw)
    L.append(f"## 已过滤（{len(day['filtered'])}，规则在 config/filters.txt，误杀的加到 config/allow.txt）")
    L.append("")
    for reason, kws in sorted(filt.items(), key=lambda x: -len(x[1])):
        L.append(f"- **{reason}**（{len(kws)}）：{'、'.join(kws)}")
    L.append("")

    L.append("## 各词根的上升词（原始）")
    L.append("")
    for root, items in day["rising"].items():
        if items:
            L.append(f"- **{root}**：" + "、".join(f"{i['query']} {i['formatted']}" for i in items))
    L.append("")
    L.append("## 往下挖：各个词自己的上升词（原始）")
    L.append("")
    for parent, items in day.get("expanded", {}).items():
        if items:
            L.append(f"- **{parent}**：" + "、".join(f"{i['query']} {i['formatted']}" for i in items))
    L.append("")

    text = "\n".join(L)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{day['date']}.md").write_text(text, encoding="utf-8")
    (REPORTS / "latest.md").write_text(text, encoding="utf-8")

    # 给 Claude 定时任务读的精简 JSON：只放值得判断的词
    keep = [r for r in rows if r["kind"] in ORDER]
    slim = [{k: r.get(k) for k in ("keyword", "kind", "tag", "status", "gpts_ratio", "formatted", "path",
                                   "first_seen", "burst_date", "weekly_spark", "daily_spark", "spark_7d", "note")}
            for r in keep]
    (DATA / "latest.json").write_text(
        json.dumps({"date": day["date"], "items": slim}, ensure_ascii=False, indent=1), encoding="utf-8")
