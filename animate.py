#!/usr/bin/env python3
"""Turn tonight's episode drawing into a short moving cartoon clip (test of stage 2).

Reads assets/scenes/<DAY>.png and writes assets/scenes/<DAY>.mp4 with Gemini Omni (image to video).
Env: GOOGLE_API_KEY, DAY=YYYY-MM-DD. Makes ONE paid request at most (it is not repeated on failure).
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY = os.environ.get("GOOGLE_API_KEY", "")
DAY = os.environ.get("DAY", "")
BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-omni-1.2-flash", "gemini-omni-1.1-flash"]

PROMPT = ("Animate this exact picture as a short shot from a cartoon series. Keep the same drawing style, the same "
          "characters, colors, clothes and composition, and keep every character on screen. The characters come to life "
          "in a lively, funny way: surprised reactions, expressive gestures, small steps and head turns, the long paper "
          "list flutters. A slow, gentle camera push in. No new characters, no text, no talking, no dialogue, no music, "
          "only soft hotel room sounds.")


def call(path, body=None, method=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"x-goog-api-key": KEY, "content-type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=900) as r:
        raw = r.read()
    return raw


def find_video(obj):
    """The video item is in steps[] (type model_output) -> content[] (type video): base64 data or a file uri."""
    for step in obj.get("steps", []) or []:
        for item in step.get("content", []) or []:
            if item.get("type") == "video":
                return item
    out = obj.get("output_video") or obj.get("outputVideo")
    return out if isinstance(out, dict) else None


def main():
    src = ROOT / "assets" / "scenes" / f"{DAY}.png"
    out = ROOT / "assets" / "scenes" / f"{DAY}.mp4"
    if out.exists():
        print("The moving clip already exists, nothing to pay for.")
        return
    if not KEY or not src.exists():
        sys.exit(f"Missing key or drawing ({src.name}).")
    body = {
        "input": [{"type": "image", "data": base64.b64encode(src.read_bytes()).decode(), "mime_type": "image/png"},
                  {"type": "text", "text": PROMPT}],
        "response_format": {"type": "video", "aspect_ratio": "9:16", "resolution": "720p"},
        "generation_config": {"video_config": {"task": "image_to_video"}},
    }
    for model in MODELS:
        try:
            print(f"Asking {model} for the moving clip (this can take a few minutes)...")
            data = json.loads(call("/interactions", dict(body, model=model)))
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            print(f"{model} answered {e.code}: {msg}", file=sys.stderr)
            if e.code in (400, 404) and "model" in msg.lower() and model != MODELS[-1]:
                continue  # this model name is not available: try the next one (nothing was charged)
            sys.exit("The video model did not make a clip.")
        item = find_video(data)
        if not item:
            print(json.dumps(data)[:1500], file=sys.stderr)
            sys.exit("No video found in the answer.")
        if item.get("data"):
            out.write_bytes(base64.b64decode(item["data"]))
        else:
            fid = item["uri"].rstrip("/").split("/files/")[-1].split(":")[0]
            out.write_bytes(call(f"/files/{fid}:download?alt=media"))
        print(f"Moving clip saved: {out} ({out.stat().st_size // 1024} KB) with {model}.")
        return
    sys.exit("No video model was available.")


if __name__ == "__main__":
    main()
