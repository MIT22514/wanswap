# Benchmarks

Every number here was measured on this setup, not estimated. Negative results are included,
because they are the more useful half.

## The journey

| stage | fps | round trip | note |
|---|---|---|---|
| local M4, inswapper_128, CPU | 2.7 | — | 370ms/frame, unusable |
| local M4, CoreML | ~3 | — | no better |
| rented GPU, inference alone | 233 fps ceiling | — | 4.28ms/frame |
| HTTP over provider proxy | ~12 | 250-400ms | the first working setup |
| over an SSH tunnel | 6.5-8 | — | *slower* than the public proxy |
| **WebSocket, same host** | **14-17** | **219-271ms** | wins on both axes, tighter spread |
| **WebSocket + 52ms host** | **15** | **139-200ms** | live webcam, 900+ frames, 0 failures |

## Transport breakdown

```
HTTP tiny request        180-250ms    protocol overhead before any pixels
WebSocket ping            110ms       <- 70-140ms cheaper before you send a frame

WebSocket frame cost      ~0.85ms per KB of payload
  tiny 160x90    (  2KB up /   5KB down) -> 132ms
  small 640x360  ( 25KB up /  43KB down) -> 203ms
  full 1080p     ( 95KB up / 174KB down) -> 335ms
```

Payload cost, measured by holding everything else constant and varying frame size.

## Host choice

TCP round trip from the camera, same client, same day:

```
Cloudflare (the floor)   42.2ms
Czechia                  51.6ms
Romania                  82ms
Amsterdam                96-128ms
```

Choosing a closer datacentre beat every code change we made that day. It is the cheapest
optimisation available and it is invisible if you only benchmark against one host.

## Latency budget

You cannot get low latency by making one thing fast; you have to know where every millisecond
goes.

```
video: capture + encode ... 20-40ms
       network (ws + payload) ... 150-250ms
       decode + OBS + call app ... 30-60ms
       ------------------------------------
       ~200-350ms end to end
```

Human perception tolerates audio *ahead* of video far better than audio *behind* it — so if you
add a voice pipeline, keep its latency below the video's rather than chasing the minimum.

## What failed, and why

| approach | result | cause |
|---|---|---|
| HTTP/2 | 100% failure | the provider's proxy mangles h2 POST bodies |
| SSH tunnel instead of the public proxy | 6.5-8fps vs 12 | tunnelling overhead exceeded the proxy's |
| udp2raw + SRT | abandoned | needs UDP, a spare port, and root on both ends |
| Vast.ai instead of RunPod | 3 hosts failed | OCI runtime errors on all three |
| FaceFusion's built-in live mode | unusable | insists on a local camera device; containers can't provide one |
| running inference on the laptop | 2.7fps | no GPU worth the name |

## Methodology notes

- Frame rate is measured **delivered** frames (client-side), not sent — dropped frames don't count.
- Round trip is exponentially smoothed client-side; the tightness of the band matters as much
  as the mean, because variance is what users feel as lag.
- Each configuration was run for 50-60s after warm-up; models load lazily on first frame.
