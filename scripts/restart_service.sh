#!/bin/bash
# restart the swap service safely.
# NOTE: the pkill pattern uses a bracket so it does not match the caller's own command line.
pkill -9 -f "[u]vicorn" 2>/dev/null
sleep 2
cd /workspace
export SWAP_KIND=hyperswap
setsid nohup /workspace/venv/bin/python -m uvicorn swap_service:app \
  --host 0.0.0.0 --port 8000 --log-level warning > /workspace/service.log 2>&1 < /dev/null &
sleep 3
