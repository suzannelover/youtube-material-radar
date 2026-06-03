"""
filter.py
職責：時間過濾 + Qwen 智能篩選推薦卡片
"""

import json
from datetime import datetime, timedelta
from openai import OpenAI

from config import QWEN_API_KEY, TARGET_CARD_COUNT


_client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


# ── 工具函數 ──────────────────────────────────────────────────────────────────

def _fmt_duration(v: dict) -> str:
    d = v.get("duration")
    if not d:
        return "未知時長"
    m, s = divmod(int(d), 60)
    return f"{m}分{s}秒"


def _fmt_date(v: dict) -> str:
    d = v.get("upload_date", "")
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d or "未知日期"


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── 主函數 ────────────────────────────────────────────────────────────────────

def filter_by_date(videos: list[dict], days: int) -> list[dict]:
    """按上傳日期過濾，days=0 表示不限"""
    if days == 0:
        print("[時間過濾] 不限時間，跳過")
        return videos

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    filtered = [v for v in videos if v.get("upload_date", "") >= cutoff]
    print(f"[時間過濾] {len(videos)} → {len(filtered)} 條（近{days}天，截止{cutoff}）")

    if not filtered:
        raise ValueError(f"近{days}天內無相關視頻，請選擇更長時間範圍")

    return filtered


def analyze_and_filter(user_input: str, videos: list[dict]) -> list[dict]:
    """調用 Qwen 從候選池中篩選推薦卡片"""
    video_list_text = ""
    for i, v in enumerate(videos):
        video_list_text += (
            f"[{i}] 標題：{v['title']}\n"
            f"    上傳者：{v.get('uploader', 'Unknown')}\n"
            f"    上傳日期：{_fmt_date(v)}\n"
            f"    時長：{_fmt_duration(v)}\n"
            f"    描述：{v['description'] or '（無描述）'}\n"
            f"    連結：{v['url']}\n\n"
        )

    prompt = f"""
你是一位視頻素材顧問。用戶正在尋找適合以下主題的 YouTube 視頻素材：
「{user_input}」

以下是搜索到的候選視頻：
{video_list_text}

【篩選原則，按優先級排序】
1. 優先推薦台灣主流媒體：中天新聞、新聞大白話、東森新聞、TVBS、三立新聞、民視新聞、鏡新聞
2. 其次選擇其他繁體中文頻道（個人 YouTuber、獨立媒體）
3. 盡量避免簡體中文媒體
4. 必須篩選出 {TARGET_CARD_COUNT} 個視頻（候補不足則全部納入）

請輸出 JSON 數組，每個對象包含：
- index: 候補列表中的原始編號（整數）
- reason: 推薦理由（1-2 句，繁體中文）
- watch_segment: 建議觀看時間段，如「0:30-2:00 的核心論點」（不確定則寫「完整觀看」）

只輸出 JSON 數組，不要任何其他文字。
[{{"index": 0, "reason": "...", "watch_segment": "..."}}]
"""

    try:
        response = _client.chat.completions.create(
            model="qwen-plus",
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = _clean_json(response.choices[0].message.content)
        selections = json.loads(raw)

        cards = []
        for sel in selections:
            idx = sel.get("index")
            if idx is None or not (0 <= idx < len(videos)):
                continue
            v = videos[idx]
            cards.append({
                "title":         v["title"],
                "url":           v["url"],
                "uploader":      v.get("uploader", ""),
                "upload_date":   _fmt_date(v),
                "duration":      v.get("duration"),
                "reason":        sel.get("reason", ""),
                "watch_segment": sel.get("watch_segment", "完整觀看"),
            })
        return cards

    except Exception as e:
        print(f"[AI 分析失敗] {e}")
        fallback = sorted(videos, key=lambda x: bool(x.get("uploader")), reverse=True)
        return [{
            "title":         v["title"],
            "url":           v["url"],
            "uploader":      v.get("uploader", ""),
            "upload_date":   _fmt_date(v),
            "duration":      v.get("duration"),
            "reason":        "根據關鍵詞匹配",
            "watch_segment": "完整觀看",
        } for v in fallback[:TARGET_CARD_COUNT]]
