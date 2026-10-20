#!/bin/bash
# Retry the single-image photo post until TikTok's 24-hour share cap frees a slot.
cd /home/thinh/antigravity/uppost || exit 1
IMG=https://nguyenkieuthinh.github.io/uppost/wallpapers/wallpaper-01.jpg
MUSIC=7525403525971528465
for i in $(seq 1 120); do
  echo "=== attempt $i  $(date '+%Y-%m-%d %H:%M:%S')"
  out=$(python3 uppost.py photo "test" "$IMG" --music "$MUSIC" 2>&1)
  echo "$out" | tail -12
  if echo "$out" | grep -q 'publish_id'; then
    echo "SUCCESS at $(date)"
    exit 0
  fi
  sleep 1200
done
echo "gave up after 120 attempts"
