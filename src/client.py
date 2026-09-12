#!/usr/bin/env python3
"""Live face-swap client  (webcam -> pod GPU -> local MJPEG stream for OBS).

Usage:
    ./start.sh                 # webcam, default settings
    ./start.sh --video x.mp4   # drive from a file (testing)
    ./start.sh --camera 1      # pick another camera

The client brings the remote service up itself: one SSH session forwards :8000 and runs
bootstrap.sh serve in the foreground, so the service lives exactly as long as this runs.
Output stream: http://127.0.0.1:8081/stream   (OBS: Media Source, or Browser Source)
"""
import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import httpx
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
POD_IP = os.environ.get("POD_IP", "157.157.221.29")
POD_PORT = os.environ.get("POD_PORT", "32001")
_identity_default = "~/.runpod/ssh/runpodctl-ssh-key"
SSH_IDENTITY = os.path.expanduser(_identity_default)

SERVICE = os.environ.get("SWAP_URL", "https://$POD_ID-8000.proxy.runpod.net")


def _load_auth():
    try:
        return open(os.path.join(HERE, ".auth")).read().strip()
    except Exception:
        return ""


AUTH = _load_auth()
LATEST = {"jpg": None, "seq": 0}
PACE = {"queue": [], "target_fps": 12.0}   # steady playback cadence, smooths bursty arrivals
SEND_STATE = {"last": 0.0}
STATS = {"sent": 0, "recv": 0, "fps": 0.0, "lat": 0.0, "fail": 0, "recv_at_report": 0}
WANT = {"frame": None, "seq": 0}          # newest captured frame, waiting to be sent
CLAIMED = {"seq": -1}                     # last seq handed to a sender
LOCK = threading.Lock()
PACE_LOCK = threading.Lock()


class MJPEG(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path.rstrip("/") not in ("/stream", ""):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        t_write = time.time()
        last_seq = -1
        while True:
            if PACE["target_fps"] <= 0:
                # pacing disabled: always send the newest frame (lowest latency, no drops)
                if LATEST["seq"] == last_seq:
                    time.sleep(0.002)
                    continue
                last_seq = LATEST["seq"]
                jpg = LATEST["jpg"]
                if not jpg:
                    continue
            else:
                with PACE_LOCK:
                    jpg = PACE["queue"].pop(0) if PACE["queue"] else None
                if jpg is None:
                    time.sleep(0.004)
                    continue
            try:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                self.wfile.flush()
                # only pace when explicitly enabled (--pace-fps); otherwise send ASAP
                if PACE["target_fps"] > 0:
                    dt = 1.0 / PACE["target_fps"] - (time.time() - t_write)
                    if dt > 0:
                        time.sleep(dt)
                    t_write = time.time()
            except Exception:
                break

    def log_message(self, *a):
        pass


def sender(stop_evt):
    """One sender worker: always sends the NEWEST frame, drops the ones it missed."""
    # NOTE: HTTP/2 was tried here and the RunPod proxy mangles h2 POST bodies (100% failures).
    # Plain HTTP/1.1 with keep-alive is the reliable path.
    s = requests.Session()
    s.headers.update({"X-Auth": AUTH})
    while not stop_evt.is_set():
        with LOCK:
            seq, buf = WANT["seq"], WANT["frame"]
            # claim it: one sender per captured frame (otherwise idle senders resend it)
            if buf is None or seq == CLAIMED["seq"]:
                fresh = False
            else:
                CLAIMED["seq"] = seq
                fresh = True
        if not fresh:
            time.sleep(0.002)
            continue
        t0 = time.time()
        try:
            r = s.post(f"{SERVICE}/swap",
                       files={"file": ("f.jpg", buf, "image/jpeg")}, timeout=15)
            STATS["sent"] += 1
            if r.ok:
                LATEST["jpg"] = r.content
                LATEST["seq"] += 1
                with PACE_LOCK:
                    PACE["queue"].append(r.content)
                    # bound the buffer: drop stale frames rather than accumulate lag
                    while len(PACE["queue"]) > PACE.get("buffer", 2):
                        PACE["queue"].pop(0)
                STATS["recv"] += 1
                STATS["lat"] = STATS["lat"] * 0.8 + (time.time() - t0) * 0.2
            else:
                STATS["fail"] += 1
        except Exception as e:
            STATS["fail"] += 1
            if STATS["fail"] <= 3:
                print(f"[client] send error #{STATS['fail']}: {type(e).__name__}: {str(e)[:110]}", flush=True)
            s.close()
            s = requests.Session()
            s.headers.update({"X-Auth": AUTH})
            time.sleep(0.05)


def sender_ws(stop_evt):
    """Same contract as sender(), but over a persistent WebSocket instead of one request per frame.

    Measured on this setup: WS round trip = ~110ms base + ~0.85ms/KB, versus ~390-500ms for the
    HTTP path. One WS connection still processes frames sequentially, so we keep running several
    of these in parallel - the concurrency is what buys frame rate.
    """
    import websocket  # websocket-client: synchronous, thread friendly
    # macOS python often has no CA bundle of its own; websocket-client does not default to
    # certifi the way requests does, so wss:// fails cert verification without this.
    try:
        import certifi
        sslopt = {"ca_certs": certifi.where()}
    except Exception:
        sslopt = {}
    ws_url = SERVICE.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/ws"
    ws = None
    while not stop_evt.is_set():
        if ws is None:
            try:
                ws = websocket.create_connection(ws_url, header=[f"X-Auth: {AUTH}"], timeout=15, sslopt=sslopt)
            except Exception as e:
                STATS["fail"] += 1
                if STATS["fail"] <= 3:
                    print(f"[client] ws connect error: {type(e).__name__}: {str(e)[:110]}", flush=True)
                time.sleep(0.4)
                continue
        with LOCK:
            seq, buf = WANT["seq"], WANT["frame"]
            if buf is None or seq == CLAIMED["seq"]:
                fresh = False
            else:
                CLAIMED["seq"] = seq
                fresh = True
        if not fresh:
            time.sleep(0.002)
            continue
        t0 = time.time()
        try:
            ws.send_binary(buf)
            data = ws.recv()
            if isinstance(data, str):
                data = data.encode()
            STATS["sent"] += 1
            if data[:2] == b"\xff\xd8":          # a JPEG came back
                LATEST["jpg"] = data
                LATEST["seq"] += 1
                with PACE_LOCK:
                    PACE["queue"].append(data)
                    while len(PACE["queue"]) > PACE.get("buffer", 2):
                        PACE["queue"].pop(0)
                STATS["recv"] += 1
                STATS["lat"] = STATS["lat"] * 0.8 + (time.time() - t0) * 0.2
            else:
                STATS["fail"] += 1
        except Exception as e:
            STATS["fail"] += 1
            if STATS["fail"] <= 3:
                print(f"[client] ws error: {type(e).__name__}: {str(e)[:110]}", flush=True)
            try:
                ws.close()
            except Exception:
                pass
            ws = None
            time.sleep(0.2)


REMOTE_LOG = os.path.join(HERE, "remote-service.log")


def start_remote_service():
    """stdout/stderr go to a FILE, never a pipe: a full pipe buffer blocks the SSH
    process and silently stalls the tunnel (that bug cost us an hour)."""
    log = open(REMOTE_LOG, "w")
    cmd = ["ssh", "-i", SSH_IDENTITY,
           "-o", "StrictHostKeyChecking=accept-new", 
           "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
           "-o", "LogLevel=ERROR", "-L", "8000:localhost:8000",
           "-p", POD_PORT, f"root@{POD_IP}", "/workspace/bootstrap.sh serve"]
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)


def wait_for_service(timeout=200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{SERVICE}/health", timeout=3)
            if r.ok:
                return r.json()
        except Exception:
            pass
        time.sleep(2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--video", default=None)
    ap.add_argument("--source", default=os.path.join(HERE, "my_face.jpg"))
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=540)
    ap.add_argument("--jpeg", type=int, default=75)
    ap.add_argument("--senders", type=int, default=4)
    ap.add_argument("--capture-fps", type=float, default=30.0,
                    help="cap the capture loop so we do not starve the SSH tunnel")
    ap.add_argument("--send-fps", type=float, default=0.0,
                    help="cap how often a new frame is offered to the senders")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--pace-fps", type=float, default=0.0, help="steady output cadence")
    ap.add_argument("--buffer", type=int, default=2, help="frames held to smooth jitter (adds lag)")
    ap.add_argument("--no-ssh", action="store_true", default=True)
    ap.add_argument("--ws", action="store_true",
                    help="use the WebSocket transport (persistent connection) instead of HTTP")
    args = ap.parse_args()

    proc = None
    if not args.no_ssh:
        print("[client] starting remote service (SSH)...", flush=True)
        proc = start_remote_service()
    print("[client] waiting for swap service...", flush=True)
    st = wait_for_service()
    if st is None:
        print("[client] ERROR: service didn't come up (check pod / SSH key)", flush=True)
        sys.exit(1)
    print(f"[client] service ready {st}", flush=True)

    with open(args.source, "rb") as fh:
        r = requests.post(f"{SERVICE}/source", files={"file": fh},
                          headers={"X-Auth": AUTH}, timeout=30)
    print(f"[client] source face: {r.status_code} {r.text.strip()[:80]}", flush=True)
    if not r.ok:
        sys.exit(1)

    PACE["target_fps"] = args.pace_fps
    PACE["buffer"] = max(1, args.buffer)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), MJPEG)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[client] >>> OBS URL: http://127.0.0.1:{args.port}/stream", flush=True)

    stop_evt = threading.Event()
    transport = sender_ws if args.ws else sender
    print(f"[client] transport: {'websocket' if args.ws else 'http'} x{max(1, args.senders)}", flush=True)
    for _ in range(max(1, args.senders)):
        threading.Thread(target=transport, args=(stop_evt,), daemon=True).start()

    cap = cv2.VideoCapture(args.video if args.video else args.camera)
    if not args.video:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
    if not cap.isOpened():
        print("[client] ERROR: cannot open camera. Grant Camera permission to your terminal app "
              "(System Settings > Privacy & Security > Camera), then re-run.", flush=True)
        sys.exit(1)

    enc = [int(cv2.IMWRITE_JPEG_QUALITY), args.jpeg]
    t0, last_report = time.time(), time.time()
    print("[client] running - Ctrl-C to stop", flush=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if args.video:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.03)
                continue
            if frame.shape[1] != args.width or frame.shape[0] != args.height:
                frame = cv2.resize(frame, (args.width, args.height))
            now = time.time()
            if args.send_fps <= 0 or now - SEND_STATE["last"] >= 1.0 / args.send_fps:
                ok, buf = cv2.imencode(".jpg", frame, enc)
                if ok:
                    with LOCK:
                        WANT["frame"] = buf.tobytes()
                        WANT["seq"] += 1
                    SEND_STATE["last"] = now

            # keep the capture loop from eating every core (this starved the tunnel before)
            if args.capture_fps > 0:
                slack = 1.0 / args.capture_fps - (time.time() - now)
                if slack > 0:
                    time.sleep(slack)
            if time.time() - last_report > 5:
                now = time.time()
                delivered = STATS["recv"] - STATS["recv_at_report"]
                STATS["recv_at_report"] = STATS["recv"]
                print(f"[client] {delivered / (now - last_report):.1f} fps delivered | "
                      f"round-trip {STATS['lat']*1000:.0f} ms | sent {STATS['sent']} "
                      f"recv {STATS['recv']} fail {STATS['fail']}", flush=True)
                last_report = now
    except KeyboardInterrupt:
        print("\n[client] stopping", flush=True)
    finally:
        stop_evt.set()
        cap.release()
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
