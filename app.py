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
from services.clipper         import analyze_clip
from services.vision_clipper import analyze_video
from services.video_processor import save_upload, cut_video
from config                   import (DOWNLOAD_DIR, OUTPUT_DIR,
                                       UPLOAD_DIR, CLIP_OUT_DIR,
                                       CLIP_DEFAULT_DURATION, CLIP_MIN_DURATION,
                                       CLIP_MAX_DURATION, MAX_UPLOAD_SIZE_MB)

# 確保運行時目錄存在
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR,   exist_ok=True)

app = Flask(__name__, static_folder=".")
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE_MB * 1024 * 1024


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


# ── 智能剪輯 V2（上傳影片 + GLM 視覺剪輯）─────────────────────────────────

@app.route("/api/clip_v2", methods=["POST"])
def api_clip_v2():
    """
    請求：multipart/form-data
        video:       <文件>  （mp4/mov/avi/webm）
        description: "找亮點片段"
        duration:    20       （可選，15/20/25/30）

    返回：
    {
        "status":       "ok",
        "filename":     "clip_abc123.mp4",
        "duration":     18.5,
        "start_sec":    42.0,
        "end_sec":      60.5,
        "download_url": "/api/clip_v2/download/clip_abc123.mp4",
        "reason":       "候選人回答時表情生動"
    }
    """
    if "video" not in request.files:
        return jsonify({"error": "請上傳影片檔案"}), 400

    file = request.files["video"]
    if not file.filename:
        return jsonify({"error": "請選擇影片檔案"}), 400

    description = request.form.get("description", "").strip()
    if not description:
        return jsonify({"error": "請輸入剪輯描述"}), 400

    try:
        target = int(request.form.get("duration", CLIP_DEFAULT_DURATION))
    except ValueError:
        target = CLIP_DEFAULT_DURATION
    target = max(CLIP_MIN_DURATION, min(CLIP_MAX_DURATION, target))

    try:
        # 1. 保存上传
        video_path = save_upload(file)

        # 2. GLM 视觉分析
        seg = analyze_video(str(video_path), description, target)

        # 3. FFmpeg 切割
        duration = seg["end_sec"] - seg["start_sec"]
        out_path = cut_video(video_path, seg["start_sec"], duration)

        return jsonify({
            "status":        "ok",
            "filename":      out_path.name,
            "duration":      round(duration, 1),
            "start_sec":     round(seg["start_sec"], 1),
            "end_sec":       round(seg["end_sec"], 1),
            "start_fmt":     seg["start_fmt"],
            "end_fmt":       seg["end_fmt"],
            "download_url":  f"/api/clip_v2/download/{out_path.name}",
            "reason":        seg["reason"],
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        print(f"[ERROR /api/clip_v2] {e}")
        return jsonify({"error": "伺服器缺少 FFmpeg，請確認已安裝"}), 500
    except Exception as e:
        print(f"[ERROR /api/clip_v2] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/clip_v2/download/<path:filename>")
def api_clip_v2_download(filename: str):
    """下载剪辑后的视频"""
    return send_from_directory(CLIP_OUT_DIR, filename)


# ── 啟動 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("啟動中... 訪問 http://localhost:5000")
    app.run(debug=True, port=5000)
