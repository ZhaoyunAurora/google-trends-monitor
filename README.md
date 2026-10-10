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
   本仓库的用来推每小时的新词提醒，私有仓库的用来推早晚的 Claude 判断。

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

1. 查每个词根全球、近 7 天的「相关查询 - 搜索量上升」，飙升或涨幅 ≥ 300% 的进队列；新闻、体育、报错、盗版、非英文等先按词面过滤。
2. 从队列里取词（AI 相关、层级浅、涨幅大的优先），像手工一样和 GPTs 一起查近 7 天，得到「vs gpts」，同时拿到它自己的飙升相关词。
   如果它的相关词大多是填字游戏 / 新闻 / 体育之类（比如 yentl setting → crossword clue），这个词直接过滤。
3. 查 12 个月周曲线：之前几乎没量 → 新词；之前有量但最近 6 周峰值是平时的 5 倍以上 → 爆发候选。
4. 新词和爆发候选再看 30 天日曲线：持续上涨 / 只热一两天（短时尖峰）/ 今天刚冒头（待观察，几小时后重查）。
5. 不管这个词合不合格，都把它的飙升相关词放回队列，继续往下挖，直到达到层数或查无可查。查过的词 3 天内不重复查。
6. Google 对请求有限速，程序每 25 秒左右发一次请求（每个词约 5~7 次请求），遇到 429 会退避，连续 4 次就收工，没查完的下次接着查。

本地测试（不联网）：`python -m tests.mock_run`
