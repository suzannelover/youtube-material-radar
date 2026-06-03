# 智能剪辑 V2 — 开发文档

> 基于 `dev` 分支开发，不破坏 `master` 的稳定性

---

## 1. 现状 vs 目标

| 维度 | 当前 V1（master） | 目标 V2（dev） |
|------|-------------------|----------------|
| **输入** | YouTube URL + 文字描述 | **用户上传视频文件** + 剪辑指令 |
| **理解方式** | Qwen 分析**字幕文本**找片段 | GLM-4.6V-Flash **视觉理解**视频画面 |
| **输出** | 返回 JSON 时间戳（不下刀） | **输出可下载的视频文件**（真正剪辑） |
| **时长控制** | 无 | **15~30s** 或用户自定义 |
| **剪辑策略** | 无 | **不生硬**（留头留尾、转场自然） |
| **Token 优化** | 无 | **尽可能低** |

---

## 2. 架构变化总览

> 原则：V1 代码**完全不动**。V2 全部新增文件，不修改 `clipper.py`。

```
services/
  ├── clipper.py           ← ★ 不修改（V1 代码保持不变）
  ├── vision_clipper.py    ← [新增] GLM-4.6V-Flash 视觉理解 + 帧采样
  └── video_processor.py   ← [新增] FFmpeg 切割 + 文件管理
config.py                  ← 新增 GLM_API_KEY、视觉参数
app.py                     ← 新增 /api/clip_v2 路由（与 V1 /api/clip 共存）
index.html                 ← 新增 V2 Tab：视频上传表单 + 进度 + 下载
requirements.txt           ← 新增 opencv-python-headless
```

---

## 3. 核心流程

```
用户上传视频 → Flask 接收文件 → 存到 uploads/（非 downloads/）
                               ↓
                   关键帧采样（见第 4 节）
                               ↓
                   GLM-4.6V-Flash 分析帧序列
                   输入：帧图片(base64) + 剪辑指令
                   输出：JSON { best_start_sec, best_end_sec, reason }
                               ↓
                   后处理策略（见第 6 节）
                               ↓
                   FFmpeg 切割（见第 5 节）
                               ↓
                   输出统一为 .mp4 存到 outputs/clips/
                   返回下载链接
```

---

## 4. Token 优化与帧采样策略（核心）

> 对比结论：**本地帧采样 + base64** 方案完胜**直接传视频 URL** 方案。
> - Token 消耗：~5,000 vs ~70,000（差 10 倍以上）
> - 延迟：~5~13s vs ~20~75s（差 4~5 倍）
> - 不需要云存储，全本地可控

### 4.1 分层均匀采样

> 设计原则：简单可维护优先于理论最优。场景切换检测（OpenCV absdiff / FFmpeg select filter）增加 100+ 行代码和阈值调优成本，本期用均匀采样 + 校验覆盖。

```
视频总长 T

第一轮（粗筛）：
  如果 T ≤ 60s：
    间隔 = 3s → 最多 20 帧，直接单轮完成（跳过第二轮）
  如果 T > 60s：
    间隔 = max(10s, T/15) → 约 10~15 帧
    送入 GLM → 输出候选时间段 [A, B]

第二轮（精确定位，仅 T > 60s 时执行）：
  在 [A-5, B+5] 范围内
  采样间隔 = 2s → 约 5 帧
  送入 GLM → 输出精确的 start_sec, end_sec
```

> 短视频（≤60s）单轮即可，避免不必要的第二轮 API 调用。

### 4.2 图片压缩

- 每帧缩放至 **640px 宽**（保持比例）
- JPEG 质量 **70%**
- 单帧约 50~100KB，两轮合计 ~15~20 帧，约 1~2MB

### 4.3 增强版 Prompt

```
系统：你是一个视频剪辑助手。根据用户提供的视频帧序列，找到最符合剪辑指令的时间段。

【分析要点】
1. 注意人物的表情变化（紧张、愤怒、激动、尴尬等）
2. 注意画面中的文字信息（标题、图表、字幕）
3. 注意场景氛围（对峙、辩论、感人、爆料等）
4. 如果多帧画面内容相似（同一场景的连续帧），时间应覆盖整个场景
5. 如果画面是黑屏、纯色、或镜头快速晃动（转场），忽略这些帧

【剪辑指令】{user_description}
【目标时长】{target_duration}s

【帧序列】每帧标注时间戳：
  [00:05] (base64 image...)
  [00:10] (base64 image...)
  ...

输出 JSON（仅 JSON，不要其他文字，不要 Markdown 代码块）：
{"start_sec": N, "end_sec": M, "reason": "说明为什么这段匹配，包含具体视觉线索"}
```

### 4.4 GLM 思考模式的取舍

```python
# 可选项：传入 extra_body 启用思考模式
# 优点：定位更准确，尤其适合模糊描述
# 缺点：Token 消耗增加 2~3 倍，延迟增加 3~5s
#
# 建议：先关闭（默认），实测后按需开启
"thinking": {"type": "disabled"}
```

---

### 4.5 GLM 输出校验

GLM 返回的 JSON 不可盲信，必须在 FFmpeg 切割前做校验：

```python
def validate_segment(seg: dict, video_duration: float) -> dict | None:
    """校验并修正 GLM 返回的时间段，返回 None 表示丢弃"""
    ss = seg.get("start_sec", 0)
    se = seg.get("end_sec", 0)

    # 0. 基本合法性：必须 start < end，且差值 ≥ 3s
    if ss >= se or (se - ss) < 3:
        print(f"[校验失败] 时间段无效: {ss}s ~ {se}s")
        return None

    # 1. 边界裁剪：不能超出视频总长
    ss = max(0.0, ss)
    se = min(video_duration, se)

    return {"start_sec": ss, "end_sec": se, "start_fmt": sec_to_timestamp(ss),
            "end_fmt": sec_to_timestamp(se), "reason": seg.get("reason", "")}
```

---

## 5. FFmpeg 切割方案

### 5.1 命令

> ⚠️ `-to` 位置决定语义：**在 `-i` 前 = 输入结束位置，在 `-i` 后 = 输出持续时间**。

```bash
# 快速模式（关键帧对齐，±2s 可接受时用）
# 变量: start_sec=42.0, duration=18.5
ffmpeg -ss {start_sec} -i input.mp4 -to {duration} -c copy -avoid_negative_ts make_zero output.mp4

# 帧精确模式（精确到秒，最终输出用这个）
# 变量: start_sec=42.0, duration=18.5
# 注：-t 在 -i 后表示输出持续时间，避免 -to 语义混淆
ffmpeg -ss {start_sec} -i input.mp4 -t {duration} -c:v libx264 -crf 23 -preset fast -c:a aac -map 0:v -map 0:a? output.mp4
```

> `-map 0:a?` 表示"如果输入有音频流则包含"，避免无音轨视频报错。

### 5.2 `-c copy` 的关键帧对齐问题

`-c copy` 只在 I帧位置切割。`start_sec=42.0s` 但最近 I帧在 `40.2s` 时，视频从 40.2s 开始。

**建议**：正式输出用**帧精确模式**（重编码）；`-c copy` 仅用于快速预览。

### 5.3 输出格式

**一律输出 `.mp4`（H.264 + AAC）**，兼容所有浏览器直接播放。

输入 `.mov`/`.avi`/`.webm` 等 → FFmpeg 自动转码。

### 5.4 文件管理

```python
UPLOAD_DIR   = "uploads"
CLIP_OUT_DIR = "outputs/clips"
```

- 输出文件：`clip_{uuid4()}.mp4`
- **清理策略**：在每次上传前扫描 `UPLOAD_DIR`，删除修改时间 > 24h 的文件（无需定时任务）

---

## 6. 不生硬剪辑策略

### 6.1 可实现方案（本期）

| 策略 | 实现 | 依赖 |
|------|------|------|
| 起止各延伸 **0.5s** 缓冲 | FFmpeg 切割时 `start - 0.5`，`end + 0.5` | 无 |
| 起止 clamp 到视频边界 | `max(0, start)`, `min(video_duration, end)` | 无 |
| 多个候选片段 | 取时长最接近目标值的 | 无 |
| 候选不足 15s | 保留原样，不强拉 | 无 |

### 6.2 无法在本期实现的（需音频分析）

| 策略 | 原因 | 后续版本 |
|------|------|----------|
| 延伸至"语句自然停顿点" | 需要 VAD 语音活动检测 | 引入 `webrtcvad` 或 GLM-ASR |
| "从镜头稳定后 0.3s" | 需要运动估计 | 引入 `scenedetect` |

---

## 7. API 设计

### 7.1 上传 + 剪辑

```python
POST /api/clip_v2
Content-Type: multipart/form-data

参数:
  video:       <文件>         # 必须，视频文件
  description: "找亮点片段"    # 必须，剪辑指令
  duration:    20             # 可选，目标秒数，默认 20

成功返回 200:
{
  "status":       "ok",
  "filename":     "clip_abc123.mp4",
  "duration":     18.5,
  "start_sec":    42.0,
  "end_sec":      60.5,
  "download_url": "/api/clip_v2/download/clip_abc123.mp4",
  "reason":       "候選人回答時表情生動，內容切題"
}

错误返回:
400 { "error": "不支援的影片格式，請上傳 mp4/mov/avi/webm" }
400 { "error": "請輸入剪輯描述" }
413 { "error": "檔案過大，上限 200MB" }
502 { "error": "AI 分析超時，請稍後重試" }
500 { "error": "伺服器錯誤，請確認 FFmpeg 已安裝" }
```

### 7.2 下载

```python
GET /api/clip_v2/download/<filename>

# 实现：send_from_directory(CLIP_OUT_DIR, filename)
# 防止路径穿越：send_from_directory 自带安全限制
```

### 7.3 并发与超时

```python
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # ★ 必须设置

# 注意：app.run(debug=True) 单线程，视频处理会阻塞其他请求
# 开发阶段可接受；生产环境需使用 Gunicorn + gevent 或 Celery
```

### 7.4 速率限制注意

`glm-4.6v-flash` 是免费模型，有 RPM/TPM 限制。多个并发请求可能被限流。
建议后续在路由入口加一个简单的请求队列或互斥锁。

---

## 8. 配置文件变更

```python
# config.py 新增
GLM_API_KEY           = "your-glm-key"
GLM_MODEL             = "glm-4.6v-flash"
GLM_BASE_URL          = "https://open.bigmodel.cn/api/paas/v4/"

# 视觉参数
VISION_FRAME_W        = 640
VISION_QUALITY        = 70
VISION_USE_THINKING   = False       # 是否启用 GLM 思考模式

# 剪辑参数
CLIP_DEFAULT_DURATION = 20
CLIP_MIN_DURATION     = 15
CLIP_MAX_DURATION     = 30

# 目录
UPLOAD_DIR            = "uploads"
CLIP_OUT_DIR          = "outputs/clips"
MAX_UPLOAD_SIZE_MB    = 200
```

---

## 9. 依赖变更

```txt
# requirements.txt 新增
opencv-python-headless   # 视频帧提取
```

FFmpeg 需系统安装并在 PATH 中。

---

## 10. GLM API 集成方式

智谱 AI 完全兼容 OpenAI SDK：

```python
from openai import OpenAI

_glm_client = OpenAI(
    api_key=GLM_API_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)

response = _glm_client.chat.completions.create(
    model="glm-4.6v-flash",
    messages=[{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt_text}
        ]
    }]
)
```

与 Qwen（`dashscope.aliyuncs.com`）完全独立，各自持有自己的 `OpenAI` 实例。

---

## 11. 实施步骤

| 步骤 | 内容 | 涉及文件 | 风险 |
|------|------|----------|------|
| 1 | 配置 GLM API key 和视觉参数 | `config.py` | 低 |
| 2 | 实现帧采样：OpenCV 提取帧 → 缩放 640px → base64 | `services/vision_clipper.py` | 低 |
| 3 | 实现 GLM 视觉分析（短视频单轮 / 长视频两轮采样） | `services/vision_clipper.py` + GLM 输出校验 | 中：GLM rate limit |
| 4 | 实现后处理（时长约束 + 0.5s 缓冲 + 边界 clamp） | `services/vision_clipper.py` | 低 |
| 5 | 实现 FFmpeg 切割，统一输出 .mp4 | `services/video_processor.py` | 低：需确认 FFmpeg 已安装 |
| 6 | 新增 `/api/clip_v2` + `/api/clip_v2/download/` 路由 | `app.py` | 低 |
| 7 | 前端：新 Tab 面板 + 上传表单 + loader + 下载按钮 | `index.html` | 低 |
| 8 | 更新 requirements.txt | | 低 |
| 9 | 测试：多种格式、不同时长、GLM 错误场景 | | 中 |

---

## 12. 安全与边界处理

| 风险 | 防护 |
|------|------|
| 上传非视频文件 | 校验 Content-Type（`video/mp4`, `video/quicktime`, `video/x-msvideo`, `video/webm`） |
| 文件超 200MB | `MAX_CONTENT_LENGTH` + `request.content_length` 预检 |
| 路径穿越下载 | `send_from_directory(CLIP_OUT_DIR, filename)` 限制目录 |
| 文件名冲突 | 使用 `uuid4()` 重命名 |
| 磁盘膨胀 | 每次上传前清理 uploads/ 中 >24h 的文件 |
| API Key 泄露 | 后续迁移到环境变量 |
| GLM 限流 | 路由入口加互斥锁（开发阶段）或请求队列（生产阶段） |

---

## 13. 待确认

| # | 问题 |
|---|------|
| 1 | FFmpeg 是否已安装在开发机上？是否在 PATH 中？ |
| 2 | 是否需要先支持"预览模式"（只返回 JSON 不下刀）确认时间段，再调 FFmpeg 实际切割？ |
