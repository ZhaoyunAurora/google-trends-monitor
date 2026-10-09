# Google Trends 新词监控

GitHub Actions 按手工找词的方式自动跑（全部是**全球**数据）：
词根 → 相关查询里的飙升词 → 每个飙升词和 GPTs 对比、看 12 个月 / 30 天 / 7 天曲线 → 再看这个词自己的飙升相关词 → 一层层往下挖（默认挖 3 层）。
每个词被判成「新词 / 老词二次爆火 / 待观察 / 短时尖峰 / 老词」，结果直接提交回这个仓库。
Claude 定时任务每天读结果，判断哪些词值得建站或加内页，写到 `reviews/`。全程免费。

## 每天看哪里

| 文件 | 内容 |
|---|---|
| `reviews/YYYY-MM-DD.md` | Claude 的判断：建议做什么、SERP、域名、模型、评分 |
| `reports/latest.md` | 当天的完整日报（GitHub 网页上直接打开就是表格） |
| `data/latest.json` | 给 Claude 读的精简数据 |
| `data/state.json`、`data/daily/` | 程序内部状态，不用管 |

## 第一次设置（约 5 分钟）

1. GitHub 新建仓库（建议 **Public**：公开仓库 Actions 不限时长，可以每小时跑 50 分钟；私有仓库每月只有 2000 免费分钟，一天只能跑一次，见下方）。
2. 把这个文件夹里的所有文件上传到仓库根目录，**包括 `.github` 文件夹**（网页上传时直接把整个文件夹拖进去；如果看不到 `.github`，在电脑上打开"显示隐藏文件"）。
3. 仓库 → Settings → Actions → General → 最下面 Workflow permissions 选 **Read and write permissions** → Save。（工作流文件里已经声明了写权限，一般不用改；如果第一次运行在"提交结果"那步报 403，就是这里没开。）
4. 仓库 → Actions → 左边 trends-monitor → Run workflow，手动跑一次。跑完后仓库里会多出 `data/` 和 `reports/`。
5. 之后它会按时间自动跑，不用管。

### 私有仓库

打开 `.github/workflows/trends.yml`，把
`- cron: "7 * * * *"` 改成 `- cron: "7 13 * * *"`，`RUN_MINUTES` 的 `'50'` 改成 `'60'`（一天一次，每月约 1900 分钟）。
代价是每天只能查约 1/20 的量，往下挖不了几层。

## 推送到飞书群（可选）

1. 飞书群 → 设置 → 群机器人 → 添加「自定义机器人」，复制 Webhook 地址（开了签名校验的话也复制密钥）。
2. 仓库 → Settings → Secrets and variables → Actions → New repository secret：名字 `FEISHU_WEBHOOK`，值填 Webhook 地址；有密钥再加一个 `FEISHU_SECRET`。
3. 之后 Claude 每天写完 `reviews/` 里的判断，会自动推到群里。想测试：Actions → feishu-notify → Run workflow。

## 调整

| 想做的事 | 改哪里 |
|---|---|
| 加/删词根 | `config/roots.txt`：`[daily]` 每天必查，`[rotate]` 轮流查 |
| 某类垃圾词总冒出来 | `config/filters.txt` 加一行 `原因 \| 正则` |
| 有词被误杀 | `config/allow.txt` 写上这个词 |
| 门槛 | `trends.yml` 里的 `CANDIDATE_MIN`（上升多少 % 才往下看，默认 300，「飙升」一律看） |
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
