# ─── 全局配置 ─────────────────────────────────────────────────────────────────

QWEN_API_KEY      = "sk-24dec5247fff469e9758bcd31fe3a324"
SEARCH_PER_QUERY  = 5
TARGET_CARD_COUNT = 8
FUNNEL_THRESHOLD  = 12

TW_MEDIA = [
    "中天新聞",
    "新聞大白話",
    "東森新聞",
    "TVBS",
    "三立新聞",
    "民視新聞",
    "鏡新聞",
]

# 下载 / 输出目录
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR   = "outputs"

# ─── CLIP V2 配置 ─────────────────────────────────────────────────────────────

# GLM-4.6V-Flash 视觉模型
GLM_API_KEY           = "38657a05f7a140c186ad877d9daf4c17.xi05ZYsDVlVLRXIN"   # ← 请填入你的智谱 API Key
GLM_MODEL             = "glm-4.6v-flash"
GLM_BASE_URL          = "https://open.bigmodel.cn/api/paas/v4/"

# 视觉参数
VISION_FRAME_W        = 640         # 帧图片宽度
VISION_QUALITY        = 70          # JPEG 质量 %
VISION_USE_THINKING   = False       # 是否启用 GLM 思考模式

# 剪辑参数
CLIP_DEFAULT_DURATION = 20          # 默认目标秒数
CLIP_MIN_DURATION     = 15
CLIP_MAX_DURATION     = 30

# ─── CLIP V2 批量剪辑配置 ────────────────────────────────────────────────────

BATCH_MIN_SEGMENTS    = 5           # 批量最少片段数
BATCH_MAX_SEGMENTS    = 8           # 批量最多片段数
BATCH_SEG_MIN_LEN     = 12          # 单段最短（去重后合法下限）
BATCH_SEG_DEFAULT     = 17          # 批量补段时默认段长
BATCH_SEG_TARGET_MIN  = 15          # 批量单段最短目标
BATCH_SEG_TARGET_MAX  = 20          # 批量单段最长目标
BATCH_SEG_GAP         = 3           # 片段最小间隔（秒）
BATCH_OVERLAP_RATIO   = 0.3         # 去重：重叠比例阈值
BATCH_FRAME_STEP_MIN  = 2.5         # 批量采样最小步长

# 上传 / 输出目录
UPLOAD_DIR            = "uploads"
CLIP_OUT_DIR          = "outputs/clips"
MAX_UPLOAD_SIZE_MB    = 200
