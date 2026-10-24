---
name: xhs-rentals-shortlist
description: >-
  Collects rental preferences then scrapes and shortlists Xiaohongshu posts via
  TikHub. Use when the user asks to find 租房, 小红书房源, refresh a rental
  shortlist, filter XHS rentals, or run scrape_rentals.py.
---

# 小红书租房短名单

TikHub 搜小红书租房帖 → **按用户自述条件**筛选 → 封面目测 → 输出短名单。

**禁止**套用他人/历史会话的地区、价位、房型。每次任务先完成「需求采集」；条件不全则先问清再抓取。

## 前提（必须）

项目根目录有 **`env.txt`**（勿把真实 key 写进 skill 或提交 git）：

```
TIKHUB_API_KEY=<从 tikhub.io 申请的 key>
```

```bash
test -f env.txt && grep -q '^TIKHUB_API_KEY=.\+' env.txt && echo ok || echo '缺少 env.txt'
```

缺失则停，请用户自建；**不要**在对话/文件中回显 key。脚本 `load_dotenv("env.txt")`。

## 步骤 0：需求采集（先做）

若用户未一次说清，**主动追问**（可用列表一次问完）。至少凑齐下面「必填」再 scrape。

### 必填

| 项 | 问法示例 | 落到执行 |
|----|----------|----------|
| **城市/区域** | 哪个城市？哪些板块/地铁站/通勤点？ | 搜索关键词 + ZONE_OK |
| **房型** | 几房几卫？面积下限？ | ROOM 正则；关键词加「三房」等 |
| **预算** | 月租上限？可接受浮动？硬丢线？ | 解析价格；OVER_BUDGET |
| **时间段** | 只要近几天/一周/半个月的帖？ | `--days` + `time_filter` 映射 |
| **装修/家具** | 精装？现代/轻奢？必须拎包？能否空房？ | 封面规则 + 文案加权 |

### 选填（有则更好）

| 项 | 问法示例 |
|----|----------|
| **朝向** | 要朝南/南北通吗？ |
| **楼龄** | 次新？几年以内？ |
| **黑名单** | 不想要的小区、噪音盘、偏远片区？ |
| **来源偏好** | 只要业主直租，还是中介也可以？ |
| **其它** | 车位、学区、宠物、地铁步行分钟数等 |

用户回复后，在对话里用简表**复述确认**（一屏即可），例如：

```
本次条件：
- 区域：…
- 房型/面积：…
- 预算：≤…（硬丢 ≥…）
- 时间：近 … 天
- 装修：…
- 加分/排除：…
确认后开始抓取。
```

用户改口则以最新说法为准，并写进本次过滤脚本；**不要**静默沿用旧 brief。

模板与正则拼法见 [criteria.md](criteria.md)。

## 工作流

```
- [ ] 0. 需求采集并复述确认
- [ ] 1. 确认 env.txt
- [ ] 2. API smoke（关键词用用户区域）
- [ ] 3. 按 brief 抓取
- [ ] 4. 按 brief 过滤打分
- [ ] 5. 按装修偏好目测封面
- [ ] 6. 输出短名单
```

### 1. Smoke

```bash
python3 - <<'PY'
import os, requests
from dotenv import load_dotenv
load_dotenv("env.txt")
key = os.environ["TIKHUB_API_KEY"]
# keyword 换成用户区域+房型，例如「上海 徐汇 两房」
kw = "USER_AREA 租房 USER_ROOMS"
r = requests.get(
    "https://api.tikhub.io/api/v1/xiaohongshu/app_v2/search_notes",
    headers={"Authorization": f"Bearer {key}"},
    params={"keyword": kw, "page": 1, "sort_type": "time_descending", "time_filter": "一周内"},
    timeout=45,
)
print(r.status_code, len(r.text))
PY
```

- `200` → 继续  
- 代理失败 → `Session(trust_env=False)` 直连，或等用户修代理  
- 其它非 200 → 停并报告，勿刷额度  

### 2. 抓取

`scrape_rentals.py`；关键词与天数来自 brief，勿用仓库默认南山/宝安列表（除非用户就是要那片）。

```bash
# 把关键词换成用户区域 × 房型；time_filter 按「时间段映射」
python3 scrape_rentals.py \
  --days N \
  --time-filter 一周内 \
  --max-pages 4 \
  --keywords "区域 租房 三房" "板块 三房出租" \
  --out output
```

**时间段映射**（接口没有「3天内/一个月内」）：

| 用户要 | `--days` | `--time-filter` |
|--------|----------|-----------------|
| 近 1 天 | 1 | `一天内` |
| 近 2～7 天 | N | `一周内` |
| 近 8～30 天等 | N | `半年内` + 本地 cutoff |
| 不限 | 很大或不筛 | `不限` 或 `半年内` |

其它：`time_filter` 仅 `一天内|一周内|半年内|不限`；翻页 `search_id` 偶发 400 可跳过该词；产出 `output/xhs_rentals_*.json`。

### 3. 过滤打分

按**本次 brief** 生成 ZONE/ROOM/预算/黑名单等规则（见 criteria.md），跑本地脚本。写出：

- `output/shortlist_<tag>.json`
- `output/shortlist_<tag>_final.json`（建议含 `brief` 字段记录条件）

### 4. 封面目测

按用户说的装修风格判断，例如：

- 要现代精装 → 丢旧风/藤编欧式过时、脏乱  
- 要拎包 → 空房硬装降权或丢  
- 未指定风格 → 只排除明显不宜居住，少做审美替用户做主  

封面下载失败则靠文案，标注「未见图」。

### 5. 交付

对照**用户自己的**条件分层：

```markdown
### 优先看
1. **小区·板块** · 面积 · 朝向 · 价格 · 为何符合你的条件
   URL

### 可谈
...

### 询价（需确认是否在预算内）
...

已丢（相对你的条件）：…
```

勿贴 API key；勿大段 dump 原始 JSON。

## 常见坑

| 坑 | 处理 |
|----|------|
| 未采集需求就开爬 | 停，先问步骤 0 |
| 详情 note id 回收 | 搜索标题≠详情时以搜索文案为准 |
| 外地同名地标 | 按用户城市黑外地；看出发地/IP/文案 |
| 「询价」帖 | 从正文挖数字；超用户硬丢线仍丢 |
| 额度 | 少 `--fetch-detail`；先筛再按需查单帖 |

## 单帖深挖

有 note id / 找业主直租：`env.txt` → detail API → 搜「小区名 业主直租」；区分中介话术与房东话术。
