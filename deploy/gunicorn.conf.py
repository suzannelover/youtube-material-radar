# Gunicorn 生产配置
# 用法：gunicorn -c deploy/gunicorn.conf.py wsgi:app

import multiprocessing

# ── 监听 ──
bind = "127.0.0.1:5000"

# ── Worker ──
workers = 4                     # 4核CPU
worker_class = "sync"
threads = 1
timeout = 300                   # 批量模式最长等 5 分钟

# ── 日志 ──
accesslog = "-"                 # stdout
errorlog = "-"
loglevel = "info"

# ── 进程命名 ──
proc_name = "youtube-radar"

# ── 优雅重启 ──
max_requests = 1000             # 每个 worker 处理 1000 请求后重启
max_requests_jitter = 100
graceful_timeout = 30
