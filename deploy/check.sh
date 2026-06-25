#!/bin/bash
# 服务器自检脚本 —— push 后自动跑 / Reasonix 远程诊断
# 用法：bash /opt/youtube-radar/deploy/check.sh

set -e
APP_DIR="/opt/youtube-radar"

echo "╔══════════════════════════════════════╗"
echo "║   YouTube Radar 服务器自检          ║"
echo "╚══════════════════════════════════════╝"

# ── 1. Python 导入检查 ──
echo ""
echo "── 1/5 Python 导入 ──"
cd "$APP_DIR"
source venv/bin/activate
python -c "from app import app; print('  ✅ Flask 导入 OK')" 2>&1 || echo "  ❌ Flask 导入失败"
python -c "from models.user import init_db; init_db(); print('  ✅ SQLite 导入 OK')" 2>&1 || echo "  ❌ SQLite 导入失败"
deactivate

# ── 2. Nginx 配置 ──
echo ""
echo "── 2/5 Nginx 配置 ──"
sudo nginx -t 2>&1 | tail -1

# ── 3. 本地端口 ──
echo ""
echo "── 3/5 Gunicorn 端口 ──"
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/ --max-time 5 2>/dev/null || echo "000")
echo "  HTTP $CODE (5000端口)"

# ── 4. HTTPS 公网 ──
echo ""
echo "── 4/5 HTTPS 公网 ──"
HTTPS_CODE=$(curl -s -o /dev/null -w "%{http_code}" https://www.videohunt.top/ --max-time 10 2>/dev/null || echo "000")
echo "  HTTP $HTTPS_CODE (www.videohunt.top)"

# ── 5. 最近错误日志 ──
echo ""
echo "── 5/5 最近错误日志 ──"
ERRORS=$(journalctl -u youtube-radar --since "10 min ago" --no-pager 2>/dev/null | grep -i "error\|traceback\|exception" | tail -5)
if [ -z "$ERRORS" ]; then
    echo "  ✅ 无错误"
else
    echo "$ERRORS"
fi

echo ""
echo "── 磁盘 ──"
df -h / | tail -1

echo ""
echo "═══ 自检完成 ═══"
