# 从用户 brief 生成过滤规则

**不要**复制下面示例里的具体地名/价位当默认。每次用用户刚确认的 brief 填空。

## 1. 把口语变成字段

```json
{
  "city": "深圳",
  "zones_ok": ["前海", "桂湾", "大新"],
  "zones_bad": ["海纳公馆", "赤湾"],
  "rooms": "三房两卫",
  "area_min_sqm": 90,
  "budget_prefer_max": 12000,
  "budget_hard_drop": 12500,
  "days": 7,
  "orient_ok": ["朝南", "南北通", "东南", "西南"],
  "age_max_years": 10,
  "furnished": "required",
  "decor_style": "现代简约/轻奢",
  "owner_only": false,
  "extra": []
}
```

缺必填项 → 回到 SKILL 步骤 0，先问用户。

## 2. 由字段拼正则（示例写法）

```python
import re

def alt(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in words if w)

# 来自 brief，勿写死
zones_ok = [...]   # brief.zones_ok
zones_bad = [...]  # brief.zones_bad + 常见误伤（买卖/外地同城名）
room_words = [...] # 如 ["三房", "三室", "3房", "三居"]
orient_words = brief.get("orient_ok") or []

ZONE_OK = re.compile(alt(zones_ok)) if zones_ok else None
ZONE_BAD = re.compile(alt(zones_bad + ["出售", "二手房", "商铺"]))
ROOM = re.compile(alt(room_words))
ORIENT_OK = re.compile(alt(orient_words)) if orient_words else None

AGE_GOOD = re.compile(r"(次新|新盘|20(1[6-9]|2[0-6]))")  # 若用户要楼龄再启用
AGE_BAD = re.compile(r"(房龄|楼龄).{0,6}(1[1-9]|[2-9]\d)|老破|筒子楼")
FURNISHED = re.compile(r"(家私|家电|全齐|拎包|家具齐全)")
EMPTY = re.compile(r"(空房|硬装交付|毛坯|无家具)")
OWNER = re.compile(r"(业主直租|房东直租|个人出租|免中介)")
AGENT = re.compile(r"(中介|经纪|置业顾问)")
```

**预算**：从文案解析 `(\d{4,5})\s*元?/?月`、`(\d(?:\.\d)?)\s*万`、`(\d{1,2})\s*[kK]`。  
`price >= budget_hard_drop` → 剔除；`price <= budget_prefer_max` → 加分。  
用户没给硬丢线时，可用 `prefer_max * 1.05` 或再问一句。

## 3. 打分（按 brief 开关）

起点 0：

| 条件 | 建议 |
|------|------|
| 发布在 `--days` 内且越新 | +1～3 |
| 命中 ZONE_OK | +2 |
| 命中 ROOM / 面积 | +1～2 |
| ORIENT_OK（若用户要求） | +2 |
| 楼龄符合（若要求） | +2 |
| 家具符合 furnished | +1 |
| 价 ≤ prefer_max | +1 |
| EMPTY 但用户要拎包 | −2 或剔除 |
| ZONE_BAD / 超 hard_drop | 剔除 |
| owner_only 且像中介 | 降权或剔除 |

阈值自定；高分进封面目测，目测规则跟 `decor_style` 走。

## 4. 搜索关键词

由 `city` + `zones_ok` + 房型词组合 6～15 个，例如：

- `"{zone} 租房 {room}"`
- `"{city}{zone} {room} 出租"`
- `"{metro_station} 租房 {room}"`（用户若提了地铁站）

交给：`python3 scrape_rentals.py --keywords ...`

## 5. 终稿 JSON

```json
{
  "brief": { "...": "本次确认的条件" },
  "items": [
    {
      "tier": "优先|可谈|询价",
      "days": 0.2,
      "community": "",
      "price": null,
      "size": "",
      "orient": "",
      "note": "对照 brief 的一句话",
      "url": "https://www.xiaohongshu.com/explore/<note_id>"
    }
  ],
  "dropped_summary": ["…"]
}
```

`note_id` 用搜索结果里的 `id` / `note_id`。
