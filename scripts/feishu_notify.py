"""把最新的 Claude 判断报告推送到飞书群机器人。需要仓库 Secret：FEISHU_WEBHOOK（可选 FEISHU_SECRET 签名校验）。"""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.request

hook = os.getenv("FEISHU_WEBHOOK", "").strip()
if not hook:
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

# 只推「不做」之前的部分，太长就截断，完整版看链接
body = text.split("\n## 不做")[0].strip()
if len(body) > 3500:
    body = body[:3500] + "\n……"
repo = os.getenv("GITHUB_REPOSITORY", "")
link = f"https://github.com/{repo}/blob/main/{path}"
msg = {"msg_type": "text", "content": {"text": f"{body}\n\n完整报告：{link}"}}

secret = os.getenv("FEISHU_SECRET", "").strip()
if secret:
    ts = str(int(time.time()))
    sign = base64.b64encode(hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()
    msg.update(timestamp=ts, sign=sign)

req = urllib.request.Request(hook, data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=20).read().decode())
