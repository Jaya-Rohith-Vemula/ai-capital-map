#!/bin/sh
# Run (or resume) the backfill in the background, keeping the Mac awake while
# it runs. caffeinate -i stops idle sleep; on battery a closed lid still
# sleeps the Mac, so keep it on the charger. Follow it with: tail -f logs/*.log
cd "$(dirname "$0")"
nohup caffeinate -i python3 run.py "$@" > logs/nohup.out 2>&1 &
echo "started (pid $!). Follow it: tail -f $(pwd)/logs/\$(ls -t logs | grep .log | head -1)"
