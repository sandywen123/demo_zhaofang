# demo_zhaofang

用 TikHub 抓取小红书租房帖，再按你的条件筛成短名单。仓库里带了一个 Cursor Agent Skill，方便在对话里直接「找房」。

## 你需要准备什么

1. **Python 3**，并安装依赖：

```bash
pip install -r requirements.txt
```

2. **TikHub API Key**（[tikhub.io](https://tikhub.io) 申请）  
   在项目根目录创建 **`env.txt`**（不要提交到 git）：

```bash
cp env.txt.example env.txt
# 编辑 env.txt，填入：
# TIKHUB_API_KEY=你的key
```

3. **Cursor**（要用 Skill 时）

## 怎么用这个 Skill

Skill 路径：`.cursor/skills/xhs-rentals-shortlist/`

### 在 Cursor 里

1. 用 Cursor 打开本仓库。
2. 在 Agent 对话里说例如：「用租房 shortlist skill 帮我找房」或「按 xhs-rentals-shortlist 流程找一批帖子」。
3. Agent 会先问你需求（**每人条件不同，不会套用别人的默认偏好**），至少包括：
   - 城市 / 区域（板块、地铁站、通勤点）
   - 房型与面积
   - 预算上限与硬丢线
   - 只要最近几天 / 一周 / 半个月的帖
   - 装修风格、是否必须拎包
4. 可选：朝向、楼龄、黑名单小区、只要业主直租等。
5. Agent 复述条件，你确认后再抓取 → 过滤 → 看封面 → 给你短名单链接。

### Skill 做什么

| 步骤 | 内容 |
|------|------|
| 需求采集 | 问清条件并复述确认 |
| 抓取 | 调 TikHub 搜小红书笔记（`scrape_rentals.py`） |
| 过滤 | 按你的区域、价位、房型等打分 |
| 封面 | 目测装修是否符合你的风格 |
| 交付 | 分层短名单（优先 / 可谈 / 询价）+ 帖子链接 |

过滤规则怎么从口语变成正则，见：  
`.cursor/skills/xhs-rentals-shortlist/criteria.md`

## 不用 Skill、自己跑脚本

```bash
# 近 7 天；关键词换成你的城市/板块/房型
python3 scrape_rentals.py \
  --days 7 \
  --time-filter 一周内 \
  --max-pages 4 \
  --keywords "深圳南山 租房 三房" "前海 三房出租" \
  --out output
```

说明：

- TikHub 的 `time_filter` 只有：`一天内` / `一周内` / `半年内` / `不限`（没有「一个月内」）。
- 要「近 15 天」时用 `--days 15 --time-filter 半年内`，由脚本在本地按发布时间截断。
- 结果在 `output/xhs_rentals_*.json`（该目录已 gitignore）。

## 安全注意

- **`env.txt` / `.env` 不要提交**，已在 `.gitignore`。
- 不要把 API Key、GitHub Token 贴进对话或写进 README / Skill。
- Skill 与脚本都只从 `env.txt` 读 `TIKHUB_API_KEY`。

## 仓库结构（简要）

```
.env.example / env.txt.example   # 密钥模板
scrape_rentals.py                # 主抓取脚本
lookup_note.py                   # 单帖/直租排查示例
.cursor/skills/xhs-rentals-shortlist/
  SKILL.md                       # Agent 主流程
  criteria.md                    # 过滤与打分模板
```
