#!/bin/bash
# deploy.sh - push the CANONICAL code to a pod, so no pod ever drifts.
#
#   ./deploy.sh --check     report what differs, change nothing
#   ./deploy.sh             upload whatever differs, then restart the service
#   POD_ID=xxx ./deploy.sh  target a different pod
#
# The pod tracks versions in /workspace/VERSION (md5 of each file), so drift is detectable.
set -uo pipefail
cd "$(dirname "$0")"

POD_ID="${POD_ID:-${POD_ID}}"
MODE="${1:-deploy}"

# code that must match everywhere. Models/venv live on the volume and are not re-uploaded.
CODE="swap_service.py bootstrap.sh restart_service.sh"   # pod-side files only;
                                                          # client.py/faces.py run on the Mac
EXTRA=".auth"

PY=./venv/bin/python
[ -x "$PY" ] || PY=python3

if [ -n "${POD_IP:-}" ] && [ -n "${POD_PORT:-}" ]; then
  IP="$POD_IP"; PORT="$POD_PORT"
  echo "  using supplied endpoint $IP:$PORT"
else
read -r IP PORT <<<"$(runpodctl ssh info "$POD_ID" 2>/dev/null | "$PY" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('ip',''), d.get('port','')) if not d.get('error') else print('','')
except Exception:
    print('','')")"

if [ -z "$IP" ] || [ -z "$PORT" ]; then
  echo "  cannot reach pod $POD_ID (stopped, or no ssh endpoint yet)"
  exit 2
fi
fi

sshc() { ssh -i ~/.runpod/ssh/runpodctl-ssh-key -o StrictHostKeyChecking=accept-new \
  -o LogLevel=ERROR -o ConnectTimeout=15 \
  -p "$PORT" "root@$IP" "$@"; }

local_md5() { md5 -q "$1" 2>/dev/null || md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

echo "  pod $POD_ID at $IP:$PORT"
stale=""
printf "  %-22s %-10s %-10s\n" "file" "local" "remote"
for f in $CODE; do
  lm="$(local_md5 "$f" | cut -c1-8)"
  rm_="$(sshc "md5sum /workspace/$f 2>/dev/null | cut -c1-8" 2>/dev/null | tr -d '\r\n')"
  [ -z "$rm_" ] && rm_="MISSING"
  mark=""
  [ "$lm" != "$rm_" ] && { mark="  <-- STALE"; stale="$stale $f"; }
  printf "  %-22s %-10s %-10s%s\n" "$f" "$lm" "$rm_" "$mark"
done

if [ -z "$stale" ]; then
  echo "  ✅ in sync - nothing to do"
  exit 0
fi

if [ "$MODE" = "--check" ]; then
  echo "  stale:$stale"
  exit 1
fi

echo "  uploading:$stale"
for f in $stale; do
  if cat "$f" | sshc "cat > /workspace/$f" 2>/dev/null; then
    [ "$f" = "bootstrap.sh" ] && sshc "chmod +x /workspace/bootstrap.sh"
    [ "$f" = "restart_service.sh" ] && sshc "chmod +x /workspace/restart_service.sh"
    echo "    $f"
  else
    echo "    $f FAILED"
  fi
done

# auth token and face library (not versioned in git, but needed on the pod)
[ -f "$EXTRA" ] && cat "$EXTRA" | sshc "cat > /workspace/$EXTRA && chmod 600 /workspace/$EXTRA"
tar czf - faces 2>/dev/null | sshc "tar xzf - -C /workspace" 2>/dev/null && echo "    faces/ synced"

# record the new version
{ for f in $CODE; do echo "$(local_md5 "$f")  $f"; done; } | sshc "cat > /workspace/VERSION"
# uvicorn returns 404 on WebSocket upgrades unless this package is present
if ! sshc '/workspace/venv/bin/python -c "import websockets" 2>/dev/null'; then
  echo "    installing websockets in the pod venv"
  sshc '/workspace/venv/bin/pip install -q websockets' 2>/dev/null
fi

echo "  restarting the service"
sshc "/workspace/restart_service.sh"
sleep 8
echo "  ✅ deployed"
