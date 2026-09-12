#!/bin/bash
# Pod bootstrap — idempotent. Run once per pod start.
#
# Everything heavy lives on the persistent volume (/workspace): venv, models, code, token.
# This script re-applies the CONTAINER-LEVEL things that are lost whenever the container
# restarts, then starts the service.
#
#   bootstrap.sh          -> set up + start service in background
#   bootstrap.sh serve    -> set up + run service in FOREGROUND (held open by the client's SSH)
set -e
MODE="${1:-bg}"

# ---------- 1. CUDA libraries into the system loader path ----------
if [ ! -e /usr/lib/x86_64-linux-gnu/libcudart.so.12 ]; then
  echo "[bootstrap] linking CUDA libs"
  mkdir -p /usr/lib/x86_64-linux-gnu
  n=0
  for d in /usr/local/lib/python3.12/dist-packages/nvidia/*/lib; do
    [ -d "$d" ] || continue
    for f in "$d"/*.so*; do
      [ -e "$f" ] || continue
      ln -sf "$f" "/usr/lib/x86_64-linux-gnu/$(basename "$f")" && n=$((n+1))
    done
  done
  ldconfig 2>/dev/null || true
  echo "[bootstrap]   linked $n files"
else
  echo "[bootstrap] CUDA libs already present"
fi

# ---------- 2. OpenGL/EGL libs (MediaPipe FaceLandmarker needs these) ----------
# Without them MediaPipe fails to load and the service silently falls back to the old
# detector - which brings the "freezing face" problem back with no obvious error.
if [ ! -e /usr/lib/x86_64-linux-gnu/libEGL.so.1 ]; then
  echo "[bootstrap] installing GL/EGL libs for MediaPipe (this takes ~1 min)"
  apt-get update -qq || true
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    libegl1 libgl1 libgles2 libglib2.0-0 libsm6 libxext6 >/dev/null 2>&1 || \
    echo "[bootstrap]   WARNING: GL/EGL install failed - MediaPipe may not load"
else
  echo "[bootstrap] GL/EGL libs already present"
fi

# ---------- 3. venv + python deps (on the volume, so normally already there) ----------
if [ ! -x /workspace/venv/bin/python ]; then
  echo "[bootstrap] creating venv"
  python3 -m venv /workspace/venv
fi
if ! /workspace/venv/bin/python -c "import onnxruntime, insightface, fastapi, uvicorn, cv2, mediapipe" 2>/dev/null; then
  echo "[bootstrap] installing python deps"
  /workspace/venv/bin/pip install -q --upgrade pip
  /workspace/venv/bin/pip install -q "onnxruntime-gpu==1.22.0" insightface opencv-python-headless \
    numpy pillow fastapi uvicorn python-multipart mediapipe websockets
fi

# ---------- 4. verify CUDA (never silently fall back to CPU) ----------
/workspace/venv/bin/python - <<'PY'
import sys
import onnxruntime as ort
prov = ort.get_available_providers()
if "CUDAExecutionProvider" not in prov:
    print("  !! CUDA NOT AVAILABLE:", prov)
    sys.exit(1)
print("  cuda ok:", prov[0])
PY

# ---------- 5. models ----------
mkdir -p /workspace/models
if [ ! -f /workspace/models/inswapper_128_fp16.onnx ]; then
  echo "[bootstrap] fetching inswapper"
  curl -sL -m 900 "https://huggingface.co/hacksider/deep-live-cam/resolve/main/inswapper_128_fp16.onnx?download=true" \
    -o /workspace/models/inswapper_128_fp16.onnx
fi
mkdir -p /workspace/models/candidates
if [ ! -f /workspace/models/candidates/hyperswap_1c_256.onnx ]; then
  echo "[bootstrap] fetching hyperswap_1c_256 (403MB)"
  curl -sL -m 900 -o /workspace/models/candidates/hyperswap_1c_256.onnx \
    "https://github.com/facefusion/facefusion-assets/releases/download/models-3.3.0/hyperswap_1c_256.onnx"
fi

if [ ! -f /workspace/models/face_landmarker.task ]; then
  echo "[bootstrap] fetching MediaPipe face landmarker"
  curl -sL -m 300 -o /workspace/models/face_landmarker.task \
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
fi

# ---------- 6. start the service ----------
cd /workspace
pkill -f "uvicorn swap_service" 2>/dev/null || true
sleep 1

if [ "$MODE" = "serve" ]; then
  echo "[bootstrap] running service in FOREGROUND on 0.0.0.0:8000"
  exec /workspace/venv/bin/python -m uvicorn swap_service:app --host 0.0.0.0 --port 8000 --log-level warning
else
  setsid nohup /workspace/venv/bin/python -m uvicorn swap_service:app \
    --host 0.0.0.0 --port 8000 --log-level warning > /workspace/service.log 2>&1 < /dev/null &
  echo "[bootstrap] service started in background (log: /workspace/service.log)"
fi
