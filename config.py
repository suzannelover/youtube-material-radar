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

# 上传 / 输出目录
UPLOAD_DIR            = "uploads"
CLIP_OUT_DIR          = "outputs/clips"
MAX_UPLOAD_SIZE_MB    = 200
