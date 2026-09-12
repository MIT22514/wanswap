---
name: wanswap
description: Provision, run and debug a real-time remote-GPU face swap pipeline. Use when the user asks to start or stop a live face swap, switch which face is being used, check GPU pod status or cost, or troubleshoot the video pipeline (OBS virtual camera, WebSocket transport, pod capacity).
---

# wanswap

Real-time face swap where the model runs on a rented GPU and the result is piped into any app
that accepts a webcam.

## When to use this skill

- "start the face swap" / "stop the face swap" / "is the pod still billing"
- "switch to <name>'s face"
- "the video is glitchy / frozen / laggy"
- "add this photo as a face"

## Check state first

```bash
runpodctl pod list                    # only lists RUNNING pods
runpodctl user                        # balance + current spend rate
lsof -nP -iTCP:8081 -sTCP:LISTEN      # is the local client serving? no output = it died
curl -s http://127.0.0.1:8081/health  # (service health lives on the pod side)
```

## Start

```bash
./scripts/doctor.sh                  # report anything missing before wasting time
./scripts/newpod.sh                  # find capacity, create pod, deploy, build, set face (~3-5 min)
```

`newpod.sh` prints the exact client command when it finishes. Then start OBS's virtual camera:

```bash
python3 scripts/obs_setup.py --password <obs-websocket-password>
```

## Switch faces

```bash
python3 tools/faces.py list
python3 tools/faces.py set <name>                 # live, mid-call, no restart
python3 tools/faces.py find "<person>" --set      # source from Wikimedia/Wikipedia, test, install
python3 tools/faces.py add <name> <file-or-url>
```

## Stop (and stop billing)

```bash
pkill -f client.py
runpodctl pod delete <pod-id>        # no volume, so delete rather than stop
runpodctl pod list                   # confirm nothing is running
```

## Diagnosing "it looks broken"

Work outward from the camera:

1. **No output at all / frozen** — is the client alive? `lsof -nP -iTCP:8081 -sTCP:LISTEN`
2. **Client dead** — it lost the camera (a call app grabbed it) or the pod went away. Restart it.
   The call app must use **OBS Virtual Camera**, never the physical camera.
3. **Jittery, not frozen** — check the delivered fps in the client's own output; below ~8fps
   looks choppy. Consider raising `--buffer` to smooth playback.
4. **Pod-side failures** — `deploy.sh --check` for version drift; the service log on the pod
   (`/workspace/service.log`) for exceptions.

## Cost discipline

Pods bill by the second while running. Verify with `runpodctl pod list` before and after any
session, and always delete rather than stop — there is no volume to preserve.
