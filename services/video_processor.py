"""
video_processor.py
职责：FFmpeg 视频切割 + 文件清理
"""

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from config import UPLOAD_DIR, CLIP_OUT_DIR


# ── 定位 ffmpeg ───────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    """查找 ffmpeg 可执行文件路径"""
    # 1. 先试 PATH
    for name in ["ffmpeg", "ffmpeg.exe"]:
        found = shutil.which(name)
        if found:
            return found

    # 2. 搜索 winget 安装路径
    candidates = list(Path(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
    )).glob("Gyan.FFmpeg*/**/ffmpeg.exe"))
    if candidates:
        # wingset 可能装多个版本，用最新的
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])

    # 3. 最终 fallback 回 "ffmpeg"（让系统报错）
    return "ffmpeg"

FFMPEG = _find_ffmpeg()


# ── 目录初始化 ────────────────────────────────────────────────────────────────

def _init_dirs():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(CLIP_OUT_DIR, exist_ok=True)


_init_dirs()


# ── 清理旧上传文件 ────────────────────────────────────────────────────────────

def cleanup_old_uploads(max_age_hours: int = 24):
    """删除 uploads/ 中超过 max_age_hours 的文件"""
    now = time.time()
    cutoff = now - max_age_hours * 3600
    for f in Path(UPLOAD_DIR).iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                print(f"[清理] 已删除: {f.name}")
            except OSError:
                pass


# ── 保存上传文件 ──────────────────────────────────────────────────────────────

ALLOWED_EXTS = {".mp4", ".mov", ".avi", ".webm"}

def save_upload(file_storage) -> Path:
    """保存 Flask FileStorage 到 uploads/，返回 Path"""
    cleanup_old_uploads()

    filename = file_storage.filename or "video.mp4"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"不支援的影片格式：{ext}，請上傳 mp4 / mov / avi / webm")

    uid = uuid.uuid4().hex[:8]
    saved_name = f"upload_{uid}{ext}"
    dest = Path(UPLOAD_DIR) / saved_name
    file_storage.save(str(dest))
    print(f"[上传] {saved_name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
    return dest


# ── FFmpeg 切割 ────────────────────────────────────────────────────────────────

def cut_video(
    input_path: Path,
    start_sec: float,
    duration: float,
    filename_hint: str = "clip",
) -> Path:
    """
    用 FFmpeg 帧精确模式切割视频。
    start_sec: 起始秒
    duration:  片段时长（秒）
    返回输出文件 Path
    """
    # 0.5s 缓冲
    ss = max(0.0, start_sec - 0.5)

    uid = uuid.uuid4().hex[:8]
    out_name = f"clip_{uid}.mp4"
    out_path = Path(CLIP_OUT_DIR) / out_name

    cmd = [
        FFMPEG,
        "-ss", str(ss),
        "-i", str(input_path),
        "-t", str(duration),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "aac",
        "-map", "0:v",
        "-map", "0:a?",
        "-y",                   # 覆盖已有文件
        str(out_path),
    ]

    print(f"[FFmpeg] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        print(f"[FFmpeg 错误] {result.stderr[-500:]}")
        raise RuntimeError(f"FFmpeg 剪辑失败：{result.stderr[-200:]}")

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg 未生成输出文件")

    print(f"[FFmpeg] 完成 → {out_name} ({out_path.stat().st_size / 1024:.1f} KB)")
    return out_path
