#!/bin/bash
# RunPod capacity watcher.
#
# SAFETY: this only ever acts while the marker file exists. That means it cannot
# silently resume billing after we are done - delete the marker and it goes inert.
#   marker: ~/Developer/faceswap/.pod_watch_pending
#
# Silent by default: prints something ONLY when the pod actually starts, so the cron
# job's output (announced to chat) is the notification.
export PATH="$HOME/.local/bin:$PATH"

POD_ID="${POD_ID}"
PENDING="$HOME/Developer/faceswap/.pod_watch_pending"
STATE="$HOME/Developer/faceswap/.pod_watch_state"

# no marker -> inert
[ -f "$PENDING" ] || exit 0

state=$(runpodctl pod get "$POD_ID" 2>/dev/null | python3 -c "
import sys, json
try: print(json.load(sys.stdin).get('runtimeStatus',''))
except Exception: print('')" 2>/dev/null)

if [ "$state" = "running" ]; then
  # already up: announce once, then disarm so we never restart billing later
  if [ ! -f "$STATE" ]; then
    echo "pod is already running"
    touch "$STATE"
    rm -f "$PENDING"
  fi
  exit 0
fi

out=$(runpodctl pod start "$POD_ID" 2>&1)
if echo "$out" | grep -q '"error"'; then
  exit 0          # still no capacity - stay silent, try again next tick
fi

# success
rm -f "$PENDING"
touch "$STATE"
bal=$(runpodctl user 2>/dev/null | python3 -c "
import sys, json
try: print('%.2f' % json.load(sys.stdin).get('clientBalance', 0))
except Exception: print('?')" 2>/dev/null)
MSG="RunPod capacity freed up - the GPU pod is STARTING again (balance \$$bal). Ready to run the udp2raw + SRT tunnel test whenever you want."
echo "$MSG"
# send it ourselves so the cron job needs no delivery target
# notify somewhere if configured, e.g. NOTIFY_TARGET="+15551234567"
[ -n "${NOTIFY_TARGET:-}" ] && openclaw message send --channel whatsapp \
  --target "$NOTIFY_TARGET" -m "$MSG" >/dev/null 2>&1 || true
