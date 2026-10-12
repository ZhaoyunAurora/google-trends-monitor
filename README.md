# Google Trends 新词监控

GitHub Actions 按手工找词的方式自动跑（全部是**全球**数据）：
词根 → 相关查询里的飙升词 → 每个飙升词和 GPTs 对比、看 12 个月 / 30 天 / 7 天曲线 → 再看这个词自己的飙升相关词 → 一层层往下挖（默认挖 3 层）。
每个词被判成「新词 / 老词二次爆火 / 待观察 / 短时尖峰 / 老词」，结果直接提交回这个仓库。
结果写到你的**私有仓库** `google-trends-data`，外人看不到；这个公开仓库只放代码，运行日志里也不打印关键词。
Claude 定时任务每天北京时间 7:20、19:20 读私有仓库里的结果，判断哪些词值得建站或加内页，写回私有仓库的 `reviews/`，并推送到飞书群。

## 设置

1. 新建**私有**仓库 `google-trends-data`（创建时勾选 Add a README）。
2. 生成令牌：头像 → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token
   - Repository access 选 Only select repositories → `google-trends-data`
   - Permissions → Repository permissions → **Contents: Read and write**
3. 本仓库 → Settings → Secrets and variables → Actions → New repository secret：`DATA_REPO_TOKEN` = 上面的令牌。
4. 飞书（可选）：在**两个仓库**都加 Secret `FEISHU_WEBHOOK`（开了签名校验再加 `FEISHU_SECRET`）。
   本仓库的用来推新词汇总（每 6 小时一次，北京时间 1、7、13、19 点后），私有仓库的用来推早晚的 Claude 判断。

没有 `DATA_REPO_TOKEN` 时工作流不会运行，结果不会写进公开仓库。

## 运行方式

GitHub 的定时触发很不准，所以工作流是「接力」跑的：每次跑约 12 分钟，结束时自己触发下一次（每次换一台机器，减少 Google 限速）。
定时（每 30 分钟）只是保险，接力断了会重新接上。
想暂停：仓库 Settings → Secrets and variables → Actions → Variables 新建变量 `CHAIN` = `off`（删掉变量即恢复）；或者在 Actions 页面直接 Disable workflow。

## 调整

| 想做的事 | 改哪里 |
|---|---|
| 加/删词根 | `config/roots.txt`：`[daily]` 每天必查，`[rotate]` 轮流查 |
| 某类垃圾词总冒出来 | `config/filters.txt` 加一行 `原因 \| 正则` |
| 有词被误杀 | `config/allow.txt` 写上这个词 |
| 门槛 | `.github/workflows/trends.yml` 里的 `CANDIDATE_MIN`（上升多少 % 才往下看，默认 300，「飙升」一律看） |
| 挖几层 | `MAX_DEPTH`（默认 3） |
| 跑得太慢 / 老被 429 | `REQUEST_INTERVAL` 调大（默认 25 秒一次请求） |

改完直接在 GitHub 网页上编辑提交即可，下次运行生效。

## 原理（简要）

- **第 0 层**：所有词根每天查一遍全球近 7 天「相关查询 - 搜索量上升」，「飙升」或涨幅 ≥ 500% 的进入第 1 层（过滤新闻、体育、谜题答案、破解外挂、人物百科等）。
- **第 1~4 层的每个词**：
  1. 和 GPTs 一起看近 7 天，同时拿到它自己的上升相关词（3 个请求）→ GPTs 倍数、估算日搜（倍数 × 5000）。
  2. 不管它本身新不新，「飙升」或 ≥ 500% 的相关词都进入下一层，最多 4 层；相关词全是谜题答案 / 新闻等垃圾的，这条线剪掉。
  3. 估算日搜 ≥ 100 次或 7 天在涨，再单独看 1 个月（2 个请求）→ 新词 / 老词二次爆火 / 今天刚冒头 / 短时尖峰 / 老词，起来时间、峰值日、现在是峰值的百分之几。
- **跨天追踪**：每个词第一次上榜的日期、连续几天 / 一共几天出现在上升列表。
- **推送**：新词、老词二次爆火估算日搜 ≥ 250 次；今天刚冒头的 ≥ 100 次（标 🆕）。每 6 小时汇总一次。
- **查询顺序**：AI 视频/图片 > AI 工具 > 工具站 > 小游戏 > 其他 > 游戏攻略；每 3 个名额留 1 个给非 AI 方向。超过 7 天没轮到的词丢掉。
- 限速：8 秒一次起步，被限速自动放慢；每次跑约 12 分钟后接力触发下一次（换机器、换 IP）。

本地测试（不联网）：`python -m tests.mock_run`
