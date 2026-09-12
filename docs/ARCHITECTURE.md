# Architecture

## The problem

Real-time face swapping needs a GPU. The machine with the camera usually doesn't have one.
Every comparable project (DeepFaceLive, FaceFusion's live mode) assumes you did buy one.

`wanswap` assumes you didn't. It rents one by the minute and ships frames over a WAN link.

## Two halves

```
LOCAL                                          REMOTE (rented GPU)
webcam -> client.py                            swap_service.py
            |  JPEG frames over WebSocket  -->   MediaPipe -> locate
            |  (4 parallel connections)    <--   hyperswap -> rebuild
            v                                    EMA -> stabilise
     MJPEG :8081 -> OBS -> OBS Virtual Camera
                          -> Zoom / Meet / anything that takes a webcam
```

`client.py` owns the camera, sends the newest frame it has, and serves the returned frames as
an MJPEG stream. OBS consumes that stream and exposes it as a webcam. The call app never knows.

## Why this shape

**Remote inference, not local.** A laptop GPU (Apple M4, in our case) manages ~2.7fps on
inswapper_128. The same model on a rented GPU does 4.28ms/frame — a 233fps ceiling. Inference
stops being the bottleneck; the network becomes it. Everything below follows from that.

**WebSocket, not HTTP per frame.** Sending one HTTP request per frame cost 180-250ms of
protocol overhead *before any pixels moved*. A persistent WebSocket costs 110ms. That single
change was the largest win in the project.

**Four parallel sockets, newest frame wins.** One socket processes frames sequentially, so
concurrency is what buys frame rate. Each worker claims the newest captured frame and drops
anything it missed — stale frames are worse than missing ones.

**EMA smoothing instead of a face tracker.** Per-frame detection wobbles slightly and the swap
inherits the wobble, which reads as "jittery". A tracker fixes it, but MediaPipe's VIDEO-mode
tracker requires ordered frames and our four senders deliberately reorder them. An exponential
moving average is order-independent, with a snap-if-moved-far guard so a new subject doesn't
drag the previous position.

**Latency needs a budget, not a minimum.** See [BENCHMARKS.md](BENCHMARKS.md) for the numbers.

## Deployment model

**No persistent volume.** A 20GB volume costs ~$4.30/month whether you use it or not. A fresh
pod costs ~$0.04 of GPU time to rebuild (3-5 minutes, automated). Break-even is ~100 sessions
a month — almost nobody reaches it. A volume also pins you to one datacentre's GPU pool, which
is precisely the pool that runs dry.

**Capacity is the binding constraint.** GPU hosts are frequently exhausted ("not enough free
GPUs on the host machine"). `newpod.sh` probes datacentres x GPU types and takes the first
that answers, instead of insisting on one host.

**Deployment that cannot drift.** Pods are disposable, so stale code is invisible until it
breaks something. `deploy.sh --check` compares md5 hashes against the local tree, and
`start.sh` syncs *before* running the bootstrap so a pod can never silently boot old code.
