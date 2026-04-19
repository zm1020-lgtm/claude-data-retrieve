#!/usr/bin/env bash
# Installs a daily 8:00 AM cron job for the whale briefing.
# Run once on your local machine: ./schedule.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$REPO_DIR/run_briefing.sh"
LOG="$REPO_DIR/briefing.log"
CRON_ENTRY="0 8 * * * cd \"$REPO_DIR\" && \"$RUNNER\" >> \"$LOG\" 2>&1"

# Check if the entry already exists
if crontab -l 2>/dev/null | grep -qF "$RUNNER"; then
    echo "Cron job already installed:"
    crontab -l | grep "$RUNNER"
    exit 0
fi

# Append to existing crontab (preserving other entries)
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "Scheduled: daily at 8:00 AM"
echo "Runner:    $RUNNER"
echo "Log:       $LOG"
echo ""
echo "Verify with: crontab -l"
echo "Remove with: crontab -e  (delete the whale briefing line)"
