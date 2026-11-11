#!/usr/bin/env python3
"""Token Hotel video maker.

Reads today's transcript, makes a vertical 1080x1920 video:
  - comic image per character (generated once with Gemini, cached in assets/)
  - voice per line (Gemini TTS, one voice per character)
  - big captions, title card, and an "AI agents wrote every line" end card
Everything has a fallback, so the video is always produced:
  no GOOGLE_API_KEY or image model unavailable -> drawn color cards
  voice unavailable -> silent scenes with reading-time length

Env: GOOGLE_API_KEY, MOCK=1 (no network), DAY=YYYY-MM-DD, TTS_MODEL, IMAGE_MODEL
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
W, H = 1080, 1920
MOCK = os.environ.get("MOCK") == "1"
KEY = os.environ.get("GOOGLE_API_KEY", "")
DAY = os.environ.get("DAY") or date.today().isoformat()
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image")
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

VOICES = {"Pierce": "Puck", "Vex": "Charon", "Madame Halloran": "Kore", "Narrator": "Orus"}
COLORS = {"Pierce": (150, 40, 40), "Vex": (30, 70, 55), "Madame Halloran": (80, 45, 110),
          "Narrator": (50, 35, 25), "Hotel": (50, 35, 25)}
LOOK = {
    "Pierce": "a thin nervous porter, round pale face, small brown mustache, red uniform with gold buttons, red pillbox cap",
    "Vex": "a tall bored bartender, slicked-back black hair, black vest, green bow tie",
    "Madame Halloran": "a stern older woman hotel manager, silver bun, cat-eye glasses on a chain, purple blazer",
    "Hotel": "a grand old hotel lobby, dark wood, brass lamps, a glowing blurry door numbered 404, nobody in it",
}
STYLE = "flat 2D comic style, bold black outlines, warm retro colors, vertical 9:16, no text, no letters"

FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_S = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"


def post(model, payload):
    req = urllib.request.Request(
        API.format(model), data=json.dumps(payload).encode(), method="POST",
        headers={"x-goog-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def gen_image(name):
    """Return path of cached character image, generating it once. None on failure."""
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    path = assets / f"{name.replace(' ', '_')}.png"
    if path.exists():
        return path
    if MOCK or not KEY:
        return None
    prompt = f"{STYLE}. Scene: {LOOK[name]}."
    if name != "Hotel":
        prompt = f"{STYLE}. Portrait of {LOOK[name]}, in front of a dark wood hotel lobby with brass lamps."
    try:
        data = post(IMAGE_MODEL, {"contents": [{"parts": [{"text": prompt}]}]})
        for part in data["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline:
                path.write_bytes(base64.b64decode(inline["data"]))
                return path
    except Exception as e:  # billing missing, quota, model name... fall back
        print(f"Image for {name} failed ({e}); using drawn card.", file=sys.stderr)
    return None


def gen_voice(text, speaker, out_wav):
    """Write a wav for the line. Returns duration seconds, or None on failure."""
    if MOCK or not KEY:
        return None
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICES[speaker]}}},
        },
    }
    for attempt in range(3):
        try:
            data = post(TTS_MODEL, payload)
            part = data["candidates"][0]["content"]["parts"][0]
            pcm = base64.b64decode((part.get("inlineData") or part["inline_data"])["data"])
            with wave.open(str(out_wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            return len(pcm) / 2 / 24000
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(20)  # free tier rate limit
                continue
            print(f"Voice failed ({e.code}) for {speaker}.", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Voice failed ({e}) for {speaker}.", file=sys.stderr)
            return None
    return None


def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def background(name):
    img_path = gen_image(name if name in LOOK else "Hotel")
    if img_path:
        im = Image.open(img_path).convert("RGB")
        scale = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * scale), int(im.height * scale)))
        l, t = (im.width - W) // 2, (im.height - H) // 2
        return im.crop((l, t, l + W, t + H))
    base = COLORS.get(name, COLORS["Hotel"])
    im = Image.new("RGB", (W, H), base)
    d = ImageDraw.Draw(im)
    for y in range(H):  # simple vertical gradient
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(c * (1 - 0.5 * k)) for c in base))
    if name in LOOK and name != "Hotel":
        d.ellipse((W // 2 - 260, 420, W // 2 + 260, 940), fill=(240, 225, 200), outline=(0, 0, 0), width=10)
        f = ImageFont.truetype(FONT_B, 300)
        d.text((W // 2, 680), name[0], font=f, fill=(0, 0, 0), anchor="mm")
    return im


def card(name, role, text, out_png, header="THE TOKEN HOTEL"):
    im = background(name).convert("RGB")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle((0, 1080, W, 1800), fill=(0, 0, 0, 175))
    od.rectangle((0, 0, W, 150), fill=(0, 0, 0, 150))
    im = Image.alpha_composite(im.convert("RGBA"), ov)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 75), header, font=ImageFont.truetype(FONT_S, 54), fill=(230, 190, 110), anchor="mm")
    d.text((60, 1120), f"{name}" + (f"  ·  {role}" if role else ""),
           font=ImageFont.truetype(FONT_B, 48), fill=(230, 190, 110))
    size = 76 if len(text) < 90 else 64
    font = ImageFont.truetype(FONT_B, size)
    y = 1210
    for ln in wrap(d, text, font, W - 120):
        d.text((60, y), ln, font=font, fill=(255, 255, 255))
        y += int(size * 1.25)
    d.text((W // 2, 1860), "AI-generated characters and voices", font=ImageFont.truetype(FONT_B, 34),
           fill=(200, 200, 200), anchor="mm")
    im.convert("RGB").save(out_png)


def make_scene(png, wav, seconds, out_mp4):
    tmp = out_mp4.with_name("tmp_" + out_mp4.name)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(png)]
    if wav and Path(wav).exists():
        cmd += ["-i", str(wav), "-af", "apad", "-t", f"{seconds:.2f}"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.2f}"]
    cmd += ["-vf", "format=yuv420p,loop=-1:1,trim=duration=%.2f" % seconds,
            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "24000", "-ac", "1", "-shortest", str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.rename(out_mp4)


def main():
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))
    work = ROOT / "build" / DAY
    work.mkdir(parents=True, exist_ok=True)
    scenes = []

    def add(idx, name, role, text, speaker_for_voice, header="THE TOKEN HOTEL", min_len=2.0, pad=0.5):
        png, wav, mp4 = work / f"{idx:02d}.png", work / f"{idx:02d}.wav", work / f"{idx:02d}.mp4"
        card(name, role, text, png, header)
        dur = gen_voice(text, speaker_for_voice, wav) if speaker_for_voice else None
        if dur is None:  # silent: reading time
            dur = max(min_len, len(text.split()) * 0.4)
        make_scene(png, wav if dur and wav.exists() else None, dur + pad, mp4)
        scenes.append(mp4)

    add(0, "Hotel", "", "Tonight at the Token Hotel: " + ep["situation"], "Narrator", min_len=3)
    for i, l in enumerate(ep["lines"], start=1):
        add(i, l["speaker"], l["role"], l["line"], l["speaker"])
    add(len(ep["lines"]) + 1, "Hotel", "", "Every line was written by an AI agent. New episode every day.", "Narrator", min_len=3)

    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    out_dir = ROOT / "videos"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{DAY}.mp4"
    tmp = out_dir / f"tmp_{DAY}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(tmp)], check=True)
    tmp.rename(out)
    print(f"Video saved: {out}")


if __name__ == "__main__":
    main()
