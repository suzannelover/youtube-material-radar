"""
app.py
職責：Flask 路由層，只負責接收請求、調用 service、返回響應
業務邏輯全部在 services/ 目錄下
"""

import os
from flask import Flask, request, jsonify, send_from_directory

from services.keyword     import extract_keywords
from services.search      import search_youtube_funnel
from services.filter      import filter_by_date, analyze_and_filter
from services.copy_writer import generate_copy
from services.clipper     import analyze_clip
from config               import DOWNLOAD_DIR, OUTPUT_DIR

# 確保運行時目錄存在
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR,   exist_ok=True)

app = Flask(__name__, static_folder=".")


# ── 靜態頁面 ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ── 視頻推薦 ──────────────────────────────────────────────────────────────────

@app.route("/api/recommend", methods=["POST"])
def recommend():
    data       = request.get_json()
    user_input = data.get("query", "").strip()
    days       = int(data.get("days", 90))

    if not user_input:
        return jsonify({"error": "請輸入素材描述"}), 400

    try:
        keywords = extract_keywords(user_input)
        videos   = search_youtube_funnel(keywords)

        if not videos:
            return jsonify({"error": "未搜到任何視頻，請換個描述試試"}), 404

        videos = filter_by_date(videos, days)
        cards  = analyze_and_filter(user_input, videos)

        return jsonify({
            "keywords": keywords.get("display", ""),
            "cards":    cards
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        print(f"[ERROR /api/recommend] {e}")
        return jsonify({"error": str(e)}), 500


# ── 文案生成 ──────────────────────────────────────────────────────────────────

@app.route("/api/generate_copy", methods=["POST"])
def api_generate_copy():
    data     = request.get_json()
    topic    = data.get("topic", "").strip()
    subtitle = data.get("subtitle", "").strip()

    if not topic:
        return jsonify({"error": "請輸入核心觀點"}), 400
    if not subtitle:
        return jsonify({"error": "請上傳字幕文件"}), 400

    try:
        result = generate_copy(topic, subtitle)
        return jsonify(result)
    except Exception as e:
        print(f"[ERROR /api/generate_copy] {e}")
        return jsonify({"error": str(e)}), 500


# ── 智能剪輯（第一期：定位時間段）────────────────────────────────────────────

@app.route("/api/clip", methods=["POST"])
def api_clip():
    """
    請求體：
    {
        "url": "https://www.youtube.com/watch?v=xxx",
        "clip_description": "找官員被追問支支吾吾的那段",
        "subtitle": "...手動上傳的字幕內容（可選）..."
    }

    返回：
    {
        "video_id": "xxx",
        "subtitle_available": true,
        "segments": [
            {
                "start_sec": 80,
                "end_sec": 140,
                "start_fmt": "1:20",
                "end_fmt": "2:20",
                "reason": "部長被追問電價時明顯回避"
            }
        ],
        "total_segments": 1,
        "message": "共找到 1 個匹配片段。"
    }
    """
    data             = request.get_json()
    url              = data.get("url", "").strip()
    clip_description = data.get("clip_description", "").strip()
    subtitle_content = data.get("subtitle", "").strip()  # 新增：手動上傳的字幕

    if not url:
        return jsonify({"error": "請輸入視頻 URL"}), 400
    if not clip_description:
        return jsonify({"error": "請描述你想找的片段點位"}), 400

    try:
        result = analyze_clip(url, clip_description, subtitle_content)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"[ERROR /api/clip] {e}")
        return jsonify({"error": str(e)}), 500


# ── 啟動 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("啟動中... 訪問 http://localhost:5000")
    app.run(debug=True, port=5000)
