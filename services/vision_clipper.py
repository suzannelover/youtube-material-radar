"""
vision_clipper.py
职责：视频帧采样 + GLM-4.6V-Flash 视觉理解定位时间片段
"""

import base64
import io
import json
import os
from pathlib import Path

import cv2
import numpy as np
from openai import OpenAI

from config import (
    GLM_API_KEY, GLM_MODEL, GLM_BASE_URL,
    VISION_FRAME_W, VISION_QUALITY, VISION_USE_THINKING,
    CLIP_DEFAULT_DURATION, CLIP_MIN_DURATION, CLIP_MAX_DURATION,
    UPLOAD_DIR,
)
from utils.srt_parser import sec_to_timestamp


# ── GLM 客户端 ────────────────────────────────────────────────────────────────

_glm_client = OpenAI(api_key=GLM_API_KEY, base_url=GLM_BASE_URL)


# ══════════════════════════════════════════════════════════════════════════════
#  帧采样
# ══════════════════════════════════════════════════════════════════════════════

def get_video_duration(path: str) -> float:
    """获取视频总时长（秒）"""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if fps <= 0:
        raise ValueError("无法读取视频帧率")
    return frame_count / fps


def _frame_to_base64(frame: np.ndarray) -> str:
    """将 OpenCV 帧缩放压缩后转为 data URI base64"""
    h, w = frame.shape[:2]
    new_w = VISION_FRAME_W
    new_h = int(h * new_w / w)
    resized = cv2.resize(frame, (new_w, new_h))

    # 编码为 JPEG
    _, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, VISION_QUALITY])
    b64 = base64.b64encode(buf).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def extract_frames_at(
    video_path: str, timestamps: list[float]
) -> list[dict]:
    """
    在指定的时间戳位置提取帧，返回 [{"ts": float, "b64": str}, ...]
    时间戳超出视频长度时自动 clamp。
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    frames = []
    for ts in timestamps:
        ts = max(0.0, min(ts, duration - 0.01))
        frame_idx = int(ts * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append({"ts": ts, "b64": _frame_to_base64(frame)})

    cap.release()
    return frames


def sample_timestamps(duration: float, target_duration: int) -> list[float]:
    """
    生成采样时间戳列表。
    短视频（≤60s）单轮密集采样；长视频两轮采样（粗筛+精确定位）。
    返回 [round1_timestamps] 或 None（表示需要第二轮）。
    """
    if duration <= 60:
        # 短视频：每 3s 一帧，最多 20 帧
        step = 3
        n = min(20, int(duration / step))
        return [i * step for i in range(n)]

    # 长视频第一轮：间隔采样
    step = max(10.0, duration / 15.0)
    n = int(duration / step)
    return [i * step for i in range(n)]


# ══════════════════════════════════════════════════════════════════════════════
#  GLM 视觉分析
# ══════════════════════════════════════════════════════════════════════════════

def _build_prompt(frames: list[dict], description: str, target_duration: int) -> str:
    """构建送入 GLM 的 prompt"""
    frame_lines = []
    for f in frames:
        m = int(f["ts"]) // 60
        s = int(f["ts"]) % 60
        frame_lines.append(f"[{m:02d}:{s:02d}] {f['b64']}")

    return f"""你是一个视频剪辑助手。根据用户提供的视频帧序列，找到最符合剪辑指令的时间段。

【分析要点】
1. 注意人物的表情变化（紧张、愤怒、激动、尴尬等）
2. 注意画面中的文字信息（标题、图表、字幕）
3. 注意场景氛围（对峙、辩论、感人、爆料等）
4. 如果多帧画面内容相似（同一场景的连续帧），时间应覆盖整个场景
5. 如果画面是黑屏、纯色、或镜头快速晃动（转场），忽略这些帧

【剪辑指令】{description}
【目标时长】{target_duration}s

【帧序列】每帧标注时间戳：
{chr(10).join(frame_lines)}

输出 JSON（仅 JSON，不要其他文字，不要 Markdown 代码块）：
{{"start_sec": N, "end_sec": M, "reason": "说明为什么这段匹配，包含具体视觉线索"}}"""


def _call_glm_vision(frames: list[dict], description: str, target_duration: int) -> dict:
    """调用 GLM-4.6V-Flash 分析帧序列"""
    prompt_text = _build_prompt(frames, description, target_duration)

    # 构建多模态消息
    content = []
    for f in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f["b64"]}
        })
    content.append({"type": "text", "text": f"""【剪辑指令】{description}
【目标时长】{target_duration}s

输出 JSON（仅 JSON）：{{"start_sec": N, "end_sec": M, "reason": "..."}}"""})

    extra = {}
    if VISION_USE_THINKING:
        extra["extra_body"] = {"thinking": {"type": "enabled"}}

    response = _glm_client.chat.completions.create(
        model=GLM_MODEL,
        temperature=0.1,
        messages=[{"role": "user", "content": content}],
        **extra,
    )

    raw = response.choices[0].message.content.strip()

    # 清洗 JSON
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


# ══════════════════════════════════════════════════════════════════════════════
#  输出校验
# ══════════════════════════════════════════════════════════════════════════════

def validate_segment(seg: dict, video_duration: float) -> dict | None:
    """校验并修正 GLM 返回的时间段，返回 None 表示丢弃"""
    ss = seg.get("start_sec", 0)
    se = seg.get("end_sec", 0)

    # 基本合法性：必须 start < end，且差值 ≥ 3s
    if ss >= se or (se - ss) < 3:
        print(f"[校验失败] 时间段无效: {ss}s ~ {se}s")
        return None

    # 边界裁剪
    ss = max(0.0, ss)
    se = min(video_duration, se)

    return {
        "start_sec": ss,
        "end_sec": se,
        "start_fmt": sec_to_timestamp(ss),
        "end_fmt": sec_to_timestamp(se),
        "reason": seg.get("reason", ""),
    }


def constrain_duration(seg: dict, target_duration: int) -> dict:
    """
    如果 GLM 返回的片段比 target 长很多，取中间最精彩的子段。
    如果不够长，保留原样不强拉。
    """
    ss, se = seg["start_sec"], seg["end_sec"]
    actual = se - ss

    if actual <= target_duration:
        return seg  # 保留了

    # 取了 → 取中间 target_duration 秒
    mid = (ss + se) / 2
    half = target_duration / 2
    ss = max(ss, mid - half)
    se = min(se, mid + half)

    return {
        "start_sec": ss,
        "end_sec": se,
        "start_fmt": sec_to_timestamp(ss),
        "end_fmt": sec_to_timestamp(se),
        "reason": seg["reason"],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════════════════

def analyze_video(video_path: str, description: str, target_duration: int = CLIP_DEFAULT_DURATION) -> dict:
    """
    完整流程：帧采样 → GLM分析 → 校验 → 时长约束。
    返回:
    {
        "start_sec": 42.0, "end_sec": 60.5,
        "start_fmt": "0:42", "end_fmt": "1:00",
        "reason": "候選人回答時表情生動"
    }
    """
    duration = get_video_duration(video_path)
    print(f"[VisionClipper] 视频时长: {duration:.1f}s, 目标: {target_duration}s")

    # ── 第一轮 ──
    timestamps = sample_timestamps(duration, target_duration)

    if duration <= 60:
        # 短视频：单轮完成
        print(f"[VisionClipper] 短视频模式，采样 {len(timestamps)} 帧")
        frames = extract_frames_at(video_path, timestamps)
        raw = _call_glm_vision(frames, description, target_duration)
        seg = validate_segment(raw, duration)
        if not seg:
            raise ValueError("GLM 未能找到匹配片段，請嘗試調整剪輯描述")

        seg = constrain_duration(seg, target_duration)
        print(f"[VisionClipper] 结果: {seg['start_fmt']} ~ {seg['end_fmt']} ({seg['end_sec'] - seg['start_sec']:.1f}s)")
        return seg

    # ── 长视频：两轮 ──
    print(f"[VisionClipper] 长视频模式，第1轮粗筛 {len(timestamps)} 帧")

    frames_r1 = extract_frames_at(video_path, timestamps)
    raw_r1 = _call_glm_vision(frames_r1, description, target_duration)
    valid_r1 = validate_segment(raw_r1, duration)

    if not valid_r1:
        raise ValueError("GLM 第1轮未能找到匹配片段，請嘗試調整剪輯描述")

    print(f"[VisionClipper] 第1轮: {valid_r1['start_fmt']} ~ {valid_r1['end_fmt']}")

    # ── 第二轮：在候选区间内密集采样 ──
    margin = 5
    r2_start = max(0, valid_r1["start_sec"] - margin)
    r2_end   = min(duration, valid_r1["end_sec"] + margin)
    r2_step  = 2  # 每 2s 一帧
    r2_ts    = []
    t = r2_start
    while t <= r2_end:
        r2_ts.append(t)
        t += r2_step

    print(f"[VisionClipper] 第2轮精确定位，采样 {len(r2_ts)} 帧 ({r2_start:.0f}s ~ {r2_end:.0f}s)")

    frames_r2 = extract_frames_at(video_path, r2_ts)
    raw_r2 = _call_glm_vision(frames_r2, description, target_duration)
    seg = validate_segment(raw_r2, duration)

    if not seg:
        # 第2轮失败，用第1轮结果
        seg = constrain_duration(valid_r1, target_duration)
    else:
        seg = constrain_duration(seg, target_duration)

    print(f"[VisionClipper] 最终: {seg['start_fmt']} ~ {seg['end_fmt']} ({seg['end_sec'] - seg['start_sec']:.1f}s)")
    return seg
