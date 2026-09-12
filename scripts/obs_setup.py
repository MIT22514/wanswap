#!/usr/bin/env python3
"""obs_setup.py - configure OBS from the command line over obs-websocket.

Creates a Media Source pointing at the swap stream, sets the canvas to match,
and starts the virtual camera. Removes three GUI steps from the setup.

  python3 scripts/obs_setup.py --password <obs-websocket-password>
  python3 scripts/obs_setup.py --password x --url http://127.0.0.1:8081/stream --width 960 --height 540
"""
import argparse, json, sys, time

try:
    import websocket  # websocket-client
except ImportError:
    sys.exit("websocket-client missing: pip install -r requirements.txt")

def rpc(ws, req_id, req_type, data=None):
    msg = {"op": 6, "d": {"requestType": req_type, "requestId": str(req_id), "requestData": data or {}}}
    ws.send(json.dumps(msg))
    while True:
        raw = json.loads(ws.recv())
        if raw.get("op") == 7 and raw["d"].get("requestId") == str(req_id):
            return raw["d"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="4455")
    ap.add_argument("--password", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8081/stream")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=540)
    a = ap.parse_args()

    ws = websocket.create_connection(f"ws://{a.host}:{a.port}", timeout=10, suppress_origin=True)
    hello = json.loads(ws.recv())
    ident = {"op": 1, "d": {"rpcVersion": 1, "authentication": None}}
    if hello["d"].get("authentication"):
        import base64, hashlib
        salt, challenge = hello["d"]["authentication"]["salt"], hello["d"]["authentication"]["challenge"]
        secret = base64.b64encode(hashlib.sha256((a.password + salt).encode()).digest()).decode()
        ident["d"]["authentication"] = base64.b64encode(
            hashlib.sha256((secret + challenge).encode()).digest()).decode()
    ws.send(json.dumps(ident))
    if json.loads(ws.recv())["d"].get("negotiatedRpcVersion") is None:
        sys.exit("obs-websocket auth failed - check the password (OBS > Tools > WebSocket Server Settings)")

    rpc(ws, 1, "SetVideoSettings", {"baseWidth": a.width, "baseHeight": a.height,
                                    "outputWidth": a.width, "outputHeight": a.height})
    rpc(ws, 2, "CreateInput", {"sceneName": rpc(ws, 21, "GetCurrentProgramScene")["responseData"]["currentProgramSceneName"],
                               "inputName": "wanswap", "inputKind": "ffmpeg_source",
                               "inputSettings": {"input": a.url, "is_local_file": False,
                                                 "close_when_inactive": False}, "sceneItemEnabled": True})
    rpc(ws, 3, "StartVirtualCam")
    print(f"  canvas {a.width}x{a.height} | source '{a.url}' | virtual camera STARTED")
    print("  now pick 'OBS Virtual Camera' as the camera in your call app")
    ws.close()

if __name__ == "__main__":
    main()
