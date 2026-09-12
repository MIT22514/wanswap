#!/usr/bin/env python3
"""Configure OBS over obs-websocket: create the media source, set the canvas, start
the virtual camera, all in one command.

Requires the maintained client library: pip install -r requirements-obs.txt

  python3 scripts/obs_setup.py --password YOUR_OBS_WEBSOCKET_PASSWORD
  python3 scripts/obs_setup.py --password ... --url http://127.0.0.1:8081/stream --width 960 --height 540
"""
import argparse
import sys

try:
    import obsws_python as obs
except ImportError:
    sys.exit("obsws-python is required:  pip install -r requirements-obs.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=4455)
    ap.add_argument("--password", required=True,
                    help="from OBS > Tools > WebSocket Server Settings")
    ap.add_argument("--url", default="http://127.0.0.1:8081/stream")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--height", type=int, default=540)
    a = ap.parse_args()

    client = obs.ReqClient(host=a.host, port=a.port, password=a.password, timeout=10)
    client.set_video_settings(base_width=a.width, base_height=a.height,
                              out_width=a.width, out_height=a.height)
    scene = client.get_current_program_scene().current_program_scene_name
    client.create_input(scene, "wanswap", "ffmpeg_source",
                        {"input": a.url, "is_local_file": False,
                         "close_when_inactive": False}, True)
    client.start_virtual_cam()
    print(f"  canvas {a.width}x{a.height} | source '{a.url}' | virtual camera STARTED")
    print("  now pick 'OBS Virtual Camera' as the camera in your call app")


if __name__ == "__main__":
    main()
