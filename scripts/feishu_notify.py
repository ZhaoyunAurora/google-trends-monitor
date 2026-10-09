"""把最新的 Claude 判断报告推送到飞书群机器人。需要仓库 Secret：FEISHU_WEBHOOK（可选 FEISHU_SECRET）。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitor import feishu  # noqa: E402

if not os.getenv("FEISHU_WEBHOOK", "").strip():
    print("没有设置 FEISHU_WEBHOOK，跳过推送")
    sys.exit(0)

changed = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD", "--", "reviews/"],
                         capture_output=True, text=True).stdout.split()
files = sorted(f for f in changed if f.endswith(".md")) or sorted(
    f"reviews/{x}" for x in os.listdir("reviews") if x.endswith(".md"))
if not files:
    print("没有报告")
    sys.exit(0)
path = files[-1]
text = open(path, encoding="utf-8").read()
body = text.split("\n## 不做")[0].strip()  # 只推「不做」之前的部分
if len(body) > 3500:
    body = body[:3500] + "\n……"
link = f"https://github.com/{os.getenv('GITHUB_REPOSITORY', '')}/blob/main/{path}"
feishu.send(f"{body}\n\n完整报告：{link}")
