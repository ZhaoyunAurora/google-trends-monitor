"""用假数据跑一遍完整流程，不发任何网络请求。
用法：python -m tests.mock_run   （结果写到 data/ 和 reports/，测完可删）
"""
import datetime as dt
import os

os.environ.setdefault("RUN_MINUTES", "5")

from monitor import run  # noqa: E402

WEEKS = [(dt.date(2025, 10, 12) + dt.timedelta(weeks=i)).isoformat() for i in range(53)]
DAYS = [(dt.date(2026, 9, 9) + dt.timedelta(days=i)).isoformat() for i in range(31)]

SHAPES = {
    # 新词：最近 3 周才出现，还在涨
    "hotel lobby ai video": ([0] * 49 + [5, 30, 80, 100], [0] * 20 + [5, 10, 20, 40, 60, 80, 90, 100, 95, 98, 97]),
    # 老词二次爆火：常年 2~3，最近暴涨并持续
    "migos ai": ([3] * 47 + [2, 10, 40, 90, 100, 85], [5] * 18 + [20, 40, 60, 80, 90, 100, 95, 90, 85, 88, 92, 90, 80]),
    # 短时尖峰：老词只热一天
    "copse": ([10] * 51 + [100, 12], [10] * 25 + [100, 15, 10, 10, 11, 10]),
    # 老词：一直有量
    "ai image generator": ([60 + (i % 7) for i in range(53)], None),
    # 待观察：老词，今天前一两天才冒头
    "seedance 3": ([2] * 51 + [3, 20], [2] * 29 + [3, 100]),
    # 第 2 层挖出来的新词
    "hotel lobby ai video prompt": ([0] * 50 + [20, 100, 90], [0] * 22 + [10, 30, 50, 70, 90, 100, 95, 98, 97]),
    "yentl setting": ([0] * 51 + [100, 5], [0] * 26 + [100, 10, 0, 0, 0]),
}

# 每个词自己的飙升相关词（往下挖用）
CHILDREN = {
    "hotel lobby ai video": [
        {"query": "hotel lobby ai video prompt", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "yentl setting", "value": 0, "breakout": True, "formatted": "Breakout"},
    ],
    "yentl setting": [
        {"query": "crossword", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "yentl setting crossword", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "yentl setting crossword clue", "value": 0, "breakout": True, "formatted": "Breakout"},
        {"query": "souk", "value": 0, "breakout": True, "formatted": "Breakout"},
    ],
    "hotel lobby ai video prompt": [
        {"query": "hotel lobby ai video", "value": 0, "breakout": True, "formatted": "Breakout"},  # 回环，应跳过
    ],
}


class FakeTrends:
    requests = 0
    count_429 = 0

    def related_rising(self, root, time_range="now 7-d"):
        self.requests += 2
        base = [{"query": "remove bg", "value": 80, "breakout": False, "formatted": "+80%"}]
        if root == "higgsfield":
            return base + [
                {"query": "hotel lobby ai video", "value": 0, "breakout": True, "formatted": "Breakout"},
                {"query": "migos ai", "value": 0, "breakout": True, "formatted": "Breakout"},
                {"query": "migos ai", "value": 0, "breakout": True, "formatted": "Breakout"},
                {"query": "sony universal legal action suno", "value": 0, "breakout": True, "formatted": "Breakout"},
            ]
        if root == "ai video":
            return base + [
                {"query": "seedance 3", "value": 2500, "breakout": False, "formatted": "+2,500%"},
                {"query": "ai image generator", "value": 400, "breakout": False, "formatted": "+400%"},
                {"query": "how to bake a cake", "value": 4000, "breakout": False, "formatted": "+4,000%"},
                {"query": "copse", "value": 0, "breakout": True, "formatted": "Breakout"},
                {"query": "openai dots app", "value": 0, "breakout": True, "formatted": "Breakout"},
            ]
        return base

    def probe(self, kw, ref="gpts"):
        self.requests += 3
        weekly, daily = SHAPES.get(kw, ([0] * 53, [0] * 31))
        last = (daily or [50] * 31)[-7:]
        hours = [v for v in last for _ in range(24)]
        series = [{"date": f"h{i}", "values": [v // 2, 50], "partial": False} for i, v in enumerate(hours)]
        return {"series": series, "rising": CHILDREN.get(kw, [])}

    def timeseries(self, keywords, time_range):
        self.requests += 2
        kw = keywords[0]
        weekly, daily = SHAPES.get(kw, ([0] * 53, [0] * 31))
        if time_range == "today 12-m":
            return [{"date": d, "values": [v], "partial": i == 52} for i, (d, v) in enumerate(zip(WEEKS, weekly))]
        daily = daily or [50] * 31
        ref = [40] * 31
        return [{"date": d, "values": [v, r] if len(keywords) > 1 else [v], "partial": i == 30}
                for i, (d, v, r) in enumerate(zip(DAYS, daily, ref))]


if __name__ == "__main__":
    # 测试时只查两个词根
    run.rules.load_roots = lambda: (["higgsfield", "ai video"], [])
    run.Runner(client=FakeTrends()).run()
    print((run.rules.ROOT_DIR / "reports" / "latest.md").read_text(encoding="utf-8"))
