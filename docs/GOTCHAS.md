# Gotchas

Every one of these cost real time to find. Most produce a symptom that points somewhere other
than the actual cause.

| symptom | actual cause | fix |
|---|---|---|
| WebSocket upgrade returns HTTP 404 | uvicorn has no WebSocket implementation installed | `pip install websockets` — it is not a dependency of uvicorn |
| `wss://` fails certificate verification | macOS system Python ships no CA bundle; `websocket-client` doesn't fall back to certifi the way `requests` does | pass `sslopt={"ca_certs": certifi.where()}` |
| a background SSH tunnel silently vanishes | macOS has no `setsid` (Linux-only) | use plain `nohup ... &` |
| pod will not start | the host has no free GPUs — this is routine, not exceptional | probe other datacentres |
| updating pod ports or volume wiped the deployment | `pod update` restarts the container | do it *before* deploying, and attach a volume first |
| the service will not restart | `pkill -f uvicorn` also matches your own SSH command line | use a pod-side restart script with a bracketed pattern |
| camera returns nothing | macOS camera permission was never granted — and it is only ever prompted when *you* launch the app, not when a background process does | launch the app once from Finder and click Allow |
| ONNX Runtime silently runs on CPU | CUDA libraries live in the pip package, not on the default loader path | export `LD_LIBRARY_PATH` before starting the service |
| frames arrive out of order | multiple parallel senders by design | keep the server stateless per frame; don't use order-dependent tracking |
| changed one model setting and everything broke | model settings are not free parameters — e.g. a feature extractor must match what the model was trained with | change one thing, test, change back |

## The meta-lesson

Most of these look like "the code is wrong". Almost none of them were. They were environment,
permissions, ordering, or a mismatch between two components that each worked correctly in
isolation. When something suddenly stops working, check what changed *around* the code first.
