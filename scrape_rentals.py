#!/usr/bin/env python3
"""
小红书租房帖爬虫（TikHub App V2 search_notes）

目标：深圳南山 / 宝安，近 30 天，三房或大两房。

API 文档: https://docs.tikhub.io/420136398e0
说明：接口 time_filter 只有 一天内 / 一周内 / 半年内，没有「一个月内」，
因此用「半年内」+ 按发布时间倒序，再在本地筛最近 30 天。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.tikhub.io"
SEARCH_PATH = "/api/v1/xiaohongshu/app_v2/search_notes"
IMAGE_DETAIL_PATH = "/api/v1/xiaohongshu/app_v2/get_image_note_detail"
VIDEO_DETAIL_PATH = "/api/v1/xiaohongshu/app_v2/get_video_note_detail"

CST = timezone(timedelta(hours=8))

# 覆盖南山 / 宝安 × 三房 / 大两房 的常见搜索说法
KEYWORDS = [
    "南山租房 三房",
    "南山租房 三室",
    "南山租房 大两房",
    "南山租房 两房两厅",
    "宝安租房 三房",
    "宝安租房 三室",
    "宝安租房 大两房",
    "宝安租房 两房两厅",
    "深圳南山 三房出租",
    "深圳宝安 三房出租",
    "南山区 三房 整租",
    "宝安区 三房 整租",
    "南山 大两房 租房",
    "宝安 大两房 租房",
]

AREA_PATTERNS = [
    # 避免命中杭州「南山路」
    re.compile(r"南山(?!路)|南山区|科技园|蛇口|西丽|南头|海岸城|后海"),
    re.compile(r"宝安|宝中|壹方城|翻身|新安|西乡"),
]

# 三房 / 大两房（避免纯「两房」小户型误伤过多时，仍保留「大两房」明确说法）
ROOM_PATTERNS = [
    re.compile(r"三\s*[房室厅]|3\s*[房室]|三居"),
    re.compile(r"大\s*两\s*[房室]|大两居|两房两厅|两室两厅|2\s*室\s*2\s*厅"),
]

# 明显无关：买卖/外地噪音等
EXCLUDE_PATTERNS = [
    re.compile(r"售|出售|买房|二手房|商铺|写字楼|办公|招租旺铺"),
    re.compile(r"杭州|西湖|吴山|南山路"),
]


@dataclass
class Note:
    note_id: str
    title: str = ""
    desc: str = ""
    note_type: str = ""
    area: str = ""
    room_tag: str = ""
    keyword: str = ""
    author: str = ""
    author_id: str = ""
    liked_count: str = ""
    collected_count: str = ""
    comment_count: str = ""
    share_count: str = ""
    publish_time: str = ""
    publish_ts: int = 0
    ip_location: str = ""
    url: str = ""
    cover: str = ""
    matched_text: str = ""
    raw_search: dict = field(default_factory=dict, repr=False)


class TikHubClient:
    def __init__(self, api_key: str, timeout: float = 45.0, pause: float = 0.6):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "zhaofang-xhs-scraper/1.0",
            }
        )
        self.timeout = timeout
        self.pause = pause

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        # 去掉空值，避免干扰翻页
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        for attempt in range(3):
            resp = self.session.get(url, params=clean, timeout=self.timeout)
            if resp.status_code == 429:
                wait = 2 ** attempt + 1
                print(f"  rate limited, sleep {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")
            if code not in (None, 0, 200):
                raise RuntimeError(f"API error code={code} msg={data.get('message') or data.get('msg')} url={url}?{urlencode(clean)}")
            time.sleep(self.pause)
            return data
        resp.raise_for_status()
        return resp.json()

    def search_notes(
        self,
        keyword: str,
        page: int = 1,
        *,
        sort_type: str = "time_descending",
        note_type: str = "不限",
        time_filter: str = "半年内",
        search_id: str = "",
        search_session_id: str = "",
    ) -> dict[str, Any]:
        return self._get(
            SEARCH_PATH,
            {
                "keyword": keyword,
                "page": page,
                "sort_type": sort_type,
                "note_type": note_type,
                "time_filter": time_filter,
                "search_id": search_id,
                "search_session_id": search_session_id,
            },
        )

    def get_note_detail(self, note_id: str, note_type: str = "") -> dict[str, Any]:
        path = VIDEO_DETAIL_PATH if note_type in ("video", "视频", "视频笔记") else IMAGE_DETAIL_PATH
        try:
            return self._get(path, {"note_id": note_id})
        except Exception:
            # 类型判断不准时互换再试一次
            alt = IMAGE_DETAIL_PATH if path == VIDEO_DETAIL_PATH else VIDEO_DETAIL_PATH
            return self._get(alt, {"note_id": note_id})


def _dig(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is default:
            return default
    return cur


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is None or v == "" or v == []:
            continue
        return v
    return None


def extract_search_items(payload: dict[str, Any]) -> tuple[list[dict], str, str, bool]:
    """从 TikHub 包装层里抽出笔记列表与翻页 id。"""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, dict):
        data = {}

    # 常见嵌套：data.data / data.items / data.notes ...
    candidates: list[Any] = [
        data.get("items"),
        data.get("notes"),
        data.get("note_list"),
        data.get("list"),
        _dig(data, "data", "items"),
        _dig(data, "data", "notes"),
        _dig(data, "data", "note_list"),
        _dig(data, "data", "items"),
        _dig(data, "search", "items"),
        _dig(data, "data", "data", "items"),
    ]

    items: list[dict] = []
    for c in candidates:
        if isinstance(c, list) and c:
            items = [x for x in c if isinstance(x, dict)]
            break

    # 有的返回把 note_card 包在 item 里
    normalized: list[dict] = []
    for it in items:
        note = _first(
            it.get("note"),
            it.get("note_card"),
            it.get("model"),
            it if it.get("note_id") or it.get("id") or it.get("title") else None,
        )
        if isinstance(note, dict):
            # 保留外层可能有的 id
            if not note.get("note_id") and it.get("id"):
                note = {**note, "note_id": it.get("id")}
            if not note.get("note_id") and it.get("note_id"):
                note = {**note, "note_id": it.get("note_id")}
            normalized.append(note)
        elif isinstance(it, dict) and (it.get("note_id") or it.get("id")):
            normalized.append(it)

    search_id = str(
        _first(
            data.get("search_id"),
            data.get("searchId"),
            _dig(data, "data", "search_id"),
            _dig(data, "data", "searchId"),
            "",
        )
        or ""
    )
    session_id = str(
        _first(
            data.get("search_session_id"),
            data.get("session_id"),
            data.get("sessionId"),
            data.get("searchSessionId"),
            _dig(data, "data", "search_session_id"),
            _dig(data, "data", "session_id"),
            _dig(data, "data", "sessionId"),
            "",
        )
        or ""
    )
    has_more_raw = _first(
        data.get("has_more"),
        data.get("hasMore"),
        data.get("next_page"),
        _dig(data, "data", "has_more"),
        _dig(data, "data", "hasMore"),
        _dig(data, "data", "next_page"),
    )
    if has_more_raw is None:
        has_more = bool(normalized)
    else:
        has_more = bool(has_more_raw)
    return normalized, search_id, session_id, has_more


def parse_timestamp(note: dict[str, Any]) -> int:
    raw = _first(
        note.get("time"),
        note.get("timestamp"),
        note.get("create_time"),
        note.get("created_at"),
        note.get("last_update_time"),
        _dig(note, "note_card", "time"),
        _dig(note, "interact_info", "time"),
    )
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        ts = int(raw)
        # 毫秒
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    if isinstance(raw, str) and raw.isdigit():
        ts = int(raw)
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    # 尝试解析日期字符串
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(raw[:19], fmt).replace(tzinfo=CST).timestamp())
        except Exception:
            continue
    return 0


def note_text_blob(note: dict[str, Any]) -> str:
    parts = [
        note.get("title") or "",
        note.get("desc") or note.get("description") or note.get("display_title") or "",
        " ".join(
            t.get("name") or t.get("title") or str(t)
            for t in (note.get("tag_list") or note.get("topics") or [])
            if isinstance(t, (dict, str))
        ),
    ]
    return " ".join(str(p) for p in parts if p)


def detect_area(text: str) -> str:
    hit = []
    # 去掉南山路再判南山，减少外地误伤
    t = text.replace("南山路", "")
    if re.search(r"南山|南山区|科技园|蛇口|西丽|南头|海岸城|后海", t):
        hit.append("南山")
    if re.search(r"宝安|宝中|壹方城|翻身|新安|西乡", text):
        hit.append("宝安")
    return "/".join(hit)


def detect_room(text: str) -> str:
    tags = []
    if ROOM_PATTERNS[0].search(text):
        tags.append("三房")
    if ROOM_PATTERNS[1].search(text):
        tags.append("大两房")
    return "/".join(tags)


def matches_filters(text: str) -> bool:
    if not any(p.search(text) for p in AREA_PATTERNS):
        return False
    if not any(p.search(text) for p in ROOM_PATTERNS):
        return False
    if any(p.search(text) for p in EXCLUDE_PATTERNS):
        return False
    return True


def to_note(raw: dict[str, Any], keyword: str) -> Optional[Note]:
    note_id = str(
        _first(
            raw.get("note_id"),
            raw.get("id"),
            raw.get("noteId"),
            _dig(raw, "note_card", "note_id"),
            "",
        )
        or ""
    )
    if not note_id:
        return None

    title = str(
        _first(
            raw.get("title"),
            raw.get("display_title"),
            raw.get("displayTitle"),
            _dig(raw, "note_card", "display_title"),
            "",
        )
        or ""
    )
    desc = str(_first(raw.get("desc"), raw.get("description"), "") or "")
    ntype = str(_first(raw.get("type"), raw.get("note_type"), "") or "")
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    interact = raw.get("interact_info") if isinstance(raw.get("interact_info"), dict) else {}
    cover = ""
    cover_obj = raw.get("cover")
    if isinstance(cover_obj, dict):
        cover = str(_first(cover_obj.get("url"), cover_obj.get("url_default"), "") or "")
    elif isinstance(cover_obj, str):
        cover = cover_obj
    images = raw.get("image_list") or raw.get("images_list") or []
    if not cover and isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            cover = str(
                _first(
                    first.get("url"),
                    first.get("url_default"),
                    first.get("original"),
                    first.get("url_size_large"),
                    "",
                )
                or ""
            )

    ts = parse_timestamp(raw)
    text = note_text_blob(raw)
    area = detect_area(text)
    room = detect_room(text)

    return Note(
        note_id=note_id,
        title=title,
        desc=desc,
        note_type=ntype,
        area=area,
        room_tag=room,
        keyword=keyword,
        author=str(_first(user.get("nickname"), user.get("nick_name"), "") or ""),
        author_id=str(_first(user.get("user_id"), user.get("userid"), "") or ""),
        liked_count=str(
            _first(raw.get("liked_count"), interact.get("liked_count"), interact.get("like_count"), "") or ""
        ),
        collected_count=str(
            _first(
                raw.get("collected_count"),
                interact.get("collected_count"),
                interact.get("collect_count"),
                "",
            )
            or ""
        ),
        comment_count=str(
            _first(raw.get("comments_count"), raw.get("comment_count"), interact.get("comment_count"), "")
            or ""
        ),
        share_count=str(
            _first(raw.get("shared_count"), raw.get("share_count"), interact.get("share_count"), "") or ""
        ),
        publish_time=datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M:%S") if ts else "",
        publish_ts=ts,
        ip_location=str(raw.get("ip_location") or ""),
        url=f"https://www.xiaohongshu.com/explore/{note_id}",
        cover=cover,
        matched_text=text[:500],
        raw_search=raw,
    )


def enrich_from_detail(client: TikHubClient, note: Note) -> Note:
    try:
        payload = client.get_note_detail(note.note_id, note.note_type)
    except Exception as e:
        print(f"  detail failed {note.note_id}: {e}", file=sys.stderr)
        return note

    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return note

    # 详情常再包一层
    detail = data.get("data") if isinstance(data.get("data"), dict) else data
    if isinstance(detail.get("note"), dict):
        detail = detail["note"]
    if isinstance(detail.get("note_card"), dict):
        detail = detail["note_card"]

    title = str(_first(detail.get("title"), detail.get("display_title"), note.title) or note.title)
    desc = str(_first(detail.get("desc"), detail.get("description"), note.desc) or note.desc)
    ts = parse_timestamp(detail) or note.publish_ts
    text = f"{title} {desc} {note_text_blob(detail)}"
    user = detail.get("user") if isinstance(detail.get("user"), dict) else {}
    interact = detail.get("interact_info") if isinstance(detail.get("interact_info"), dict) else {}

    note.title = title
    note.desc = desc
    note.publish_ts = ts
    note.publish_time = datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M:%S") if ts else note.publish_time
    note.area = detect_area(text) or note.area
    note.room_tag = detect_room(text) or note.room_tag
    note.matched_text = text[:800]
    note.author = str(_first(user.get("nickname"), note.author) or note.author)
    note.author_id = str(_first(user.get("user_id"), note.author_id) or note.author_id)
    note.liked_count = str(_first(interact.get("liked_count"), note.liked_count) or note.liked_count)
    note.collected_count = str(_first(interact.get("collected_count"), note.collected_count) or note.collected_count)
    note.comment_count = str(_first(interact.get("comment_count"), note.comment_count) or note.comment_count)
    note.ip_location = str(detail.get("ip_location") or note.ip_location)
    return note


def search_keyword(
    client: TikHubClient,
    keyword: str,
    *,
    max_pages: int,
    cutoff_ts: int,
    time_filter: str,
) -> list[Note]:
    print(f"\n== keyword: {keyword} ==")
    found: list[Note] = []
    search_id = ""
    session_id = ""
    older_streak = 0

    for page in range(1, max_pages + 1):
        print(f"  page {page} ...")
        try:
            payload = client.search_notes(
                keyword,
                page=page,
                sort_type="time_descending",
                time_filter=time_filter,
                search_id=search_id,
                search_session_id=session_id,
            )
        except Exception as e:
            print(f"  search error: {e}", file=sys.stderr)
            break

        items, sid, sess, has_more = extract_search_items(payload)
        if sid:
            search_id = sid
        if sess:
            session_id = sess

        if not items:
            # 调试：第一页空结果时落盘原始响应
            if page == 1:
                safe_kw = re.sub(r"\W+", "_", keyword)[:40]
                debug_path = Path("output") / f"debug_empty_{safe_kw}.json"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  empty page, raw saved to {debug_path}")
            break

        page_notes = 0
        for raw in items:
            note = to_note(raw, keyword)
            if not note:
                continue
            # 时间：有时间戳则严格 30 天；无时间戳先留下，详情里再判
            if note.publish_ts and note.publish_ts < cutoff_ts:
                older_streak += 1
                continue
            older_streak = 0
            text = note.matched_text
            if not matches_filters(text):
                continue
            found.append(note)
            page_notes += 1

        print(f"  got {len(items)} items, matched {page_notes} (total {len(found)})")

        # 按时间倒序：连续多条过期则后面大概率更旧
        if older_streak >= 8:
            print("  reached notes older than 30 days, stop paging")
            break
        if not has_more:
            break

    return found


def save_outputs(notes: Iterable[Note], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"xhs_rentals_{stamp}.json"
    csv_path = out_dir / f"xhs_rentals_{stamp}.csv"

    rows = []
    for n in notes:
        d = asdict(n)
        d.pop("raw_search", None)
        rows.append(d)

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "note_id",
        "title",
        "desc",
        "area",
        "room_tag",
        "publish_time",
        "author",
        "liked_count",
        "collected_count",
        "comment_count",
        "url",
        "keyword",
        "ip_location",
        "cover",
        "matched_text",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    return json_path, csv_path


def dedupe(notes: list[Note]) -> list[Note]:
    seen: dict[str, Note] = {}
    for n in notes:
        prev = seen.get(n.note_id)
        if not prev or (n.publish_ts and n.publish_ts > (prev.publish_ts or 0)):
            seen[n.note_id] = n
    return sorted(seen.values(), key=lambda x: x.publish_ts or 0, reverse=True)


def load_api_key() -> str:
    """优先读项目根目录 env.txt（TIKHUB_API_KEY=...），其次 .env / 环境变量。"""
    root = Path(__file__).resolve().parent
    env_txt = root / "env.txt"
    if env_txt.is_file():
        load_dotenv(env_txt, override=True)
    else:
        load_dotenv(root / ".env")
    return os.getenv("TIKHUB_API_KEY", "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="爬取小红书南山/宝安租房帖（TikHub）")
    parser.add_argument("--days", type=int, default=30, help="最近 N 天（默认 30）")
    parser.add_argument("--max-pages", type=int, default=5, help="每个关键词最多翻页数")
    parser.add_argument("--keywords", nargs="*", help="自定义关键词，覆盖默认列表")
    parser.add_argument("--time-filter", default="半年内", choices=["一天内", "一周内", "半年内", "不限"])
    parser.add_argument("--fetch-detail", action="store_true", help="拉详情补全文（更准，更费额度）")
    parser.add_argument("--out", default="output", help="输出目录")
    parser.add_argument("--pause", type=float, default=0.6, help="请求间隔秒")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key or api_key == "your_api_key_here":
        print(
            "请先设置 TIKHUB_API_KEY：\n"
            "  1. cp env.txt.example env.txt\n"
            "  2. 在 env.txt 填入 https://tikhub.io 的 API Key\n"
            "  或: export TIKHUB_API_KEY=...",
            file=sys.stderr,
        )
        return 1

    keywords = args.keywords or KEYWORDS
    cutoff = datetime.now(CST) - timedelta(days=args.days)
    cutoff_ts = int(cutoff.timestamp())
    print(f"cutoff: {cutoff.strftime('%Y-%m-%d %H:%M:%S')} CST ({args.days} days)")
    print(f"keywords: {len(keywords)}, max_pages={args.max_pages}, time_filter={args.time_filter}")

    client = TikHubClient(api_key, pause=args.pause)
    all_notes: list[Note] = []
    for kw in keywords:
        all_notes.extend(
            search_keyword(
                client,
                kw,
                max_pages=args.max_pages,
                cutoff_ts=cutoff_ts,
                time_filter=args.time_filter,
            )
        )

    notes = dedupe(all_notes)
    print(f"\ndeduped candidates: {len(notes)}")

    if args.fetch_detail and notes:
        print("fetching details...")
        enriched: list[Note] = []
        for i, n in enumerate(notes, 1):
            print(f"  [{i}/{len(notes)}] {n.note_id}")
            n = enrich_from_detail(client, n)
            text = n.matched_text or f"{n.title} {n.desc}"
            if n.publish_ts and n.publish_ts < cutoff_ts:
                continue
            if not matches_filters(text):
                continue
            enriched.append(n)
        notes = enriched
        print(f"after detail filter: {len(notes)}")

    # 无时间戳的帖子：若开了详情仍无时间，默认保留并标注
    final = []
    for n in notes:
        if n.publish_ts and n.publish_ts < cutoff_ts:
            continue
        final.append(n)

    json_path, csv_path = save_outputs(final, Path(args.out))
    print(f"\n完成：{len(final)} 条")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    for n in final[:15]:
        print(f"  - [{n.area}|{n.room_tag}] {n.publish_time} {n.title[:40]} {n.url}")
    if len(final) > 15:
        print(f"  ... 另有 {len(final) - 15} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
