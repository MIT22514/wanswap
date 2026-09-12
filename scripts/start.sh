#!/bin/bash
# Live face swap - one command, works from a cold/stopped pod.
#
#   ./start.sh                    webcam
#   ./start.sh --video clip.mp4   test from a file
#   ./start.sh --senders 6        more fps (more lag)
#
# What it does:
#   1. checks the service on RunPod's public HTTPS proxy (URL is stable: <podid>-8000.proxy.runpod.net)
#   2. if the pod is stopped, starts it (keeps your $ credit, nothing is rebuilt)
#   3. discovers the pod's CURRENT ssh ip/port (they change on every restart)
#   4. runs the bootstrap on the pod to re-apply container-level bits and start the service
#   5. launches the client and serves MJPEG for OBS on http://127.0.0.1:8081/stream
set -e
cd "$(dirname "$0")"

ulimit -n 4096 2>/dev/null || true

POD_ID="${POD_ID:-${POD_ID}}"
SWAP_URL="${SWAP_URL:-https://$POD_ID-8000.proxy.runpod.net}"
RUNPODCTL="$HOME/.local/bin/runpodctl"
command -v runpodctl >/dev/null 2>&1 && RUNPODCTL="runpodctl"
IDENTITY="$HOME/.runpod/ssh/runpodctl-ssh-key"

PY="./venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[start] first run: installing client deps (one time)..."
  python3 -m venv venv
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install --quiet opencv-python requests numpy
fi

# NOTE: RunPod's proxy answers 200 with an HTML "waiting" page while the backend is down,
# so a plain HTTP check is not enough - we must see the service's actual JSON.
service_up() { curl -s -m 8 "$SWAP_URL/health" 2>/dev/null | grep -q '"ok": *true'; }

if service_up; then
  echo "[start] GPU service already running"
else
  echo "[start] service not responding - checking pod state..."
  # NOTE: 'pod list' only returns RUNNING pods, so a stopped pod reads as ''. Use 'pod get'.
  running=$("$RUNPODCTL" pod get "$POD_ID" 2>/dev/null | python3 -c "
import sys,json
try: print(json.load(sys.stdin).get('runtimeStatus',''))
except Exception: print('')" 2>/dev/null | head -1)

  if [ "$running" != "running" ]; then
    echo "[start] pod is '$running' -> starting it (no rebuild, this just resumes billing)"
    "$RUNPODCTL" pod start "$POD_ID" >/dev/null 2>&1 || true
    echo "[start] waiting for the pod to boot..."
    for i in $(seq 1 40); do sleep 6; "$RUNPODCTL" pod get "$POD_ID" 2>/dev/null | grep -q '"runtimeStatus": *"running"' && break; done
  fi

  echo "[start] discovering pod ssh endpoint..."
  read -r PIP PPORT <<<"$("$RUNPODCTL" ssh info "$POD_ID" 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('ip',''), d.get('port',''))
except Exception: print('', '')
")"
  if [ -z "$PIP" ] || [ -z "$PPORT" ]; then
    echo "[start] ERROR: could not get the pod's ssh endpoint. Is the pod running? ($RUNPODCTL pod list)"
    exit 1
  fi
  echo "[start] pod ssh: $PIP:$PPORT"

  # sync code BEFORE the bootstrap runs, so the pod always bootstraps with current code
  if ! POD_IP="$PIP" POD_PORT="$PPORT" ./deploy.sh --check >/dev/null 2>&1; then
    echo "[start] pod code is stale - syncing before bootstrap (automatic)"
    POD_IP="$PIP" POD_PORT="$PPORT" ./deploy.sh
  fi

  ( nohup ssh -i "$IDENTITY" \
      -o StrictHostKeyChecking=accept-new \
      -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o LogLevel=ERROR \
      -p "$PPORT" "root@$PIP" \
      '/workspace/bootstrap.sh bg > /workspace/serve.log 2>&1' > wake.log 2>&1 & )

  echo "[start] waiting for the GPU service (first boot after a stop can take ~2 min)..."
  for i in $(seq 1 40); do
    sleep 6
    if service_up; then echo "[start] service ready"; break; fi
  done
  if ! service_up; then
    echo "[start] ERROR: service did not come up. Check: $RUNPODCTL ssh info $POD_ID"
    exit 1
  fi
fi

echo "[start] starting client (Ctrl-C to stop)"
echo "[start] OBS URL -> http://127.0.0.1:8081/stream"
"$PY" -u client.py --no-ssh "$@"
