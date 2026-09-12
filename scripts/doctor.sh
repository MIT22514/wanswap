#!/bin/bash
# doctor.sh - check every prerequisite and say exactly what is missing.
set -uo pipefail
cd "$(dirname "$0")/.."
ok=0; warn=0

pass() { printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail() { printf "  \033[31m✗\033[0m %s\n" "$1"; ok=1; }
note() { printf "  \033[33m!\033[0m %s\n" "$1"; warn=1; }

echo "wanswap doctor"
echo

echo "local"
command -v python3 >/dev/null && pass "python3 $(python3 -V 2>&1 | cut -d' ' -f2)" || fail "python3 missing"
[ -d venv ] && pass "venv present" || note "no venv - run: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
python3 - <<'PY' 2>/dev/null && pass "python deps importable" || note "python deps missing - pip install -r requirements.txt"
import cv2, requests, websocket, certifi, numpy
PY
command -v jq >/dev/null && pass "jq" || note "jq not installed (optional)"

echo
echo "gpu provider"
command -v runpodctl >/dev/null && pass "runpodctl $(runpodctl version 2>/dev/null | head -c 20)" || fail "runpodctl missing - see docs/ARCHITECTURE.md"
if runpodctl user >/dev/null 2>&1; then pass "runpodctl authenticated"; else fail "runpodctl not authenticated - run: runpodctl config --apiKey <key>"; fi
if [ -n "${RUNPOD_API_KEY:-}" ]; then pass "RUNPOD_API_KEY set"; else note "RUNPOD_API_KEY not exported (runpodctl may still work from its own config)"; fi

echo
echo "obs"
[ -d /Applications/OBS.app ] && pass "OBS installed" || fail "OBS missing - https://obsproject.com"
if lsof -nP -iTCP:4455 -sTCP:LISTEN >/dev/null 2>&1; then
  pass "obs-websocket listening on 4455 (auto-config available)"
else
  note "obs-websocket not listening - in OBS: Tools > WebSocket Server Settings > Enable"
fi

echo
echo "network"
if lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; then
  note "port 8081 already in use (a client may already be running)"
else
  pass "port 8081 free"
fi

echo
[ "$ok" = 0 ] && echo "ready to run." || echo "fix the ✗ items above before starting."
[ "$warn" = 1 ] && echo "(the ! items are non-fatal)"
exit $ok
