"""
srt_parser.py
職責：解析 SRT 字幕文件，輸出帶時間戳的結構化文本塊
不依賴任何第三方庫，純標準庫實現
"""

import re
from dataclasses import dataclass


@dataclass
class SubtitleBlock:
    index: int        # 字幕序號
    start_sec: float  # 開始時間（秒）
    end_sec: float    # 結束時間（秒）
    text: str         # 字幕文字


def _timestamp_to_sec(ts: str) -> float:
    """
    將 SRT 時間戳轉為秒數
    輸入格式：00:01:23,456 或 00:01:23.456
    """
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_srt(content: str) -> list[SubtitleBlock]:
    """
    解析字幕字符串，返回 SubtitleBlock 列表
    兼容 Windows (CRLF) 和 Unix (LF) 換行
    
    支持兩種格式：
    1. 標準 SRT 格式（帶時間戳）
    2. 純文本格式（自動分配時間戳）
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    
    # 先嘗試解析為標準 SRT 格式
    blocks = _parse_srt_format(content)
    
    # 如果解析失敗（可能是純文本），嘗試按段落自動分段
    if not blocks:
        blocks = _parse_plain_text(content)
    
    return blocks


def _parse_srt_format(content: str) -> list[SubtitleBlock]:
    """解析標準 SRT 格式"""
    raw_blocks = re.split(r"\n\s*\n", content.strip())
    blocks = []
    
    for raw in raw_blocks:
        lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
        if len(lines) < 3:
            continue

        # 第一行：序號
        try:
            idx = int(lines[0])
        except ValueError:
            continue

        # 第二行：時間戳
        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1]
        )
        if not time_match:
            continue

        start_sec = _timestamp_to_sec(time_match.group(1))
        end_sec   = _timestamp_to_sec(time_match.group(2))

        # 剩餘行：字幕文字（去掉 HTML 標籤）
        text = " ".join(lines[2:])
        text = re.sub(r"<[^>]+>", "", text).strip()

        if text:
            blocks.append(SubtitleBlock(
                index=idx,
                start_sec=start_sec,
                end_sec=end_sec,
                text=text
            ))

    return blocks


def _parse_plain_text(content: str) -> list[SubtitleBlock]:
    """
    解析純文本字幕（無時間戳）
    按段落分段，每段預設 3 秒（普通講話速度約 3-4 字/秒）
    """
    blocks = []
    
    # 按空行或換行分段
    paragraphs = re.split(r"\n\s*\n|\n{2,}", content.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    
    if not paragraphs:
        # 如果沒有空行分隔，按字數分段（每段約 30-40 字）
        text = content.strip()
        chunk_size = 35
        paragraphs = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    
    # 分配時間戳：每段預設 3 秒
    current_sec = 0
    duration_per_block = 3  # 每段約 3 秒
    
    for idx, text in enumerate(paragraphs, 1):
        blocks.append(SubtitleBlock(
            index=idx,
            start_sec=current_sec,
            end_sec=current_sec + duration_per_block,
            text=text.strip()
        ))
        current_sec += duration_per_block
    
    print(f"[字幕解析] 純文本模式，解析到 {len(blocks)} 段")
    return blocks


def blocks_to_prompt_text(blocks: list[SubtitleBlock]) -> str:
    """
    將字幕塊轉為適合送入 LLM 的格式化文本
    格式：[MM:SS] 字幕文字
    """
    lines = []
    for b in blocks:
        m = int(b.start_sec) // 60
        s = int(b.start_sec) % 60
        lines.append(f"[{m:02d}:{s:02d}] {b.text}")
    return "\n".join(lines)


def sec_to_timestamp(sec: float) -> str:
    """秒數轉回可讀時間戳，用於返回前端顯示"""
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
