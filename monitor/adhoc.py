"""临时查曲线：给复盘用。读私有仓库 adhoc/keywords.txt（每行一个词），
每个词和 gpts 一起查最近 90 天（全球、按天），结果写到 adhoc/latest.json。
可以中断续查：主流程每轮花一小部分时间查几个，查完为止；改了词表就重新查新增的词。
公开日志里只打进度，不打关键词。"""
import datetime as dt
import json
import os
import statistics
import time

from . import rules

REF_DAILY = float(os.getenv("REF_DAILY", "5000"))
RANGE = os.getenv("ADHOC_RANGE", "today 3-m")


def _paths():
    base = rules.OUT_DIR / "adhoc"
    return base, base / "keywords.txt", base / "latest.json"


def pending():
    base, kw_path, out_path = _paths()
    if not kw_path.exists():
        return []
    kws = [x.strip().lower() for x in kw_path.read_text(encoding="utf-8").splitlines()
           if x.strip() and not x.startswith("#")]
    done = json.loads(out_path.read_text(encoding="utf-8")).get("keywords", {}) if out_path.exists() else {}
    return [k for k in kws if not done.get(k)]


def summarize(pts):
    series = [{"date": p["date"], "v": p["values"][0], "gpts": p["values"][1], "partial": p.get("partial", False)}
              for p in pts]
    ref = statistics.median([x["gpts"] for x in series if not x["partial"]] or [0])
    est = lambda v: round(v / ref * REF_DAILY) if ref else None  # noqa: E731
    for x in series:
        x["est_daily"] = est(x["v"])
    peak = max(series, key=lambda x: x["v"]) if series else None
    first_at = lambda n: next((x["date"] for x in series if (x["est_daily"] or 0) >= n), None)  # noqa: E731
    return {"first_nonzero": next((x["date"] for x in series if x["v"] > 0), None),
            "first_50": first_at(50), "first_300": first_at(300), "first_1000": first_at(1000),
            "peak_date": peak["date"] if peak else None, "peak_est_daily": est(peak["v"]) if peak else None,
            "series": series}


def run_with(client, until, log=print):
    """用主流程的客户端查，最多查到 until（时间戳）。返回查了几个。"""
    todo = pending()
    if not todo:
        return 0
    base, _, out_path = _paths()
    out = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    out.update({"range": RANGE, "ref": "gpts", "ref_daily": REF_DAILY})
    out.setdefault("keywords", {})
    n = 0
    for kw in todo:
        if time.time() > until:
            break
        pts = client.timeseries([kw, "gpts"], RANGE)
        if pts:
            out["keywords"][kw] = summarize(pts)
            n += 1
        out["at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        base.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[复盘曲线] 本轮查了 {n} 个，还剩 {len(pending())} 个")
    return n


def main():
    from .trends import Trends
    run_with(Trends(interval=float(os.getenv("REQUEST_INTERVAL", "8"))), time.time() + 15 * 60)


if __name__ == "__main__":
    main()
