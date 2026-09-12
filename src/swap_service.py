"""Thin face-swap service for the RunPod pod.

Per-frame face tracking now uses **MediaPipe Face Landmarker in VIDEO mode** (Google),
which is purpose-built for video streams and applies temporal smoothing internally.
That replaces the hand-rolled EMA / optical-flow code, which caused freeing and flicker.

  detection + landmarks : MediaPipe FaceLandmarker (proven, maintained)
  source embedding      : insightface ArcFace (one-off, from the source photo)
  swap                  : hyperswap_1c_256 (256px, model emits its own mask)
  blending              : model mask, warped inside the face ROI only

Routes: POST /source, POST /swap, GET /health
"""
import hmac

import auth
import asyncio
import os
import time

import cv2
import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, Header, UploadFile, WebSocket
from fastapi.responses import JSONResponse, Response

KIND = os.environ.get("SWAP_KIND", "hyperswap")
MODELS = {"sm_kps": None, "sm_bbox": None, 
    "hyperswap": "/workspace/models/candidates/hyperswap_1c_256.onnx",
    "inswapper": "/workspace/models/inswapper_128_fp16.onnx",
}
MODEL_PATH = os.environ.get("SWAP_MODEL", MODELS.get(KIND, MODELS["hyperswap"]))
CROP = 256 if KIND != "inswapper" else 128
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "88"))
LANDMARKER_MODEL = os.environ.get("LANDMARKER_MODEL", "/workspace/models/face_landmarker.task")
MAX_MISS = int(os.environ.get("MAX_MISS", "2"))

# MediaPipe face-mesh indices for the 5 ArcFace alignment points
IDX_EYE_A = (33, 133)      # one eye (centres averaged)
IDX_EYE_B = (362, 263)     # other eye
IDX_NOSE = 1
IDX_MOUTH_A = 61
IDX_MOUTH_B = 291

PROVIDERS = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
             if p in ort.get_available_providers()]

LM_LOCK = __import__("threading").Lock()

app = FastAPI(title="faceswap-service")
S = {"fa": None, "sess": None, "landmarker": None, "source": None,
     "frames": 0, "det_ms": 0.0, "swap_ms": 0.0,
     "kps": None, "bbox": None, "miss": 0, "last_ts": 0,
     "n_swapped": 0, "n_reused": 0, "n_held": 0, "last_out": None}


def _load_auth():
    try:
        return open("/workspace/.auth").read().strip()
    except Exception:
        return ""


AUTH = _load_auth()


def _auth_ok(supplied):
    return auth.auth_ok(supplied, AUTH)


def _check(auth):
    if not _auth_ok(auth):
        return JSONResponse({"ok": False, "error": "bad auth"}, status_code=401)
    return None


@app.on_event("startup")
def _load():
    import insightface
    from insightface.app import FaceAnalysis

    t0 = time.time()
    # insightface is kept ONLY to compute the source face embedding (one-off)
    fa = FaceAnalysis(name="buffalo_l", providers=PROVIDERS)
    fa.prepare(ctx_id=0, det_size=(640, 640))

    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(MODEL_PATH, opts, providers=PROVIDERS)

    landmarker = None
    if os.path.exists(LANDMARKER_MODEL):
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            lm_opts = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=LANDMARKER_MODEL),
                running_mode=vision.RunningMode.IMAGE,   # stateless: our frames arrive out of order
                num_faces=1,
                min_face_detection_confidence=0.25,
                min_face_presence_confidence=0.25,
                min_tracking_confidence=0.25,
            )
            landmarker = vision.FaceLandmarker.create_from_options(lm_opts)
            print("[startup] MediaPipe FaceLandmarker (IMAGE mode) ready", flush=True)
        except Exception as e:
            print(f"[startup] landmarker failed: {str(e)[:120]}", flush=True)

    S["fa"], S["sess"], S["landmarker"] = fa, sess, landmarker
    print(f"[startup] {time.time()-t0:.1f}s | kind={KIND} crop={CROP} | {sess.get_providers()[:1]}",
          flush=True)


def _v(*a):
    if os.environ.get("VERBOSE") == "1":
        print("[trace]", *a, flush=True)


def _decode(raw):
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def _encode(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()


def _biggest(faces):
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def locate(frame):
    """Return (kps 5x2, bbox) using MediaPipe VIDEO-mode landmarks (smoothed)."""
    if S["landmarker"] is None:
        return None, None
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    ts = int(time.time() * 1000)
    if ts <= S["last_ts"]:
        ts = S["last_ts"] + 1
    S["last_ts"] = ts
    with LM_LOCK:
        res = S["landmarker"].detect(mp_img)
    if not res.face_landmarks:
        return None, None
    lm = res.face_landmarks[0]
    h, w = frame.shape[:2]
    pts = np.array([[p.x * w, p.y * h] for p in lm], np.float32)
    kps = np.array([
        pts[list(IDX_EYE_A)].mean(axis=0),
        pts[list(IDX_EYE_B)].mean(axis=0),
        pts[IDX_NOSE],
        pts[IDX_MOUTH_A],
        pts[IDX_MOUTH_B],
    ], np.float32)
    bbox = np.array([pts[:, 0].min(), pts[:, 1].min(),
                     pts[:, 0].max(), pts[:, 1].max()], np.float32)
    # --- temporal smoothing: the anti-jitter fix ---------------------------------
    # Per-frame detection wobbles slightly every frame, and the swap inherits that wobble.
    # EMA is order-independent, unlike MediaPipe's VIDEO tracker (which breaks with our
    # 4 out-of-order senders). Tune with SMOOTH=0.3 (steadier) .. 0.9 (snappier).
    alpha = float(os.environ.get("SMOOTH", "0.55"))
    if S.get("sm_kps") is None:
        S["sm_kps"], S["sm_bbox"] = kps, bbox
    else:
        prev_c = (S["sm_bbox"][:2] + S["sm_bbox"][2:]) / 2.0
        new_c = (bbox[:2] + bbox[2:]) / 2.0
        if np.linalg.norm(new_c - prev_c) > 0.18 * max(frame.shape[:2]):
            S["sm_kps"], S["sm_bbox"] = kps, bbox          # moved too far: new subject, snap
        else:
            S["sm_kps"] = alpha * kps + (1 - alpha) * S["sm_kps"]
            S["sm_bbox"] = alpha * bbox + (1 - alpha) * S["sm_bbox"]
    return S["sm_kps"], S["sm_bbox"]


def _roi_box(bbox, shape, pad=0.30):
    fh, fw = shape[:2]
    x0, y0, x1, y1 = (int(v) for v in bbox)
    px, py = int((x1 - x0) * pad), int((y1 - y0) * pad)
    return (max(0, x0 - px), max(0, y0 - py), min(fw, x1 + px), min(fh, y1 + py))


def _swap_hyperswap(frame, kps, bbox, source_face):
    from insightface.utils import face_align

    crop, M = face_align.norm_crop2(frame, kps, CROP)
    rgb = crop[:, :, ::-1] / 255.0
    blob = ((rgb - 0.5) / 0.5).transpose(2, 0, 1)[None].astype(np.float32)
    emb = source_face.normed_embedding.reshape((1, -1)).astype(np.float32)

    outs = S["sess"].run(None, {"target": blob, "source": emb})
    img = outs[0][0].transpose(1, 2, 0)
    img = (np.clip(img * 0.5 + 0.5, 0, 1) * 255).astype(np.uint8)[:, :, ::-1]
    mask = outs[1][0, 0] if len(outs) > 1 else np.ones((CROP, CROP), np.float32)

    x0, y0, x1, y1 = _roi_box(bbox, frame.shape)
    if x1 <= x0 or y1 <= y0:
        return frame
    rw, rh = x1 - x0, y1 - y0
    inv_roi = cv2.invertAffineTransform(M)
    inv_roi[0, 2] -= x0
    inv_roi[1, 2] -= y0

    warped = cv2.warpAffine(img, inv_roi, (rw, rh),
                            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    m = cv2.warpAffine(mask, inv_roi, (rw, rh), flags=cv2.INTER_LINEAR)
    m = np.clip(cv2.GaussianBlur(m, (0, 0), 1.2), 0, 1)[..., None]

    roi = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (roi * (1.0 - m) + warped.astype(np.float32) * m).astype(np.uint8)
    return frame


@app.get("/health")
def health():
    return {"ok": True, "kind": KIND, "crop": CROP, "locator": "mediapipe" if S["landmarker"] else "insightface",
            "source_set": S["source"] is not None, "frames": S["frames"],
            "avg_det_ms": round(S["det_ms"], 2), "avg_swap_ms": round(S["swap_ms"], 2),
            "swapped": S["n_swapped"], "reused": S["n_reused"], "held": S["n_held"]}


@app.post("/source")
async def set_source(file: UploadFile = File(...), x_auth: str = Header(default="")):
    bad = _check(x_auth)
    if bad:
        return bad
    img = _decode(await file.read())
    if img is None:
        return JSONResponse({"ok": False, "error": "bad image"}, status_code=400)
    face = _biggest(S["fa"].get(img))
    if face is None:
        return JSONResponse({"ok": False, "error": "no face detected"}, status_code=422)
    S["source"] = face
    return {"ok": True, "det_score": round(float(face.det_score), 3),
            "face_px": int(face.bbox[2] - face.bbox[0])}


@app.post("/swap")
async def swap(file: UploadFile = File(...), x_auth: str = Header(default="")):
    bad = _check(x_auth)
    if bad:
        return bad
    if S["source"] is None:
        return JSONResponse({"ok": False, "error": "source face not set"}, status_code=409)
    frame = _decode(await file.read())
    if frame is None:
        return JSONResponse({"ok": False, "error": "bad frame"}, status_code=400)
    _v("1 decoded", frame.shape)

    t0 = time.time()
    kps, bbox = locate(frame)
    det_ms = (time.time() - t0) * 1000
    _v("2 located", "face" if kps is not None else "none")

    t1 = time.time()
    if kps is not None:
        S["kps"], S["bbox"], S["miss"] = kps, bbox, 0
        frame = _swap_hyperswap(frame, kps, bbox, S["source"])
        mode = "swapped"
        S["n_swapped"] += 1
    elif S["kps"] is not None and S["miss"] < MAX_MISS:
        S["miss"] += 1
        frame = _swap_hyperswap(frame, S["kps"], S["bbox"], S["source"])
        mode = "reused"
        S["n_reused"] += 1
    else:
        S["miss"] += 1
        mode = "none"
        S["n_held"] += 1
    _v("3 applied", mode)
    S["last_out"] = frame.copy()
    swp_ms = (time.time() - t1) * 1000

    S["frames"] += 1
    if S["frames"] == 1:
        S["det_ms"], S["swap_ms"] = det_ms, swp_ms
    else:
        S["det_ms"] = S["det_ms"] * 0.9 + det_ms * 0.1
        S["swap_ms"] = S["swap_ms"] * 0.9 + swp_ms * 0.1

    _v("4 encoding")
    return Response(content=_encode(frame), media_type="image/jpeg",
                    headers={"X-Det-Ms": f"{det_ms:.1f}", "X-Swap-Ms": f"{swp_ms:.1f}",
                             "X-Mode": mode, "X-Kind": KIND})

def _process_frame(frame):
    """Blocking detect+swap+encode - must run off the event loop."""
    kps, bbox = locate(frame)
    if kps is not None:
        S["kps"], S["bbox"], S["miss"] = kps, bbox, 0
        out = _swap_hyperswap(frame, kps, bbox, S["source"])
    elif S["kps"] is not None and S["miss"] < MAX_MISS:
        S["miss"] += 1
        out = _swap_hyperswap(frame, S["kps"], S["bbox"], S["source"])
    else:
        S["miss"] += 1
        out = frame
    return _encode(out)


@app.websocket("/ws")
async def ws_stream(ws: WebSocket):
    """Persistent bidirectional frame stream (aims to replace request-per-frame HTTP).

    - text JSON {"op":"ping","t":<ms>} -> replies {"op":"pong","t":<ms>}  (latency probe)
    - binary JPEG frame               -> replies with the swapped JPEG (same bytes format)
    """
    # Authenticate before accepting. An unauthenticated client must not be able to
    # consume GPU time or read swapped frames. Closing before accept() makes
    # Starlette refuse the handshake instead of opening the socket.
    if not _auth_ok(ws.headers.get("x-auth")):
        await ws.close(code=1008)
        return
    await ws.accept()
    n = 0
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("text") is not None:
                await ws.send_text(msg["text"])          # echo ping
                continue
            data = msg.get("bytes")
            if not data:
                continue
            if S["source"] is None:
                await ws.send_bytes(data)
                continue
            frame = _decode(data)
            if frame is None:
                await ws.send_bytes(data)
                continue
            # blocking GPU work -> run off the event loop so the socket stays responsive
            out_bytes = await asyncio.to_thread(_process_frame, frame)
            n += 1
            S["frames"] += 1
            await ws.send_bytes(out_bytes)
    except Exception as e:
        import traceback; print(f"[ws] closed after {n} frames: {type(e).__name__}: {e}", flush=True); traceback.print_exc()
