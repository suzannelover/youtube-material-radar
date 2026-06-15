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
    BATCH_MIN_SEGMENTS, BATCH_MAX_SEGMENTS,
    BATCH_SEG_MIN_LEN, BATCH_SEG_DEFAULT,
    BATCH_SEG_TARGET_MIN, BATCH_SEG_TARGET_MAX,
    BATCH_SEG_GAP, BATCH_OVERLAP_RATIO, BATCH_FRAME_STEP_MIN,
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


def sample_timestamps_batch(duration: float) -> list[float]:
    """批量模式：比单视频更密集采样，一次覆盖全片"""
    target = min(50, max(25, int(duration / 6)))
    step = duration / target
    step = max(step, BATCH_FRAME_STEP_MIN)
    return [i * step for i in range(int(duration / step))]


# ══════════════════════════════════════════════════════════════════════════════
#  GLM 视觉分析
# ══════════════════════════════════════════════════════════════════════════════

def _build_instruction_text(description: str, target_duration: int, is_retry: bool = False) -> str:
    """构建送入 GLM 的文本指令部分"""
    strictness = ""
    if is_retry:
        strictness = """
如果以上都不合适，直接取影片中最有视觉冲击力/最精彩的连续片段。
务必输出有效 JSON，不要输出空结果。"""

    return f"""你是一个视频剪辑助手。根据给出的帧序列，找到最符合剪辑指令的时间段。

【剪辑指令】{description}
【目标时长】{target_duration}s

【分析要点】
1. 注意人物的表情变化（紧张、愤怒、激动、尴尬、大笑等）
2. 注意画面中的文字信息（标题、图表、字幕、评论区等）
3. 注意场景氛围（对峙、辩论、感人、爆料、冲突等）
4. 连续多帧画面内容相似（同一场景）时，时间范围应覆盖整个场景
5. 黑屏、纯色、镜头快速晃动（转场）——忽略这些帧

【输出要求】
只输出一个 JSON 对象，不要其他文字，不要 Markdown 代码块：
{{"start_sec": N, "end_sec": M, "reason": "这段匹配的具体视觉线索"}}
{strictness}"""


def _call_glm_vision(frames: list[dict], description: str, target_duration: int, is_retry: bool = False) -> dict:
    """调用 GLM-4.6V-Flash 分析帧序列

    每帧图片前附带时间戳文本，让模型知道每帧的时间位置。
    """
    content = []
    for f in frames:
        m = int(f["ts"]) // 60
        s = int(f["ts"]) % 60
        # 每帧前附带时间戳文本，让模型知道该帧在视频中的位置
        content.append({
            "type": "text",
            "text": f"幀 @{m:02d}:{s:02d}"
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": f["b64"]}
        })

    instruction = _build_instruction_text(description, target_duration, is_retry)
    content.append({"type": "text", "text": instruction})

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


# ── 批量模式 Prompt ──────────────────────────────────────────────────────────

_BATCH_INSTRUCTION = """你是一个视频剪辑助手。从一段长视频中提取多个短视频片段。

【剪辑指令】{description}
【每段时长】{min_len}~{max_len} 秒
【输出数量】{min_out}~{max_out} 段

请从帧序列中选出 {min_out}~{max_out} 个适合独立成片的片段：
1. 优先选择最符合剪辑指令的画面区域
2. 不够 {min_out} 段时，补充视觉精彩的画面：
   表情变化（紧张/愤怒/激动/大笑）、冲突辩论、文字标题、
   爆料瞬间、场景切换、人物特写
3. 各片段覆盖影片的**不同时间段**，不要全部集中在同一区域
4. 相邻片段间隔至少 {gap} 秒，避免画面雷同

输出 JSON 数组（仅 JSON，不要其他文字，不要 Markdown 代码块）：
[{{"start_sec": 30, "end_sec": 48, "reason": "表情变化明显"}}, ...]
如果实在找不到足够片段，有多少输出多少。"""


def _call_glm_vision_batch(frames: list[dict], description: str) -> list[dict]:
    """调用 GLM-4.6V-Flash，批量模式：返回片段数组"""
    content = []
    for f in frames:
        m = int(f["ts"]) // 60
        s = int(f["ts"]) % 60
        content.append({
            "type": "text",
            "text": f"幀 @{m:02d}:{s:02d}"
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": f["b64"]}
        })

    instruction = _BATCH_INSTRUCTION.format(
        description=description,
        min_len=BATCH_SEG_TARGET_MIN,
        max_len=BATCH_SEG_TARGET_MAX,
        min_out=BATCH_MIN_SEGMENTS,
        max_out=BATCH_MAX_SEGMENTS,
        gap=BATCH_SEG_GAP,
    )
    content.append({"type": "text", "text": instruction})

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
#  批量模式：去重 + 补段
# ══════════════════════════════════════════════════════════════════════════════

def _clamp_segment(seg: dict) -> dict:
    """将片段 clamp 到批量模式的 15~20s 范围内"""
    ss, se = seg["start_sec"], seg["end_sec"]
    actual = se - ss

    if actual < BATCH_SEG_TARGET_MIN:
        mid = (ss + se) / 2
        half = BATCH_SEG_TARGET_MIN / 2
        ss = mid - half
        se = mid + half
    elif actual > BATCH_SEG_TARGET_MAX:
        mid = (ss + se) / 2
        half = BATCH_SEG_TARGET_MAX / 2
        ss = mid - half
        se = mid + half

    return {
        "start_sec": ss,
        "end_sec": se,
        "start_fmt": sec_to_timestamp(ss),
        "end_fmt": sec_to_timestamp(se),
        "reason": seg.get("reason", ""),
    }


def _dedup_segments(segments: list[dict]) -> list[dict]:
    """去重：重叠 > 30% 丢弃，≤ 30% 修剪，间隙强制 ≥ 3s"""
    if not segments:
        return []

    segments.sort(key=lambda s: s["start_sec"])
    result = [segments[0]]

    for seg in segments[1:]:
        prev = result[-1]
        overlap = prev["end_sec"] - seg["start_sec"]

        if overlap > 0:
            overlap_ratio = overlap / min(
                prev["end_sec"] - prev["start_sec"],
                seg["end_sec"] - seg["start_sec"],
            )
            if overlap_ratio > BATCH_OVERLAP_RATIO:
                continue  # 重叠 > 30%，丢弃
            else:
                seg["start_sec"] = prev["end_sec"] + BATCH_SEG_GAP
                seg["start_fmt"] = sec_to_timestamp(seg["start_sec"])
        elif seg["start_sec"] - prev["end_sec"] < BATCH_SEG_GAP:
            seg["start_sec"] = prev["end_sec"] + BATCH_SEG_GAP
            seg["start_fmt"] = sec_to_timestamp(seg["start_sec"])

        # 修剪后检查：至少 BATCH_SEG_MIN_LEN 秒
        if seg["end_sec"] - seg["start_sec"] >= BATCH_SEG_MIN_LEN:
            result.append(seg)

    return result


def _fill_segments(existing: list[dict], duration: float) -> list[dict]:
    """不足 5 段时，从未使用区域均匀补段"""
    needed = BATCH_MIN_SEGMENTS - len(existing)
    if needed <= 0:
        return existing

    used = sorted([(s["start_sec"], s["end_sec"]) for s in existing])
    free_ranges = []
    last_end = 0.0
    for ss, se in used:
        if ss - last_end >= BATCH_SEG_MIN_LEN + BATCH_SEG_GAP:
            free_ranges.append([last_end, ss])
        last_end = max(last_end, se)
    if duration - last_end >= BATCH_SEG_MIN_LEN + BATCH_SEG_GAP:
        free_ranges.append([last_end, duration])

    result = list(existing)
    seg_len = BATCH_SEG_DEFAULT

    for _ in range(needed):
        free_ranges.sort(key=lambda r: r[1] - r[0], reverse=True)
        candidates = [r for r in free_ranges if r[1] - r[0] >= seg_len + BATCH_SEG_GAP]
        if not candidates:
            break

        r = candidates[0]
        mid = (r[0] + r[1]) / 2
        half = seg_len / 2
        ss = max(r[0], mid - half)
        se = min(r[1], mid + half)
        result.append({
            "start_sec": ss,
            "end_sec": se,
            "start_fmt": sec_to_timestamp(ss),
            "end_fmt": sec_to_timestamp(se),
            "reason": "自动补充片段",
        })
        free_ranges.remove(r)
        if ss - r[0] >= seg_len + BATCH_SEG_GAP:
            free_ranges.append([r[0], ss])
        if r[1] - se >= seg_len + BATCH_SEG_GAP:
            free_ranges.append([se, r[1]])

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  主入口（单视频）
# ══════════════════════════════════════════════════════════════════════════════

def _fallback_segment(duration: float, target_duration: int, reason: str = "自动选取影片中间段") -> dict:
    """当所有尝试都失败时，返回影片中间段作为保底结果"""
    mid = duration / 2
    half = target_duration / 2
    ss = max(0, mid - half)
    se = min(duration, mid + half)
    return {
        "start_sec": ss,
        "end_sec": se,
        "start_fmt": sec_to_timestamp(ss),
        "end_fmt": sec_to_timestamp(se),
        "reason": reason,
    }


def _original_step(duration: float) -> float:
    """计算第一轮采样的原始 step，用于 retry 时按比例缩小"""
    if duration <= 60:
        return 3.0
    return max(10.0, duration / 15.0)


def _retry_dense(video_path: str, description: str, target_duration: int,
                 duration: float, r1_seg: dict | None) -> dict | None:
    """重试：适当加密采样 + 宽松 prompt，返回 seg 或 None"""
    orig_step = _original_step(duration)

    if r1_seg:
        # 有第一轮结果时，在其附近加密一倍（step 减半）
        margin = orig_step * 2
        r_start = max(0, r1_seg["start_sec"] - margin)
        r_end   = min(duration, r1_seg["end_sec"] + margin)
        step    = orig_step / 2  # 密度翻倍，但不过分
    else:
        # 没有第一轮结果，整片加密一倍
        r_start = 0
        r_end   = duration
        step    = orig_step / 2

    step = max(step, 2.0)  # 最低 2s，避免帧数爆炸

    r_ts = []
    t = r_start
    while t <= r_end:
        r_ts.append(t)
        t += step

    # 最多 30 帧，避免超出 context window
    if len(r_ts) > 30:
        # 均匀抽取 30 帧
        idx = [int(i * len(r_ts) / 30) for i in range(30)]
        r_ts = [r_ts[i] for i in idx]

    print(f"[VisionClipper] 重试采样 {len(r_ts)} 帧 ({r_start:.0f}s ~ {r_end:.0f}s, step={step:.1f}s, 原始step={orig_step:.1f}s)")
    frames = extract_frames_at(video_path, r_ts)
    try:
        raw = _call_glm_vision(frames, description, target_duration, is_retry=True)
        return validate_segment(raw, duration)
    except Exception as e:
        print(f"[VisionClipper] 重试也失败: {e}")
        return None


def analyze_video(video_path: str, description: str, target_duration: int = CLIP_DEFAULT_DURATION) -> dict:
    """
    完整流程：帧采样 → GLM分析 → 校验 → 重试 → 保底。
    返回:
    {
        "start_sec": 42.0, "end_sec": 60.5,
        "start_fmt": "0:42", "end_fmt": "1:00",
        "reason": "候選人回答時表情生動"
    }
    """
    duration = get_video_duration(video_path)
    print(f"[VisionClipper] 视频时长: {duration:.1f}s, 目标: {target_duration}s")

    timestamps = sample_timestamps(duration, target_duration)

    # ── 第一轮 ──
    print(f"[VisionClipper] 第1轮采样 {len(timestamps)} 帧")
    frames = extract_frames_at(video_path, timestamps)
    try:
        raw = _call_glm_vision(frames, description, target_duration)
        seg = validate_segment(raw, duration)
    except Exception as e:
        print(f"[VisionClipper] 第1轮异常: {e}")
        seg = None

    if seg:
        seg = constrain_duration(seg, target_duration)
        print(f"[VisionClipper] 第1轮结果: {seg['start_fmt']} ~ {seg['end_fmt']}")
        # 短视频单轮即返回
        if duration <= 60:
            return seg
    else:
        print(f"[VisionClipper] 第1轮未找到有效片段，准备重试")
        seg = None  # 标记需要重试

    # ── 长视频（或第1轮失败）：尝试重试 ──
    if not seg:
        # 第1轮失败 → 密集重试
        retry_seg = _retry_dense(video_path, description, target_duration, duration, None)
        if retry_seg:
            seg = constrain_duration(retry_seg, target_duration)
            print(f"[VisionClipper] 重试成功: {seg['start_fmt']} ~ {seg['end_fmt']}")
            return seg

        # 全部失败 → 保底：取影片中间段
        print(f"[VisionClipper] 所有尝试失败，使用保底中间段")
        return _fallback_segment(duration, target_duration,
                                 reason=f"未能精确定位，自动选取影片中间 {target_duration}s")

    # 第1轮成功，进入第2轮精确定位
    margin = 5
    r2_start = max(0, seg["start_sec"] - margin)
    r2_end   = min(duration, seg["end_sec"] + margin)
    r2_step  = 2  # 每 2s 一帧
    r2_ts    = []
    t = r2_start
    while t <= r2_end:
        r2_ts.append(t)
        t += r2_step

    print(f"[VisionClipper] 第2轮精确定位，采样 {len(r2_ts)} 帧 ({r2_start:.0f}s ~ {r2_end:.0f}s)")

    frames_r2 = extract_frames_at(video_path, r2_ts)
    try:
        raw_r2 = _call_glm_vision(frames_r2, description, target_duration)
        seg2 = validate_segment(raw_r2, duration)
    except Exception as e:
        print(f"[VisionClipper] 第2轮异常: {e}")
        seg2 = None

    if seg2:
        seg = constrain_duration(seg2, target_duration)
    else:
        # 第2轮失败，用第1轮结果
        seg = constrain_duration(seg, target_duration)
        print(f"[VisionClipper] 第2轮无效，使用第1轮结果")

    print(f"[VisionClipper] 最终: {seg['start_fmt']} ~ {seg['end_fmt']} ({seg['end_sec'] - seg['start_sec']:.1f}s)")
    return seg


# ══════════════════════════════════════════════════════════════════════════════
#  批量模式主入口
# ══════════════════════════════════════════════════════════════════════════════

def get_max_batch_segments(duration: float) -> int:
    """短影片保护：计算最大可行片段数"""
    return max(1, int(duration / (BATCH_SEG_MIN_LEN + BATCH_SEG_GAP)))


def analyze_video_batch(video_path: str, description: str) -> list[dict]:
    """
    批量模式：采样 → GLM → 校验 → 去重 → clamp → 补段。
    返回 5~8 段，每段 15~20s。
    """
    duration = get_video_duration(video_path)
    max_ok = get_max_batch_segments(duration)
    print(f"[VisionClipper-Batch] 视频时长: {duration:.1f}s, 最大可行段数: {max_ok}")

    # 1. 密集采样
    timestamps = sample_timestamps_batch(duration)
    print(f"[VisionClipper-Batch] 采样 {len(timestamps)} 帧")
    frames = extract_frames_at(video_path, timestamps)

    # 2. GLM 分析
    try:
        raw_segments = _call_glm_vision_batch(frames, description)
    except Exception as e:
        print(f"[VisionClipper-Batch] GLM 异常: {e}")
        raw_segments = []

    if not isinstance(raw_segments, list):
        raw_segments = []

    print(f"[VisionClipper-Batch] GLM 返回 {len(raw_segments)} 段")

    # 3. 逐段校验
    valid = []
    for raw in raw_segments:
        seg = validate_segment(raw, duration)
        if seg:
            valid.append(seg)
    print(f"[VisionClipper-Batch] 校验通过 {len(valid)} 段")

    # 4. 去重
    deduped = _dedup_segments(valid)
    print(f"[VisionClipper-Batch] 去重后 {len(deduped)} 段")

    # 5. clamp 到 15~20s
    clamped = [_clamp_segment(s) for s in deduped]

    # 6. 补段（不足 5 段时）
    filled = _fill_segments(clamped, duration)

    # 7. 限制到 max_ok
    filled = filled[:min(len(filled), max_ok, BATCH_MAX_SEGMENTS)]

    # 边界裁剪
    for s in filled:
        s["start_sec"] = max(0.0, s["start_sec"])
        s["end_sec"] = min(duration, s["end_sec"])
        s["start_fmt"] = sec_to_timestamp(s["start_sec"])
        s["end_fmt"] = sec_to_timestamp(s["end_sec"])

    print(f"[VisionClipper-Batch] 最终输出 {len(filled)} 段")
    return filled
