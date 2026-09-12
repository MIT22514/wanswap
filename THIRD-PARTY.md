# Third-party components and their licences

`wanswap` ships **no model weights and no third-party binaries**. You download the models
yourself at runtime. This file exists because several of those dependencies have terms that
matter — in particular, one is non-commercial and one has no declared licence at all.

| Component | Role | Licence | Notes |
|---|---|---|---|
| **FaceFusion** | publishes the `hyperswap_1c_256` swap model we download | *custom / not an SPDX licence* | GitHub reports `NOASSERTION`. We do **not** redistribute the model — `bootstrap.sh` fetches it from their release assets at runtime. Read their terms before commercial use. |
| **InsightFace** | face detection + embeddings (`buffalo_l`) | **no licence declared** on the repository | No declared licence means all rights reserved by default. In addition, InsightFace's **model zoo is explicitly licensed for non-commercial research purposes**. This is the most restrictive dependency in the stack. |
| **hyperswap** (model) | the face swap itself | see FaceFusion | research model, distributed via FaceFusion's assets |
| **MediaPipe** | face/landmark detection | Apache-2.0 | permissive |
| **ONNX Runtime** | model execution | MIT | permissive |
| **OpenCV** | image handling | Apache-2.0 | permissive |
| **FastAPI / uvicorn / Starlette** | the pod-side service | MIT / BSD-3 | permissive |
| **websocket-client** | client transport | Apache-2.0 | permissive |
| **OBS Studio** | virtual camera | GPL-2.0 | separate program, not linked |
| **RunPod** | GPU rental | commercial service | your account, your terms |

## What this means if you want to use wanswap commercially

You probably can't, as-is. The swap model comes from FaceFusion (custom terms) and the face
embedding comes from InsightFace (non-commercial research). Swapping in a permissively
licensed detector and embedder would be the work required — the transport and deployment
parts of this project are licence-clean and are the actual novelty.

For personal, non-commercial use, the practical position is: don't redistribute the weights,
and don't build a product on them.
