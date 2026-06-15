"""
clipper.py
職責：第一期剪輯功能
  1. 用 yt-dlp 下載視頻 + 字幕
  2. 解析 SRT
  3. 調用 Qwen 根據點位描述定位時間段
  4. （第二期）調用 FFmpeg 切割拼接

當前實現：第一期 —— 只返回時間段 JSON，不做實際剪輯
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from openai import OpenAI

from config import QWEN_API_KEY, DOWNLOAD_DIR
from utils.srt_parser import parse_srt, blocks_to_prompt_text, sec_to_timestamp


_client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 字幕語言優先級
_SUB_LANGS = "zh-TW,zh-Hant,zh-HK,zh"


# ── Step 1：下載字幕（不下載視頻本體，節省時間）────────────────────────────

def download_subtitle(url: str, video_id: str) -> str | None:
    """
    嘗試下載字幕（優先手動字幕，其次自動生成字幕）
    返回字幕文件路徑，失敗返回 None
    """
    out_dir = Path(DOWNLOAD_DIR)
    out_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    base_cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download",          # 只下字幕，不下視頻
        "--sub-lang", _SUB_LANGS,
        "--sub-format", "srt",
        "--convert-subs", "srt",
        "-o", str(out_dir / "%(id)s.%(ext)s"),
        "--quiet",
        "--no-warnings",
    ]

    # 先嘗試手動字幕
    cmd_manual = base_cmd + ["--write-sub", url]
    result = subprocess.run(cmd_manual, capture_output=True, text=False,
                            timeout=60, env=env)

    srt_path = _find_srt(out_dir, video_id)
    if srt_path:
        print(f"[字幕] 手動字幕下載成功：{srt_path}")
        return str(srt_path)

    # 沒有手動字幕，用自動生成字幕
    cmd_auto = base_cmd + ["--write-auto-sub", url]
    result = subprocess.run(cmd_auto, capture_output=True, text=False,
                            timeout=60, env=env)

    srt_path = _find_srt(out_dir, video_id)
    if srt_path:
        print(f"[字幕] 自動字幕下載成功：{srt_path}")
        return str(srt_path)

    print(f"[字幕] 未找到可用字幕：{url}")
    return None


def _find_srt(directory: Path, video_id: str) -> Path | None:
    """在 directory 下找到以 video_id 開頭的 .srt 文件"""
    for f in directory.glob(f"{video_id}*.srt"):
        return f
    return None


# ── Step 2：從 URL 提取 video_id ─────────────────────────────────────────────

def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:embed|shorts)/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


# ── Step 3：Qwen 根據點位描述定位時間段 ──────────────────────────────────────

def locate_segments(clip_description: str, subtitle_text: str) -> list[dict]:
    """
    clip_description: 用戶描述的點位，如「找官員被追問支支吾吾的那段」
    subtitle_text:    blocks_to_prompt_text() 輸出的帶時間戳字幕文本

    返回:
    [
        {
            "start_sec": 80,
            "end_sec":   140,
            "start_fmt": "1:20",
            "end_fmt":   "2:20",
            "reason":    "部長被追問電價明顯回避"
        },
        ...
    ]
    """
    # 字幕太長時截斷，避免超出 context window
    # 策略：取頭 + 尾，保留中後段內容而非只取開頭
    max_chars = 6000
    if len(subtitle_text) > max_chars:
        half = max_chars // 2
        truncated = (
            subtitle_text[:half]
            + f"\n...(中間 {len(subtitle_text) - max_chars} 字省略)...\n"
            + subtitle_text[-half:]
        )
    else:
        truncated = subtitle_text

    prompt = f"""你是一位視頻剪輯助理。用戶想從以下字幕中找出特定片段。

【用戶點位描述】
{clip_description}

【字幕內容（格式：[MM:SS] 文字）】
{truncated}

請找出與點位描述最相關的 1-3 個時間段，輸出 JSON 數組。
每個時間段比實際匹配內容各延伸 5 秒，確保畫面完整。

輸出格式（只輸出 JSON，不要其他文字）：
[
  {{
    "start_sec": 80,
    "end_sec": 140,
    "reason": "部長被追問電價時明顯回避，支支吾吾"
  }}
]

如果沒有精確匹配，請找出最接近的片段（例如影片高潮、衝突點、關鍵發言）。
務必至少輸出一個片段，不要輸出空數組。
"""

    response = _client.chat.completions.create(
        model="qwen-plus",
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.strip()

    # 清洗 JSON
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    segments = json.loads(raw)

    # 補充格式化時間戳
    for seg in segments:
        seg["start_fmt"] = sec_to_timestamp(seg["start_sec"])
        seg["end_fmt"]   = sec_to_timestamp(seg["end_sec"])

    print(f"[Clipper] 找到 {len(segments)} 個匹配片段")
    return segments


# ── 主入口：第一期完整流程 ────────────────────────────────────────────────────

def analyze_clip(url: str, clip_description: str, subtitle_content: str = None) -> dict:
    """
    第一期主流程：
      URL + 點位描述 → 字幕下載/上傳 → SRT解析 → Qwen定位 → 返回時間段
    
    參數:
      url:              YouTube 視頻 URL
      clip_description: 用戶描述的點位
      subtitle_content: 手動上傳的字幕內容（可選），支持 .srt 格式或純文本格式
    
    返回:
    {
        "video_id": "xxx",
        "subtitle_available": True/False,
        "segments": [...],
        "total_segments": N,
        "message": "說明文字"
    }
    """
    # 1. 提取 video_id
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"無法從 URL 解析 video_id：{url}")

    print(f"[Clipper] 開始處理：{video_id}")

    # 2. 獲取字幕（優先使用手動上傳的字幕）
    if subtitle_content:
        # 使用手動上傳的字幕
        print(f"[字幕] 使用手動上傳的字幕，長度: {len(subtitle_content)} 字")
        srt_content = subtitle_content
    else:
        # 下載字幕
        srt_path = download_subtitle(url, video_id)
        if not srt_path:
            return {
                "video_id":          video_id,
                "subtitle_available": False,
                "segments":          [],
                "total_segments":    0,
                "message":           "此視頻無可用字幕（無手動字幕或自動字幕），無法進行智能定位。請手動上傳字幕文件。"
            }
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            srt_content = f.read()

    # 3. 解析 SRT

    blocks = parse_srt(srt_content)

    if not blocks:
        return {
            "video_id":          video_id,
            "subtitle_available": True,
            "segments":          [],
            "total_segments":    0,
            "message":           "字幕文件解析失敗或內容為空。"
        }

    print(f"[Clipper] 解析到 {len(blocks)} 條字幕")

    # 4. 轉為 prompt 文本
    subtitle_text = blocks_to_prompt_text(blocks)

    # 5. Qwen 定位時間段
    segments = locate_segments(clip_description, subtitle_text)

    msg = (
        f"共找到 {len(segments)} 個匹配片段。"
        if segments
        else "未找到匹配片段，請嘗試調整點位描述。"
    )

    return {
        "video_id":          video_id,
        "subtitle_available": True,
        "segments":          segments,
        "total_segments":    len(segments),
        "message":           msg
    }
