#!/bin/bash
# newpod.sh - stand up a swap pod wherever there is GPU capacity, deploy, and get ready.
#
#   ./newpod.sh                find capacity -> create -> deploy -> build -> set face -> ready
#   ./newpod.sh --no-launch    do everything but don't print/launch the client command
#   FACE=ronaldo ./newpod.sh   choose which library face to set
#
# No volume is used: git + this script ARE the persistent state. A fresh pod takes ~3-5 min.
set -uo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

IMAGE="runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404"
DCS="${DCS:-EU-RO-1 EU-CZ-1 EU-SE-1 EU-FR-1 EU-NL-1}"
GPUS="${GPUS:-NVIDIA GeForce RTX 4090|NVIDIA GeForce RTX 3090|NVIDIA L4|NVIDIA RTX A4000|NVIDIA RTX A5000|NVIDIA RTX A6000|NVIDIA A40}"
FACE="${FACE:-edwestwick}"
PY=./venv/bin/python; [ -x "$PY" ] || PY=python3

echo "[newpod] looking for GPU capacity..."
POD="" DC="" GPU=""
for dc in $DCS; do
  IFS='|' read -r -a arr <<<"$GPUS"
  for gpu in "${arr[@]}"; do
    out=$(perl -e 'alarm 120; exec @ARGV' runpodctl pod create --name faceswap-live \
            --image "$IMAGE" --gpu-id "$gpu" --data-center-ids "$dc" \
            --container-disk-in-gb 25 --ports "22/tcp,8000/http" 2>&1)
    id=$(printf '%s' "$out" | "$PY" -c "
import sys, re
m = re.search(r'\"id\"\s*:\s*\"([a-z0-9]{10,})\"', sys.stdin.read())
print(m.group(1) if m else '')" 2>/dev/null)
    if [ -n "$id" ]; then POD="$id"; DC="$dc"; GPU="$gpu"; echo "  ✅ $dc / $gpu -> pod $POD"; break 2; fi
    echo "  ✗ $dc / $(printf '%s' "$gpu" | cut -c8-22)"
  done
done

if [ -z "$POD" ]; then
  echo "[newpod] no GPU capacity right now. Try again shortly - availability changes by the minute."
  exit 2
fi

echo "[newpod] waiting for the ssh endpoint..."
IP=""; PORT=""
for i in $(seq 1 30); do
  read -r IP PORT <<<"$(runpodctl ssh info "$POD" 2>/dev/null | "$PY" -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('ip',''), d.get('port','')) if not d.get('error') else print('','')
except Exception:
    print('','')")"
  [ -n "$IP" ] && [ -n "$PORT" ] && break
  sleep 15
done
[ -z "$IP" ] && { echo "[newpod] pod never exposed ssh"; exit 1; }
echo "  ssh: $IP:$PORT"

sshc() { ssh -i ~/.runpod/ssh/runpodctl-ssh-key -o StrictHostKeyChecking=accept-new \
  -o LogLevel=ERROR -o ConnectTimeout=15 \
  -p "$PORT" "root@$IP" "$@"; }

echo "[newpod] uploading code"
POD_ID="$POD" POD_IP="$IP" POD_PORT="$PORT" ./deploy.sh 2>&1 | sed 's/^/  /'

echo "[newpod] building (venv + models, ~3 min)"
sshc 'cd /workspace && (setsid nohup /workspace/bootstrap.sh bg > /workspace/boot.log 2>&1 < /dev/null &)'
for i in $(seq 1 30); do
  sleep 20
  sshc 'grep -q "service started" /workspace/boot.log 2>/dev/null' && { echo "  build done"; break; }
  printf '.'
done

URL="https://$POD-8000.proxy.runpod.net"
echo ""
echo "[newpod] waiting for the service at $URL"
for i in $(seq 1 20); do
  curl -s -m 10 "$URL/health" 2>/dev/null | grep -q '"ok"' && { echo "  ✅ service ready"; break; }
  sleep 10
done

sshc '/workspace/restart_service.sh' >/dev/null 2>&1
sleep 25
SWAP_URL="$URL" "$PY" faces.py set "$FACE" 2>&1 | tail -1

echo ""
echo "  pod      : $POD  ($DC / $GPU)"
echo "  service  : $URL"
echo "  face     : $FACE"
echo ""
echo "  RUN THIS:"
echo "    cd ~/Developer/faceswap"
echo "    SWAP_URL=\"$URL\" ./venv/bin/python client.py --ws --source ~/Developer/faceswap/faces/$FACE.jpg"
