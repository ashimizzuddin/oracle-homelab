#!/usr/bin/env bash
# Weekly Docker housekeeping for the Oracle VPS (ai-job-filter production).
#
# Safe variant of `docker system prune -af --volumes`:
#   - never removes images in use (plain `image prune` = dangling only)
#   - never touches volumes (ai-job-filter uses bind mounts, not named volumes)
#   - only clears build cache older than 7 days
set -euo pipefail

LOG="/home/ubuntu/docker-prune.log"

{
  echo "=== $(date -Is) docker prune start ==="
  docker image prune -f
  docker builder prune -f --filter until=168h
  echo "--- disk after ---"
  df -h / | tail -n 1
  docker system df
  echo "=== done ==="
} >> "$LOG" 2>&1

# Keep the log bounded
tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
