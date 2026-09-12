#!/usr/bin/env python3
"""Face library manager for the swapper pipeline.

Usage:
  python3 faces.py list                    show the library
  python3 faces.py set <name>              set the live source (works mid-call, no restart)
  python3 faces.py add <name> <path|url>   add a photo, test it, record it
  python3 faces.py find "<query>" [--set]  search Wikimedia/Wikipedia for candidates

The library lives in faces/faces.json; images live in faces/.
Switching is instantaneous server-side, so a call keeps running.
"""
import json, os, re, subprocess, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
FACES = os.path.join(HERE, "faces")
LIB = os.path.join(FACES, "faces.json")
AUTH = open(os.path.join(HERE, ".auth")).read().strip() if os.path.exists(os.path.join(HERE, ".auth")) else ""
SERVICE = os.environ.get("SWAP_URL", "https://$POD_ID-8000.proxy.runpod.net").rstrip("/")

# things that look like a face but are not a usable photo source
BAD = ("statue", "figure", "wax", "tussaud", "painting", "olej", "drawing", "mural", "boots",
       "hotel", "museum", "airport", "sculpt", "bust", "stamp", "coin", "trophy", "miniatur",
       "logo", "poster", "card", "shirt", "signature")


def load():
    if os.path.exists(LIB):
        return json.load(open(LIB))
    return {"faces": {}}


def save(lib):
    lib["faces"] = dict(sorted(lib["faces"].items()))
    json.dump(lib, open(LIB, "w"), indent=2, sort_keys=True)
    print(f"  saved library -> {LIB}")


def post_source(path):
    """POST a photo to /source; returns (face_px, det_score) or (None, error)."""
    r = subprocess.run(["curl", "-s", "-m", "40", "-H", f"X-Auth: {AUTH}",
                        "-F", f"file=@{path}", f"{SERVICE}/source"],
                       capture_output=True, text=True).stdout
    try:
        j = json.loads(r)
    except Exception:
        return None, r[:120]
    if not j.get("ok"):
        return None, j.get("error", r[:120])
    return j.get("face_px", 0), j.get("det_score", 0)


def cmd_list(lib):
    if not lib["faces"]:
        print("  library is empty")
        return
    print(f"  {'name':16s} {'file':26s} {'face_px':>8s} {'score':>6s}")
    for name, m in lib["faces"].items():
        print(f"  {name:16s} {m['file']:26s} {m.get('face_px',0):8d} {m.get('det_score',0):6.3f}")


def cmd_set(lib, name):
    m = lib["faces"].get(name)
    if not m:
        print(f"  no such face: {name}  (try: faces.py list)")
        return 1
    path = os.path.join(FACES, os.path.basename(m["file"]))
    if not os.path.exists(path):
        print(f"  file missing: {path}")
        return 1
    px, sc = post_source(path)
    if px is None:
        print(f"  FAILED to set: {sc}")
        return 1
    m["face_px"], m["det_score"] = px, sc
    save(lib)
    print(f"  ✅ source is now '{name}'  (face_px={px} score={sc})  - live, no restart needed")
    return 0


def cmd_add(lib, name, src):
    os.makedirs(FACES, exist_ok=True)
    ext = ".jpg"
    dest = os.path.join(FACES, re.sub(r"[^a-z0-9_]", "", name.lower()) + ext)
    if src.startswith("http"):
        subprocess.run(["curl", "-sL", "-m", "90", "-o", dest, src])
    else:
        subprocess.run(["cp", "-f", src, dest])
    if not os.path.exists(dest) or os.path.getsize(dest) < 3000:
        print("  download/copy failed")
        return 1
    px, sc = post_source(dest)
    if px is None:
        print(f"  photo rejected by the detector: {sc}")
        return 1
    lib["faces"][name] = {"file": os.path.relpath(dest, HERE), "face_px": px, "det_score": sc,
                          "source": src if src.startswith("http") else "local file"}
    save(lib)
    print(f"  ✅ added '{name}' (face_px={px} score={sc}) AND set it live")
    return 0


def commons_candidates(query, limit=12):
    urls = []
    q = urllib.parse.quote_plus(query)
    api = (f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={q}"
           f"&gsrnamespace=6&gsrlimit=20&prop=imageinfo&iiprop=url|size&iiurlwidth=1600&format=json")
    raw = subprocess.run(["curl", "-s", "-m", "30", api], capture_output=True, text=True).stdout
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    for p in ((d.get("query") or {}).get("pages") or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        t = (p.get("title") or "").lower()
        if ii.get("thumburl") and (ii.get("width") or 0) >= 1000 and not any(b in t for b in BAD):
            urls.append(ii["thumburl"])
    # Wikipedia lead images are usually the best head shots
    for wiki in ("en", "pt", "es", "it", "de", "fr"):
        q2 = urllib.parse.quote(query.replace(" ", "%20"))
        api2 = (f"https://{wiki}.wikipedia.org/w/api.php?action=query&titles={q2}"
                f"&prop=pageimages&piprop=original&format=json&redirects=1")
        raw = subprocess.run(["curl", "-s", "-m", "30", api2], capture_output=True, text=True).stdout
        try:
            d = json.loads(raw)
            for p in ((d.get("query") or {}).get("pages") or {}).values():
                s = (p.get("original") or {}).get("source")
                if s and s not in urls:
                    urls.append(s)
        except Exception:
            pass
    return urls[:limit]


def cmd_find(lib, query, do_set):
    cands = commons_candidates(query)
    print(f"  {len(cands)} candidates for {query!r}")
    best, results = None, []
    for n, url in enumerate(cands, start=1):
        tmp = f"/tmp/find_{n}.jpg"
        subprocess.run(["curl", "-sL", "-m", "60", "-o", tmp, url])
        if not os.path.exists(tmp) or os.path.getsize(tmp) < 3000:
            continue
        px, sc = post_source(tmp)
        if px is None:
            continue
        print(f"  [{n}] face_px={px:4d} score={sc:.3f}  {url.split('/')[-1][:52]}")
        results.append((tmp, px, sc, url))

    if results:
        # rank by detection confidence first (best proxy for a clean frontal face --
        # a low score usually means a turned head, blur or occlusion), size as tie-break.
        # Anything >=200px is plenty: insightface aligns to 112x112 anyway.
        ranked = sorted(results, key=lambda r: (r[2], r[1]), reverse=True)
        sized = [r for r in ranked if r[1] >= 200] or ranked
        best = sized[0]
    if not best:
        print("  nothing usable found")
        return 1
    print(f"\n  best: face_px={best[1]} score={best[2]}")
    if do_set:
        name = re.sub(r"[^a-z0-9_]", "", query.lower())
        return cmd_add(lib, name, best[0])
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, args = sys.argv[1], sys.argv[2:]
    lib = load()
    if cmd == "list":
        cmd_list(lib)
    elif cmd == "set":
        return cmd_set(lib, args[0])
    elif cmd == "add":
        return cmd_add(lib, args[0], args[1])
    elif cmd == "find":
        return cmd_find(lib, args[0], "--set" in args)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
