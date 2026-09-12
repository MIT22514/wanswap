# Roadmap

Roughly in order of impact.

## 1. Demo capture — highest impact by far
A 15-30 second screen recording: the raw camera, then the swap appearing live, then the pod being
deleted (`$0/hr` and gone). People star and try what they can *see*; nothing else in this list
comes close. A repo with no demo of a visual product asks the reader to take it on faith.

## 2. Any host, not just RunPod
The core (`src/`, `deploy.sh`) already works on any SSH-able machine with an NVIDIA GPU. Make that
a first-class path rather than a footnote: a documented `--host ssh` mode and a thin provider
abstraction, so RunPod is one implementation instead of an assumption. This removes the payment
wall for everyone who already owns a graphics card — the largest audience we currently turn away.

## 3. CPU smoke test — zero GPU, zero spend
Run `swap_service.py` on CPU against a video file. At 1-2fps it's useless for a call and perfect
for proving the whole chain works: frames in, swapped frames out, OBS shows them. It lets a
stranger validate the project in five minutes without an account or a credit card, which is
exactly where most of them currently leave.

## 4. Screenshots
Two images: the OBS media source configured, and a live call window. Cheap credibility for anyone
skimming.

## 5. Better face quality
hyperswap rebuilds the face at 256px, which is the visible quality ceiling. Either a 512-class
swap model or a face-enhancer pass (GFPGAN / GPEN, ~30-60ms per frame) would sharpen it
noticeably. Should be a flag, not a default: it trades frame rate for fidelity.

## 6. Use cases
A short section on what this is for beyond the obvious — streaming avatars, privacy in calls,
latency research. It helps people imagine a use that isn't a prank, which widens the audience
and lowers the reputational cost of the project.

## Not planned

- **Bundled face presets or model weights.** Never. See `THIRD-PARTY.md` for why — two of our
  dependencies are non-commercial, and shipping other people's likenesses is how repos get removed.
- **Voice conversion.** It works and we ran it, but it needs a cloned voice of a real person to be
  interesting, which is a different risk class. Deliberately out of scope here.
- **Windows / Linux client.** macOS-only today, untested elsewhere. Contributions welcome.
