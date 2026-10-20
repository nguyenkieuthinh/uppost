#!/bin/bash
# Retry the single-image photo post until TikTok's 24-hour share cap frees a slot.
#
# The cap counts every share created in a rolling 24-hour window, not the ones
# waiting for approval, so cancelling a draft does not free a slot. A slot comes
# back when the oldest share drops out of the window. The top 32 bits of a
# publish id are a Unix time, so the wait can be worked out:
#
#   python3 -c "import datetime; print(datetime.datetime.fromtimestamp(7698800536095115285 >> 32))"
#
# Note: --music is recorded but TikTok ignores it on a photo draft. The sound
# has to be picked in the app before publishing.
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
