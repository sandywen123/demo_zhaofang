#!/usr/bin/env python3
"""Fetch one XHS note and search for owner direct-rent posts."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scrape_rentals import (  # noqa: E402
    TikHubClient,
    extract_search_items,
    load_api_key,
    matches_filters,
    to_note,
)

NOTE_ID = "6a8a7b44000000002202de35"
CHECK_IDS = [
    "6a82ab9d000000002501561e",
    "6a59857b00000000060111e2",
    "6a52d30d000000001702fc5f",
]

OWNER_HINTS = re.compile(
    r"(业主直租|房东直租|个人转租|个人出租|业主出租|自家|自住|无中介|0中介|免中介|本人出租|本人转租|房东本人)"
)
AGENT_HINTS = re.compile(
    r"(中介|经纪|代理|置业|地产|房屋管家|托管|公寓管家|看房联系|随时看房|密码看房|钥匙在手|专业租房)"
)


def extract_note(payload: dict) -> dict:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict) and "data" in data:
        inner = data["data"]
        if isinstance(inner, list) and inner:
            inner = inner[0]
        if isinstance(inner, dict):
            data = inner
    if isinstance(data, dict):
        return data.get("note") or data.get("note_detail") or data
    return {}


def main() -> int:
    api_key = load_api_key()
    if not api_key:
        print("缺少 env.txt 中的 TIKHUB_API_KEY", file=sys.stderr)
        return 1
    client = TikHubClient(api_key)
    detail = client.get_note_detail(NOTE_ID, "video")
    note = extract_note(detail)
    title = note.get("title") or ""
    desc = note.get("desc") or ""
    user = note.get("user") or {}
    text = f"{title} {desc}"

    print("=== TARGET NOTE ===")
    print("id:", NOTE_ID)
    print("title:", title)
    print("author:", user.get("nickname"), user.get("user_id"))
    print("desc:", desc[:800])
    print("url:", f"https://www.xiaohongshu.com/explore/{NOTE_ID}")

    print("\n=== LIVE CHECK CANDIDATES ===")
    for cid in CHECK_IDS:
        detail = client.get_note_detail(cid, "video")
        cnote = extract_note(detail)
        cuser = cnote.get("user") or {}
        print("-", cid)
        print("  title:", cnote.get("title"))
        print("  author:", cuser.get("nickname"))
        print("  desc:", (cnote.get("desc") or "")[:220])
        print("  url:", f"https://www.xiaohongshu.com/explore/{cid}")

    # community keywords from title/desc
    community_patterns = [
        r"[\u4e00-\u9fffA-Za-z0-9·]{2,12}(?:公馆|花园|国际|中心|臻邸|天境|锦庭|茗荟|海岸|公馆|小区|府|苑|城|湾|邸|里|府)",
    ]
    communities = []
    for pat in community_patterns:
        communities.extend(re.findall(pat, text))
    communities = list(dict.fromkeys(communities))[:8]

    # fallback tokens
    tokens = []
    for kw in ["海纳", "壹方", "前海", "宝中", "都市茗荟", "云玺", "天境", "一湾", "后海", "登良", "海岸城", "大新", "桂湾", "前湾"]:
        if kw in text:
            tokens.append(kw)
    search_terms = []
    for c in communities[:3]:
        search_terms.append(f"{c} 业主直租 三房")
        search_terms.append(f"{c} 房东直租 三房")
    for t in tokens[:4]:
        search_terms.append(f"{t} 业主直租 三房")
        search_terms.append(f"{t} 个人转租 三房")
    search_terms = list(dict.fromkeys(search_terms))[:12]

    print("\nsearch terms:", search_terms)

    hits = []
    seen = {NOTE_ID}
    for kw in search_terms:
        payload = client.search_notes(keyword=kw, page=1, sort_type="time_descending", time_filter="半年内")
        items, _, _, _ = extract_search_items(payload)
        for raw in items:
            n = to_note(raw, kw)
            if not n or n.note_id in seen:
                continue
            seen.add(n.note_id)
            blob = f"{n.title} {n.desc} {n.matched_text}"
            if not matches_filters(blob):
                continue
            owner_score = len(OWNER_HINTS.findall(blob))
            agent_score = len(AGENT_HINTS.findall(blob))
            same_comm = any(c in blob for c in communities) or any(t in blob for t in tokens)
            if owner_score == 0 and not re.search(r"个人转租|房东|业主", blob):
                continue
            hits.append(
                {
                    "note_id": n.note_id,
                    "title": n.title,
                    "desc": (n.desc or "")[:200],
                    "author": n.author,
                    "url": n.url,
                    "keyword": kw,
                    "owner_score": owner_score,
                    "agent_score": agent_score,
                    "same_community": same_comm,
                }
            )

    hits.sort(key=lambda x: (-x["owner_score"], -x["same_community"], x["agent_score"]))
    out = Path("output/owner_lookup_6a8a7b44.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "target": {
                    "note_id": NOTE_ID,
                    "title": title,
                    "desc": desc,
                    "author": user.get("nickname"),
                    "communities": communities,
                    "tokens": tokens,
                },
                "owner_candidates": hits,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n=== OWNER CANDIDATES ({len(hits)}) ===")
    for h in hits[:15]:
        print(
            f"- [{h['owner_score']}o/{h['agent_score']}a] {h['title'][:50]} | {h['author']} | {h['url']}"
        )
    print("saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
