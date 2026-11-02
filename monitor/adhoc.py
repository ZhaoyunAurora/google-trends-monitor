"""临时查曲线：给复盘用。读私有仓库 adhoc/keywords.txt（每行一个词），
每个词和 gpts 一起查最近 90 天（全球、按天），结果写到 adhoc/result-时间.json 和 adhoc/latest.json。
公开日志里只打进度，不打关键词。"""
import datetime as dt
import json
import os

from . import rules
from .trends import Trends

REF_DAILY = float(os.getenv("REF_DAILY", "5000"))


def main():
    base = rules.OUT_DIR / "adhoc"
    kws = [x.strip().lower() for x in (base / "keywords.txt").read_text(encoding="utf-8").splitlines()
           if x.strip() and not x.startswith("#")]
    t = Trends(interval=float(os.getenv("REQUEST_INTERVAL", "8")))
    rng = os.getenv("ADHOC_RANGE", "today 3-m")
    out = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "range": rng, "ref": "gpts",
           "ref_daily": REF_DAILY, "keywords": {}}
    for i, kw in enumerate(kws, 1):
        pts = t.timeseries([kw, "gpts"], rng)
        if not pts:
            out["keywords"][kw] = None
            print(f"{i}/{len(kws)} 失败", flush=True)
            continue
        series = []
        for p in pts:
            v, g = p["values"][0], p["values"][1]
            series.append({"date": p["date"], "v": v, "gpts": g, "partial": p.get("partial", False)})
        ref = sorted(x["gpts"] for x in series if not x["partial"])
        ref_med = ref[len(ref) // 2] if ref else 0
        first = next((x["date"] for x in series if x["v"] > 0), None)
        # 「起来」：第一次达到峰值的 10%
        peak = max(series, key=lambda x: x["v"]) if series else None
        rise = next((x["date"] for x in series if peak and peak["v"] and x["v"] >= peak["v"] * 0.1), None)
        out["keywords"][kw] = {
            "first_nonzero": first, "rise_10pct": rise, "peak_date": peak["date"] if peak else None,
            "peak_est_daily": round(peak["v"] / ref_med * REF_DAILY) if peak and ref_med else None,
            "series": series}
        print(f"{i}/{len(kws)} ok", flush=True)
    base.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    for name in (f"result-{stamp}.json", "latest.json"):
        (base / name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
