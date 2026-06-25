"""
search.py
職責：所有 yt-dlp 搜索邏輯，包含漏斗式三層搜索策略
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SEARCH_PER_QUERY, FUNNEL_THRESHOLD, TW_MEDIA, ytdlp_proxy_args


def search_one_query(query: str, count: int = SEARCH_PER_QUERY) -> list[dict]:
    """單次 yt-dlp 搜索，返回視頻元數據列表"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    cmd = [
        sys.executable, "-m", "yt_dlp",
        f"ytsearch{count}:{query}",
        "--dump-json",
        "--no-download",
        "--quiet",
        "--no-warnings",
        *ytdlp_proxy_args(),
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=False, timeout=60, env=env
    )
    stdout = result.stdout.decode("utf-8", errors="ignore")

    videos = []
    for line in stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            video_id = data.get("id", "")
            url = (
                data.get("webpage_url")
                or data.get("url")
                or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
            )
            if not url:
                continue
            videos.append({
                "id":          video_id,
                "title":       data.get("title", "無標題"),
                "description": (data.get("description") or "")[:400],
                "url":         url,
                "duration":    data.get("duration"),
                "view_count":  data.get("view_count"),
                "uploader":    data.get("uploader") or data.get("channel", ""),
                "upload_date": data.get("upload_date", ""),
            })
        except Exception:
            continue

    print(f"[yt-dlp] 「{query}」→ {len(videos)} 條")
    return videos


def search_one_layer(layer_query: str, seen_ids: set) -> list[dict]:
    """搜索單層：基礎查詢 + 並發 8 路媒體組合查詢"""
    queries = [layer_query] + [f"{layer_query} {m}" for m in TW_MEDIA]
    new_videos = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(search_one_query, q): q for q in queries}
        for future in as_completed(future_map):
            try:
                for v in future.result():
                    if v["id"] and v["id"] not in seen_ids:
                        seen_ids.add(v["id"])
                        new_videos.append(v)
            except Exception as e:
                print(f"[搜索失敗] {future_map[future]}: {e}")

    print(f"[Layer] 「{layer_query}」新增 {len(new_videos)} 條")
    return new_videos


def search_youtube_funnel(keywords: dict) -> list[dict]:
    """
    漏斗式三層搜索：
    layer1（最精準）→ layer2 → layer3（最寬）
    候選池達到 FUNNEL_THRESHOLD 即停止
    """
    layers = [keywords["layer1"], keywords["layer2"], keywords["layer3"]]
    pool = []
    seen_ids = set()

    for i, layer_query in enumerate(layers, start=1):
        new_videos = search_one_layer(layer_query, seen_ids)
        pool.extend(new_videos)
        print(f"[漏斗] 第{i}層完畢，候選池共 {len(pool)} 條")

        if len(pool) >= FUNNEL_THRESHOLD:
            print(f"[漏斗] 達到閾值 {FUNNEL_THRESHOLD}，停止搜索")
            break

    print(f"[漏斗] 最終候選池 {len(pool)} 條")
    return pool
