"""把趋势曲线判成：新词 / 老词二次爆火 / 短时尖峰 / 待观察 / 老词 / 数据不足。"""
from statistics import median

BARS = "▁▂▃▄▅▆▇█"


def spark(values, width=None):
    vals = values[-width:] if width else values
    peak = max(vals) if vals else 0
    if peak == 0:
        return "·" * len(vals)
    out = []
    for v in vals:
        if v == 0:
            out.append("·")
        else:
            out.append(BARS[min(len(BARS) - 1, int(v / peak * (len(BARS) - 1) + 0.5))])
    return "".join(out)


def complete(points, idx=0, keep_partial=False):
    """默认去掉最后的不完整数据点，返回 (日期列表, 数值列表)。"""
    pts = points if keep_partial else [p for p in points if not p["partial"]]
    return [p["date"] for p in pts], [p["values"][idx] for p in pts]


def classify_weekly(dates, vals):
    """只看 12 个月周数据的初判。返回 dict。"""
    if not vals or max(vals) == 0:
        return {"kind": "数据不足"}
    recent, prior = vals[-6:], vals[:-6]
    first = next(i for i, v in enumerate(vals) if v > 0)
    nonzero_frac = sum(1 for v in prior if v > 0) / max(len(prior), 1)
    res = {
        "first_seen": dates[first],
        "nonzero_frac": round(nonzero_frac, 2),
        "weekly_spark": spark(vals, 27),
        "weekly_peak_date": dates[vals.index(max(vals))],
    }
    if nonzero_frac <= 0.10:
        if prior and max(prior) > 0.6 * max(recent):
            res["kind"] = "老词"
            res["note"] = f"出现较早，高峰在 {res['weekly_peak_date']} 那一周，最近热度不高"
        else:
            res["kind"] = "新词"
            if nonzero_frac > 0:
                res["note"] = f"出现前偶有零星搜索（{int(nonzero_frac * 100)}% 的周有数据）"
        return res
    base = max(median(prior), 1)
    res["boost"] = round(max(recent) / base, 1)
    res["kind"] = "爆发候选" if res["boost"] >= 5 else "老词"
    return res


def partial_tail(points, idx=0):
    """最后一个不完整数据点（今天 / 本周）的 (日期, 值)，没有就返回 None。"""
    if points and points[-1]["partial"]:
        return points[-1]["date"], points[-1]["values"][idx]
    return None


def classify_daily(dates, vals, tail=None):
    """30 天日数据：判断走势、是否只热一两天。
    tail = 今天还没统计完的 (日期, 值)。不完整的值通常偏低，如果它已经是最高点，说明今天刚爆。"""
    if tail and vals and tail[1] > max(vals) and tail[1] > 0:
        return {
            "status": "上升中",
            "burst_date": tail[0],
            "high_days": 1,
            "short_spike": False,
            "just_started": True,
            "daily_spark": spark(vals + [tail[1]], 30),
        }
    if not vals or max(vals) == 0:
        return {"status": "", "short_spike": False}
    peak = max(vals)
    peak_i = vals.index(peak)
    last14 = vals[-14:]
    high_days = sum(1 for v in last14 if v >= 0.3 * peak)
    last3 = sum(vals[-3:]) / 3
    prev7 = sum(vals[-10:-3]) / 7 if len(vals) >= 10 else last3
    if last3 < 0.3 * peak:
        status = "已明显回落"
    elif last3 >= prev7 * 1.2:
        status = "上升中"
    elif last3 <= prev7 * 0.8:
        status = "回落中"
    else:
        status = "高位"
    just_started = peak_i >= len(vals) - 2 and high_days <= 2
    return {
        "status": status,
        "burst_date": dates[peak_i],
        "high_days": high_days,
        "short_spike": high_days <= 2 and not just_started,
        "just_started": just_started,
        "daily_spark": spark(vals, 30),
    }


def finalize(weekly_res, daily_res):
    kind = weekly_res["kind"]
    res = dict(weekly_res)
    if daily_res:
        res.update(daily_res)
    notes = [res["note"]] if res.get("note") else []
    if kind == "爆发候选":
        if daily_res and daily_res.get("just_started"):
            kind = "待观察"
            notes.append("最近 1~2 天才冒头，下次运行重查")
        elif daily_res and daily_res.get("short_spike"):
            kind = "短时尖峰"
            notes.append("老词只热了一两天，常见于新闻、刷量、每日谜题答案")
        else:
            kind = "老词二次爆火"
        notes.insert(0, f"最近 6 周峰值是前期中位数的 {res.get('boost')} 倍")
    elif kind == "新词" and daily_res and daily_res.get("short_spike"):
        notes.append("只热了一两天就回落（新闻 / 刷量 / 谜题答案常见这种形态）")
    res["kind"] = kind
    res["note"] = "；".join(notes)
    return res


def classify_7d(points):
    """和 GPTs 一起查的近 7 天小时曲线（全球）。points 的 values = [词, gpts]。
    返回 gpts_ratio（7 天平均热度是 GPTs 的几倍，对应手工对比图左边的「平均值」柱子）、7 天走势、是否已回落。"""
    pts = [p for p in points if len(p["values"]) >= 2]
    if not pts:
        return {}
    kv = [p["values"][0] for p in pts]
    rv = [p["values"][1] for p in pts]
    res = {"gpts_ratio": round(sum(kv) / sum(rv), 3) if sum(rv) else None}
    if max(kv) == 0:
        res["spark_7d"] = "·" * 28
        return res
    # 每 6 小时取最大值，压成 28 格
    bins = [max(kv[i:i + 6]) for i in range(0, len(kv), 6)]
    res["spark_7d"] = spark(bins, 28)
    peak = max(kv)
    peak_i = kv.index(peak)
    res["peak_7d"] = pts[peak_i]["date"]
    last24 = sum(kv[-24:]) / max(len(kv[-24:]), 1)
    # 值太小时（相对 GPTs 只有 0/1），形状没有参考价值
    res["faded_7d"] = peak >= 5 and peak_i < len(kv) - 36 and last24 < 0.15 * peak
    prev48 = sum(kv[-72:-24]) / max(len(kv[-72:-24]), 1)
    res["rising_7d"] = last24 > 0 and last24 >= prev48 * 1.2
    return res


def junk_from_children(children, filter_reason):
    """看这个词自己的飙升相关词：如果大多是填字游戏答案 / 新闻 / 体育等，这个词本身也是这类。
    例：yentl setting 的相关词是 crossword、yentl setting crossword clue → 谜题答案。"""
    hits = {}
    for c in children:
        r = filter_reason(c["query"])
        # 「网址导航」不算垃圾：相关词里出现 xxx.io / xxx.com，往往说明有新产品、新网站（例如 pokesurvivor）
        if r and r not in ("非英文", "问句长句", "网址导航"):
            hits[r] = hits.get(r, 0) + 1
    if not hits:
        return None
    reason, n = max(hits.items(), key=lambda x: x[1])
    if n >= 2 or n / max(len(children), 1) >= 0.4:
        return reason
    return None


def classify_month(dates, vals, tail=None):
    """30 天日曲线（单独或和 GPTs 同图都可以，只看形状）判断：
    新词 / 老词二次爆火 / 待观察 / 短时尖峰 / 老词 / 数据不足，
    并给出 起来时间、峰值日、现在是峰值的百分之几、走势。"""
    if tail and vals and tail[1] > 0:
        # 今天（还没统计完）的值。只有明显高出之前，才算"今天刚冒头"：
        # 之前几乎没量的词：今天超过之前的最高点；一直有量的老词：今天要到平时（中位数）的 3 倍以上
        nonzero_days = sum(1 for v in vals if v > 0)
        quiet_before = nonzero_days <= max(2, 0.2 * len(vals))
        base = max(median(vals), 1)
        if (quiet_before and tail[1] > max(vals)) or (not quiet_before and tail[1] >= 3 * base and tail[1] > max(vals)):
            res = {"kind": "待观察", "status": "上升中", "burst_date": tail[0], "peak_date": tail[0],
                   "now_pct": 100, "daily_spark": spark(vals + [tail[1]], 30),
                   "first_seen": next((d for d, v in zip(dates, vals) if v > 0), tail[0]),
                   "note": "今天才冒头，几小时后重查" if quiet_before else
                           f"老词今天突然是平时的 {round(tail[1] / base, 1)} 倍，几小时后重查"}
            return res
    if not vals or max(vals) == 0:
        return {"kind": "数据不足", "daily_spark": spark(vals or [], 30)}
    peak = max(vals)
    peak_i = len(vals) - 1 - vals[::-1].index(peak)  # 最近一次峰值
    # 起来时间：从峰值往前找，直到热度掉到峰值 20% 以下
    start = peak_i
    while start > 0 and vals[start - 1] >= 0.2 * peak:
        start -= 1
    prior = vals[:start]
    res = {
        "first_seen": next(d for d, v in zip(dates, vals) if v > 0),
        "burst_date": dates[start],
        "peak_date": dates[peak_i],
        "daily_spark": spark(vals, 30),
    }
    last = vals[-1]
    last3 = sum(vals[-3:]) / min(3, len(vals))
    prev7 = sum(vals[-10:-3]) / 7 if len(vals) >= 10 else last3
    res["now_pct"] = round(100 * last / peak)
    if last3 < 0.3 * peak:
        res["status"] = "已明显回落"
    elif last3 >= prev7 * 1.2:
        res["status"] = "上升中"
    elif last3 <= prev7 * 0.8:
        res["status"] = "回落中"
    else:
        res["status"] = "高位"

    nonzero = sum(1 for v in prior if v > 0)
    if prior and nonzero <= max(1, 0.2 * len(prior)) and max(prior) <= 0.25 * peak:
        kind = "新词"
    elif not prior:
        kind = "老词"  # 整个 30 天都在高位：之前就有量
        res["note"] = "30 天内一直有量，不是这个月才起来的"
    else:
        base = max(median(prior), 1)
        boost = peak / base
        res["boost"] = round(boost, 1)
        kind = "老词二次爆火" if boost >= 5 else "老词"
        if kind == "老词二次爆火":
            res["note"] = f"之前就有量，这次峰值是平时的 {res['boost']} 倍"

    after = vals[start:]
    high_days = sum(1 for v in after if v >= 0.3 * peak)
    if kind in ("新词", "老词二次爆火"):
        if peak_i >= len(vals) - 2 and high_days <= 2:
            kind = "待观察"
            res["note"] = "最近 1~2 天才冒头，几小时后重查"
        elif high_days <= 2 and res["status"] == "已明显回落":
            kind = "短时尖峰"
            res["note"] = "只热了一两天就回落（新闻 / 刷量 / 谜题答案常见这种形态）"
    res["kind"] = kind
    return res
