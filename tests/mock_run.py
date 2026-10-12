"""用假数据跑一遍完整流程，不发任何网络请求。
用法：python -m tests.mock_run   （结果写到 data/ 和 reports/，测完可删）
"""
import datetime as dt
import os

os.environ.setdefault("RUN_MINUTES", "5")

from monitor import run  # noqa: E402

DAYS = [(dt.date(2026, 9, 12) + dt.timedelta(days=i)).isoformat() for i in range(31)]

# 30 天日曲线（最后一个点是今天，未统计完）
SHAPES = {
    "hotel lobby ai video": [0] * 20 + [5, 10, 20, 40, 60, 80, 90, 100, 95, 98, 40],           # 新词
    "hotel lobby ai video prompt": [0] * 22 + [10, 30, 50, 70, 90, 100, 95, 98, 30],          # 第 2 层新词
    "migos ai": [5] * 18 + [20, 40, 60, 80, 90, 100, 95, 90, 85, 88, 92, 90, 30],             # 老词二次爆火
    "copse": [10] * 25 + [100, 15, 10, 10, 11, 5],                                             # 短时尖峰
    "ai image generator": [60 + i % 7 for i in range(31)],                                     # 老词
    "seedance 3": [2] * 29 + [3, 100],                                                         # 今天刚冒头
    "yentl setting": [0] * 26 + [100, 90, 80, 70, 60, 30],                                     # 新词，但相关词是填字游戏
    "tiny new tool": [0] * 22 + [1, 2, 3, 5, 7, 8, 9, 10, 3],                                  # 很小的新词
}
GPTS = [50] * 31

CHILDREN = {
    "higgsfield": [
        {"query": "hotel lobby ai video", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "migos ai", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "sony universal legal action suno", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "remove bg", "value": 80, "breakout": False, "formatted": "+80%"},
    ],
    "ai video": [
        {"query": "seedance 3", "value": 2500, "breakout": False, "formatted": "+2,500%"},
        {"query": "ai image generator", "value": 400, "breakout": False, "formatted": "+400%"},
        {"query": "how to bake a cake", "value": 4000, "breakout": False, "formatted": "+4,000%"},
        {"query": "copse", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "tiny new tool", "value": 0, "breakout": True, "formatted": "Breakout"},
    ],
    "hotel lobby ai video": [
        {"query": "hotel lobby ai video prompt", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "yentl setting", "value": 0, "breakout": True, "formatted": "Breakout"},
    ],
    "yentl setting": [
        {"query": "crossword", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "yentl setting crossword clue", "value": 0, "breakout": True, "formatted": "Breakout"},
    ],
    "hotel lobby ai video prompt": [
        {"query": "hotel lobby ai video", "value": 0, "breakout": True, "formatted": "Breakout"},
    ],
}


class FakeTrends:
    requests = 0
    count_429 = 0

    def probe(self, kw, ref="gpts"):
        self.requests += 3
        k = SHAPES.get(kw, [0] * 31)[-8:-1]
        scale = 0.08 if kw == "tiny new tool" else 1
        hours = [int(v * scale) for v in k for _ in range(24)]
        series = [{"date": f"h{i}", "values": [v, 50], "partial": False} for i, v in enumerate(hours)]
        return {"series": series, "rising": CHILDREN.get(kw, [])}

    def related_rising(self, kw, time_range="now 7-d"):
        self.requests += 2
        return CHILDREN.get(kw, [])

    def timeseries(self, keywords, time_range):
        self.requests += 2
        kw = keywords[0]
        k = SHAPES.get(kw, [0] * 31)
        if len(keywords) > 1:
            scale = 0.08 if kw == "tiny new tool" else 1  # 很小的词和 GPTs 同图只剩 0/1
            vals = [[int(v * scale), g] for v, g in zip(k, GPTS)]
        else:
            vals = [[v] for v in k]
        return [{"date": d, "values": v, "partial": i == 30} for i, (d, v) in enumerate(zip(DAYS, vals))]


if __name__ == "__main__":
    run.rules.load_roots = lambda: (["higgsfield", "ai video"], [])
    run.Runner(client=FakeTrends()).run()
    print((run.rules.OUT_DIR / "reports" / "latest.md").read_text(encoding="utf-8"))
