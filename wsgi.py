"""
wsgi.py
Gunicorn 生产入口 —— 与 app.py 的 app.run() 互斥
本地开发：python app.py
生产部署：gunicorn -c deploy/gunicorn.conf.py wsgi:app
"""

import os

# 确保运行时目录存在
from config import DOWNLOAD_DIR, OUTPUT_DIR, UPLOAD_DIR, CLIP_OUT_DIR

for d in [DOWNLOAD_DIR, OUTPUT_DIR, UPLOAD_DIR, CLIP_OUT_DIR]:
    os.makedirs(d, exist_ok=True)

from app import app

if __name__ == "__main__":
    # 仅备用：直接 python wsgi.py 也能启动
    from gunicorn.app.wsgiapp import run
    run()
