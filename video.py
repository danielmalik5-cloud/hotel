#!/usr/bin/env python3
"""Token Hotel video maker (animated).

Reads today's transcript and makes a vertical 1080x1920 video:
  - the three hotel characters, drawn in code (always identical, free)
  - the speaker's mouth moves with the voice, everyone blinks
  - voice per line (Gemini TTS, one voice per character)
  - big captions, title card, and an "AI agents wrote every line" end card
Fallbacks: no GOOGLE_API_KEY or voice unavailable -> silent scenes with a
pretend-talking mouth and reading-time length.

Env: GOOGLE_API_KEY, MOCK=1 (no network), DAY=YYYY-MM-DD, TTS_MODEL
"""
import array
import base64
import json
import math
import os
import shutil
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
FPS = 12
MOCK = os.environ.get("MOCK") == "1"
KEY = os.environ.get("GOOGLE_API_KEY", "")
DAY = os.environ.get("DAY") or date.today().isoformat()
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

VOICES = {"Pierce": "Puck", "Vex": "Charon", "Madame Halloran": "Kore", "Narrator": "Orus"}
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_S = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
ST = 'stroke="#000" stroke-width="8" stroke-linejoin="round" stroke-linecap="round"'


# ---------------------------------------------------------------- drawing
def mouth(level, cx, cy, closed_svg):
    if level == 0:
        return closed_svg
    ry = 14 if level == 1 else 30
    rx = 28 if level == 1 else 36
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="#5a1a1a"/>'


def pierce(m, blink):
    eyes = ('<path d="M440 795 L500 795 M580 795 L640 795" fill="none"/>' if blink else
            '<ellipse cx="470" cy="790" rx="26" ry="38" fill="#fff"/><ellipse cx="610" cy="790" rx="26" ry="38" fill="#fff"/>'
            '<circle cx="476" cy="800" r="12" fill="#000"/><circle cx="604" cy="800" r="12" fill="#000"/>')
    return f'''<g {ST}>
<path d="M300 1500 L330 1000 Q540 940 750 1000 L780 1500Z" fill="#b3262b"/>
<circle cx="540" cy="1150" r="14" fill="#e6b84c"/><circle cx="540" cy="1230" r="14" fill="#e6b84c"/><circle cx="540" cy="1310" r="14" fill="#e6b84c"/>
<rect x="500" y="900" width="80" height="110" fill="#f1d6b8"/>
<ellipse cx="540" cy="780" rx="190" ry="215" fill="#f6e3cf"/>
<path d="M350 610 Q540 470 730 610 L730 560 Q540 440 350 560Z" fill="#b3262b"/><rect x="350" y="560" width="380" height="60" fill="#b3262b"/>
{eyes}
<path d="M425 735 Q470 710 510 740" fill="none"/><path d="M570 740 Q610 710 655 735" fill="none"/>
<path d="M470 905 Q540 860 610 905 Q540 890 470 905Z" fill="#5a3418"/>
{mouth(m, 540, 950, '<path d="M490 960 Q540 930 590 960" fill="none"/>')}
<path d="M705 700 Q735 740 710 770 Q690 740 705 700Z" fill="#8fd3f4"/></g>'''


def vex(m, blink):
    eyes = ('<path d="M410 775 L475 775 M605 775 L670 775" fill="none"/>' if blink else
            '<ellipse cx="445" cy="775" rx="30" ry="18" fill="#fff"/><ellipse cx="635" cy="775" rx="30" ry="18" fill="#fff"/>'
            '<circle cx="452" cy="780" r="9" fill="#000"/><circle cx="628" cy="780" r="9" fill="#000"/>'
            '<path d="M410 765 L480 765 M600 765 L670 765" fill="none"/>')
    return f'''<g {ST}>
<path d="M290 1500 L320 1010 Q540 950 760 1010 L790 1500Z" fill="#161616"/>
<path d="M440 1000 L540 1230 L640 1000Z" fill="#eee"/>
<path d="M500 1010 L580 1010 L540 1060Z" fill="#2e9b55"/>
<rect x="505" y="880" width="70" height="130" fill="#e9c9a8"/>
<ellipse cx="540" cy="760" rx="165" ry="230" fill="#efd3b3"/>
<path d="M370 640 Q360 470 540 450 Q720 470 710 640 Q620 560 540 560 Q460 560 370 640Z" fill="#0a0a0a"/>
{eyes}
<path d="M430 735 L515 745 M565 745 L650 735" fill="none"/>
{mouth(m, 540, 905, '<path d="M475 905 L605 905" fill="none"/>')}</g>'''


def halloran(m, blink):
    pupils = ('<path d="M440 788 L476 788 M604 788 L640 788" fill="none" stroke-width="6"/>' if blink else
              '<circle cx="458" cy="785" r="11" fill="#000"/><circle cx="622" cy="785" r="11" fill="#000"/>')
    return f'''<g {ST}>
<path d="M280 1500 L320 1010 Q540 940 760 1010 L800 1500Z" fill="#6a3d9a"/>
<path d="M440 1000 L540 1180 L640 1000Z" fill="#f2e6ff"/>
<rect x="505" y="890" width="70" height="120" fill="#f1d6b8"/>
<circle cx="540" cy="470" r="105" fill="#c9ccd1"/>
<ellipse cx="540" cy="770" rx="175" ry="215" fill="#f6e3cf"/>
<path d="M365 700 Q380 520 540 520 Q700 520 715 700 Q620 600 540 600 Q460 600 365 700Z" fill="#c9ccd1"/>
<path d="M410 770 L505 770 L505 800 L410 800Z M575 770 L670 770 L670 800 L575 800Z" fill="#fff" fill-opacity=".5"/>
{pupils}
<path d="M505 785 L575 785" fill="none"/><path d="M405 760 L350 735 M675 760 L730 735" fill="none"/>
<path d="M430 730 L510 720" fill="none"/><path d="M570 720 L650 730" fill="none"/>
{mouth(m, 540, 905, '<path d="M470 905 Q540 885 610 905" fill="none"/>')}
<path d="M410 800 Q400 1000 440 1060" fill="none" stroke-width="5"/></g>'''


CHARS = [("Pierce", pierce, 190), ("Vex", vex, 540), ("Madame Halloran", halloran, 890)]
SCALE = 0.62


def scene_svg(speaker, level, blink):
    parts = [f'''<defs><linearGradient id="w" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3b2416"/><stop offset="1" stop-color="#1c110a"/></linearGradient>
<radialGradient id="g" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#ffd27a" stop-opacity=".9"/><stop offset="1" stop-color="#ffd27a" stop-opacity="0"/></radialGradient></defs>
<rect width="{W}" height="{H}" fill="url(#w)"/>
<g stroke="#000" stroke-width="6"><rect x="40" y="260" width="180" height="420" fill="#4a2e1b"/><rect x="860" y="260" width="180" height="420" fill="#4a2e1b"/>
<rect x="450" y="220" width="180" height="300" rx="80" fill="#150d08"/></g>
<circle cx="130" cy="310" r="140" fill="url(#g)"/><circle cx="950" cy="310" r="140" fill="url(#g)"/>
<text x="540" y="430" font-family="DejaVu Serif" font-weight="bold" font-size="80" text-anchor="middle" fill="#ffe3a1" stroke="#000" stroke-width="3">404</text>
<rect x="0" y="930" width="{W}" height="150" fill="#2b1a10" stroke="#000" stroke-width="6"/>''']
    for name, fn, cx in CHARS:
        m = level if name == speaker else 0
        op = 1.0 if speaker in (None, name) else 0.7
        tx, ty = cx - 540 * SCALE, 70
        parts.append(f'<g opacity="{op}" transform="translate({tx:.1f},{ty}) scale({SCALE})">{fn(m, blink)}</g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{"".join(parts)}</svg>'


def ensure_renderer():
    if shutil.which("rsvg-convert"):
        return
    subprocess.run("sudo apt-get update -qq && sudo apt-get install -y -qq librsvg2-bin fonts-dejavu-core",
                   shell=True, check=False)
    if not shutil.which("rsvg-convert"):
        raise SystemExit("rsvg-convert is missing and could not be installed.")


_cache = {}


def base_frame(work, speaker, level, blink):
    key = (speaker, level, blink)
    if key not in _cache:
        svg = work / f"s_{len(_cache)}.svg"
        png = svg.with_suffix(".png")
        svg.write_text(scene_svg(speaker, level, blink), encoding="utf-8")
        subprocess.run(["rsvg-convert", "-w", str(W), "-h", str(H), "-o", str(png), str(svg)], check=True)
        _cache[key] = Image.open(png).convert("RGBA")
    return _cache[key]


# ---------------------------------------------------------------- captions
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


def overlay(name, role, text):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle((0, 1080, W, 1800), fill=(0, 0, 0, 185))
    d.rectangle((0, 0, W, 150), fill=(0, 0, 0, 160))
    d.text((W // 2, 75), "THE TOKEN HOTEL", font=ImageFont.truetype(FONT_S, 54), fill=(230, 190, 110), anchor="mm")
    d.text((60, 1120), name + (f"  ·  {role}" if role else ""),
           font=ImageFont.truetype(FONT_B, 48), fill=(230, 190, 110))
    size = 76 if len(text) < 90 else 64
    font = ImageFont.truetype(FONT_B, size)
    y = 1210
    for ln in wrap(d, text, font, W - 120):
        d.text((60, y), ln, font=font, fill=(255, 255, 255))
        y += int(size * 1.25)
    d.text((W // 2, 1860), "AI-generated characters and voices", font=ImageFont.truetype(FONT_B, 34),
           fill=(200, 200, 200), anchor="mm")
    return ov


# ---------------------------------------------------------------- voice
def post(model, payload):
    req = urllib.request.Request(
        API.format(model), data=json.dumps(payload).encode(), method="POST",
        headers={"x-goog-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def gen_voice(text, speaker, out_wav):
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
                time.sleep(20)
                continue
            print(f"Voice failed ({e.code}) for {speaker}.", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Voice failed ({e}) for {speaker}.", file=sys.stderr)
            return None
    return None


def mouth_levels(wav, n_frames, text):
    """One mouth level (0,1,2) per frame from the voice loudness, or a pretend pattern."""
    if wav and Path(wav).exists():
        with wave.open(str(wav)) as w:
            samples = array.array("h", w.readframes(w.getnframes()))
        win = 24000 // FPS
        rms = []
        for i in range(n_frames):
            seg = samples[i * win:(i + 1) * win]
            rms.append(math.sqrt(sum(s * s for s in seg) / len(seg)) if seg else 0.0)
        peak = max(rms) or 1.0
        return [0 if r / peak < 0.15 else 1 if r / peak < 0.5 else 2 for r in rms]
    pattern = [2, 1, 2, 0, 1, 2, 1, 0]
    talk = min(n_frames, int(len(text.split()) * 0.4 * FPS))
    return [pattern[(i + len(text)) % len(pattern)] if i < talk else 0 for i in range(n_frames)]


# ---------------------------------------------------------------- video
def make_scene(work, idx, speaker, name, role, text, voice_as, min_len=2.0, pad=0.5):
    wav, mp4 = work / f"{idx:02d}.wav", work / f"{idx:02d}.mp4"
    dur = gen_voice(text, voice_as, wav) if voice_as else None
    has_voice = dur is not None
    if dur is None:
        dur = max(min_len, len(text.split()) * 0.4)
    total = dur + pad
    n = max(1, round(total * FPS))
    levels = mouth_levels(wav if has_voice else None, n, text) if speaker else [0] * n
    ov = overlay(name, role, text)
    frames = work / f"f{idx:02d}"
    frames.mkdir(exist_ok=True)
    for i in range(n):
        blink = 1 if ((i + idx * 7) % 40) in (0, 1) else 0
        im = Image.alpha_composite(base_frame(work, speaker, levels[i], blink), ov).convert("RGB")
        im.save(frames / f"{i:04d}.jpg", quality=92)
    tmp = work / f"tmp_{idx:02d}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "%04d.jpg")]
    if has_voice:
        cmd += ["-i", str(wav), "-af", "apad"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono"]
    cmd += ["-t", f"{total:.2f}", "-r", "30", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "24000", "-ac", "1", "-shortest", str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.rename(mp4)
    shutil.rmtree(frames)
    return mp4


def main():
    ensure_renderer()
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))
    work = ROOT / "build" / DAY
    work.mkdir(parents=True, exist_ok=True)
    scenes = [make_scene(work, 0, None, "Narrator", "", "Tonight at the Token Hotel: " + ep["situation"],
                         "Narrator", min_len=3)]
    for i, l in enumerate(ep["lines"], start=1):
        scenes.append(make_scene(work, i, l["speaker"], l["speaker"], l["role"], l["line"], l["speaker"]))
    scenes.append(make_scene(work, len(ep["lines"]) + 1, None, "Narrator", "",
                             "Every line was written by an AI agent. New episode every day.", "Narrator", min_len=3))

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
