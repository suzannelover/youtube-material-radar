#!/bin/bash
# 定时清理 24 小时前的上传和输出文件
# crontab：0 3 * * * /opt/youtube-radar/deploy/cleanup.sh

find /opt/youtube-radar/uploads/    -type f -mmin +1440 -delete 2>/dev/null
find /opt/youtube-radar/outputs/    -type f -mmin +1440 -delete 2>/dev/null
find /opt/youtube-radar/downloads/  -type f -mmin +1440 -delete 2>/dev/null
echo "[cleanup] $(date): cleaned old files"
