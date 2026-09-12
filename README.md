# wanswap

[![ci](https://github.com/MIT22514/wanswap/actions/workflows/ci.yml/badge.svg)](https://github.com/MIT22514/wanswap/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CodeQL](https://github.com/MIT22514/wanswap/actions/workflows/codeql.yml/badge.svg)](https://github.com/MIT22514/wanswap/actions/workflows/codeql.yml)

**Run real-time models on a rented GPU and pipe the result into any app that takes a webcam.**

Your laptop has a camera and no GPU. This runs the heavy model on a machine you rent by the
minute, ships frames over a WebSocket, and feeds the result into OBS — which presents it to
Zoom, Meet, Teams, or anything else as an ordinary webcam.

Measured end to end: **~15 fps at ~139-200ms round trip**, from an Apple M4 with no NVIDIA
hardware, at about **$0.50/hour**.

> Demo video: *coming shortly.*

---

## Repo quality

CI runs the unit tests and syntax checks, CodeQL does static analysis, Dependabot keeps
dependencies current, and OpenSSF Scorecard runs weekly via its CLI (the official GitHub
Action is a Docker image on `gcr.io`, which currently refuses pulls — see
`docs/GOTCHAS.md`). Branch protection requires the `ci` check.

## Why this exists

Every comparable project assumes you own a graphics card:

- **DeepFaceLive** — excellent, and needs a local NVIDIA GPU
- **FaceFusion's** live mode — insists on a local camera device, so it can't run on a server

The interesting engineering is what happens when inference is 2,000km away from the camera.
This project is mostly the answer to that: transport, latency budget, and hosts that run out
of capacity.

## The numbers

| stage | fps | round trip |
|---|---|---|
| laptop doing the swap itself | 2.7 | — |
| rented GPU, inference alone | 233 fps ceiling | — |
| HTTP per frame over the provider's proxy | ~12 | 250-400ms |
| **WebSocket, on a host 52ms away** | **15** | **139-200ms** |

Where the gains came from, in order of impact:

1. **Protocol overhead.** HTTP-per-frame cost 180-250ms *before any pixels moved*. A persistent
   WebSocket costs 110ms — the single biggest win.
2. **Host choice.** 52ms (Czechia) vs 96-128ms (Amsterdam) vs a 42ms floor. Renting closer beat
   every code change we made.
3. **Payload size.** Once overhead was gone, ~0.85ms/KB dominated: a 1080p frame costs 335ms
   just to ship, 640x360 costs 203ms.

Full data, including what failed and why: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## How it works

```
LOCAL                                    REMOTE (rented GPU, by the minute)
webcam -> client.py                      swap_service.py
            |  JPEG over WebSocket  -->    MediaPipe  -> find the face
            |  (4 parallel sockets)  <--    hyperswap  -> rebuild it
            v                               EMA        -> stop the jitter
     MJPEG :8081 -> OBS -> OBS Virtual Camera -> any call app
```

Details and the reasoning behind each choice: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

```bash
git clone <this repo> && cd wanswap
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# 1. check what's missing
./scripts/doctor.sh

# 2. runpodctl (https://github.com/runpod/runpodctl) + authenticate once
runpodctl config --apiKey <YOUR_KEY>

# 3. put a face photo in tools/faces/ (one clear, front-facing, well-lit head shot)
cp /path/to/your-photo.jpg tools/faces/source.jpg

# 4. provision: finds capacity anywhere, creates the pod, installs everything, sets the face
./scripts/newpod.sh

# 5. run the client (it prints this command for you)
SWAP_URL="https://<pod-id>-8000.proxy.runpod.net" ./venv/bin/python src/client.py --ws \
  --source tools/faces/source.jpg
```

Then in **OBS**: Media Source → `http://127.0.0.1:8081/stream` → **Start Virtual Camera**
(or let `./scripts/obs_setup.py` do all three steps for you), and pick **OBS Virtual Camera**
as your camera in the call app.

**Managing faces:**
```bash
python3 tools/faces.py list                    # what you have
python3 tools/faces.py set <name>              # switch live, mid-call, no restart
python3 tools/faces.py find "<person>" --set   # search Wikimedia/Wikipedia, test, install the best
python3 tools/faces.py add <name> <file|url>   # register your own
```

**Stopping:** `runpodctl pod delete <pod-id>` — there is no volume, so stopping is pointless.
Nothing is billed once the pod is gone.

## Design decisions

- **No persistent volume.** ~$4.30/month for a volume vs ~$0.04 of GPU time to rebuild. It also
  pins you to one datacentre's GPU pool — the one that runs dry.
- **Capacity first.** `newpod.sh` probes datacentres x GPU types and takes whichever answers.
- **Deployment that cannot drift.** `deploy.sh --check` compares hashes against the local tree,
  and `start.sh` syncs *before* bootstrapping, so a pod can never silently run old code.
- **EMA smoothing, not a tracker.** Trackers need ordered frames; parallel senders deliberately
  reorder them. An order-independent moving average fixes the jitter instead.

## Limits

- **~15fps at ~200ms is not state of the art.** A local RTX 3060+ will do ~30fps at <100ms. This
  project's point is doing it *without* local NVIDIA hardware.
- **The 256px face crop is the quality ceiling.** A face-enhancer pass (GFPGAN/GPEN) would
  sharpen it for ~30-60ms/frame — the obvious next improvement.
- **RunPod only.** The core (`src/`, `deploy.sh`) works on any SSH-able GPU box, but the
  provisioning script is written for RunPod.
- **macOS client.** Written and tested on macOS; the Linux/Windows paths are untested.

## Ethics and legality — read before using

This code makes convincing fake faces of **real people**, in real time.

- **Consent matters.** A synthetic face on a call is deception of the person on the other end.
  Use it only where everyone involved knows.
- **Impersonation for gain is a crime.** Obtaining money, goods or services by impersonation is
  fraud in the UK and comparable offences exist across the EU and US states.
- **Don't publish or distribute** synthetic depictions of real people — defamation, harassment
  and misinformation exposure all start there, and several jurisdictions now require
  AI-generated media to be labelled.
- **Public figures are not fair game.** Political deepfakes are the most damaging use of this
  technology, and the fastest way to get this project removed.

The tooling is generic. What you point it at is your responsibility.

## Credits

Face swap model from **[FaceFusion](https://github.com/facefusion/facefusion)** (hyperswap) ·
detection by **MediaPipe** · embeddings by **InsightFace** · inference by **ONNX Runtime** ·
virtual camera by **[OBS Studio](https://obsproject.com)** · GPU by **[RunPod](https://runpod.io)**.

No model weights are distributed with this repository. See [`THIRD-PARTY.md`](THIRD-PARTY.md) —
some dependencies are explicitly non-commercial.

## Licence

MIT — see [`LICENSE`](LICENSE). The licence covers this repository's code only, not the models
you download alongside it.
