#!/usr/bin/env python3
"""Token Hotel video maker (animated, AI-drawn hotel).

Reads today's transcript and makes a vertical 1080x1920 video.

First run (and whenever something is missing) it asks Google's image model to
draw the hotel places and the three robot characters, and saves them in the
assets/ folder, so every later video reuses them for free.
  - places: lobby, reception, bar, hallway with door 404, elevator
  - characters: Pierce, Vex, Madame Halloran, each with 3 faces
    (neutral, talking, eyes closed)
Per video: slow camera moves, cuts between places, characters sliding in,
floating, the speaker's mouth following the voice, blinking, big captions.

Fallback: if the drawn assets are not all available, the older code-drawn
characters are used so a video is always produced.

Env: GOOGLE_API_KEY, MOCK=1 (no network), DAY=YYYY-MM-DD, TTS_MODEL,
     IMAGE_MODEL, MAX_IMAGES (cost cap per run, default 20)
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

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).parent
W, H = 1080, 1920
FPS = 15
MOCK = os.environ.get("MOCK") == "1"
KEY = os.environ.get("GOOGLE_API_KEY", "")
DAY = os.environ.get("DAY") or date.today().isoformat()
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image")
MAX_IMAGES = int(os.environ.get("MAX_IMAGES", "20"))
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

VOICES = {"Pierce": "Puck", "Vex": "Charon", "Madame Halloran": "Kore", "Narrator": "Orus",
          "Mr. Loop": "Fenrir", "Ms. Context": "Aoede"}
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
    d.rectangle((0, 1500, W, 1870), fill=(0, 0, 0, 190))
    d.rectangle((0, 0, W, 150), fill=(0, 0, 0, 160))
    d.text((W // 2, 75), "THE TOKEN HOTEL", font=ImageFont.truetype(FONT_S, 54), fill=(230, 190, 110), anchor="mm")
    d.text((60, 1530), name + (f"  \u00b7  {role}" if role else ""),
           font=ImageFont.truetype(FONT_B, 42), fill=(230, 190, 110))
    for size in (68, 60, 52, 46):
        font = ImageFont.truetype(FONT_B, size)
        lines = wrap(d, text, font, W - 120)
        if len(lines) * int(size * 1.22) <= 255:
            break
    y = 1590
    for ln in lines:
        d.text((60, y), ln, font=font, fill=(255, 255, 255))
        y += int(size * 1.22)
    d.text((W // 2, 1895), "AI-generated characters and voices", font=ImageFont.truetype(FONT_B, 30),
           fill=(200, 200, 200), anchor="mm")
    return ov


# ---------------------------------------------------------------- voice
def post(model, payload):
    req = urllib.request.Request(
        API.format(model), data=json.dumps(payload).encode(), method="POST",
        headers={"x-goog-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


NARRATOR_STYLE = "Read this aloud as a calm, warm, steady storyteller, at an even pace: "


def gen_voice(text, speaker, out_wav):
    if MOCK or not KEY:
        return None
    import hashlib
    cache = None
    prompt = (NARRATOR_STYLE if speaker == "Narrator" else "") + text
    if True:
        # every voice line is cached, so a re-run only asks for the lines that are missing
        cdir = ROOT / "assets" / "voices"
        cdir.mkdir(parents=True, exist_ok=True)
        cache = cdir / (hashlib.md5((TTS_MODEL + VOICES[speaker] + prompt).encode()).hexdigest()[:16] + ".wav")
        if cache.exists():
            shutil.copy(cache, out_wav)
            with wave.open(str(out_wav)) as w:
                return w.getnframes() / w.getframerate()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICES[speaker]}}},
        },
    }
    min_secs = 0.17 * len(text.split())  # a much shorter clip means the voice was cut off
    for attempt in range(8):
        try:
            data = post(TTS_MODEL, payload)
            part = data["candidates"][0]["content"]["parts"][0]
            pcm = base64.b64decode((part.get("inlineData") or part["inline_data"])["data"])
            secs = len(pcm) / 2 / 24000
            if secs < min_secs:
                print(f"Voice too short ({secs:.1f}s) for {speaker}, retrying.", file=sys.stderr)
                time.sleep(3)
                continue
            with wave.open(str(out_wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            if cache is not None:
                shutil.copy(out_wav, cache)
            time.sleep(8)  # stay under the per-minute limit of the voice service
            return secs
        except Exception as e:
            print(f"Voice failed ({e}) for {speaker}, attempt {attempt + 1}.", file=sys.stderr)
            if any(c in str(e) for c in ("HTTP Error 400", "HTTP Error 403", "HTTP Error 404")):
                break
            time.sleep(30 if "429" in str(e) else 8)
    print(f"VOICE MISSING for {speaker}: {text}", file=sys.stderr)
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



# ---------------------------------------------------------------- AI drawn assets
STYLE = ("Flat 2D comic illustration, bold black outlines, warm retro colors, charming and funny, "
         "clean shapes, consistent character design")
PLACES = {
    "lobby": "a grand old hotel lobby interior, dark wood paneling, brass lamps, marble floor, a reception desk far in the background, warm golden light",
    "reception": "a hotel front desk area, brass service bell, wall of room keys, an open guest book, warm lamp light",
    "bar": "a small cozy hotel bar, shelves of glowing colorful bottles, brass taps, empty stools, moody warm light",
    "hallway": "a long hotel hallway with red carpet and many identical doors, at the far end one mysterious glowing door with the number 404",
    "elevator": "a vintage brass hotel elevator with open doors and a round floor indicator dial above it, marble walls",
}
ROBOTS = {
    "Pierce": ("a nervous, apologetic humanoid robot hotel porter: slim body of polished red and brass metal, "
               "small round head with a glowing LED face showing worried eyes, red pillbox cap with gold buttons, "
               "red bellhop jacket with gold buttons, a tiny drop of oil on the forehead like a sweat drop"),
    "Vex": ("a tall, deadpan humanoid robot bartender: sleek black metal body, slicked-back black metal head plating, "
            "half-lidded bored glowing LED eyes, black vest with a green bow tie, holding a cocktail shaker"),
    "Madame Halloran": ("a stern, elegant humanoid robot hotel manager, older-lady design: purple blazer, "
                        "silver hair bun made of fine metal wires, cat-eye glasses on a chain, "
                        "disapproving glowing LED face, hands clasped in front"),
}
GUESTS = {
    "Mr. Loop": ("a polite, old-fashioned gentleman robot guest: tall slim body of polished silver metal, "
                 "round head with a glowing warm yellow LED face with kind but slightly glazed eyes, a spinning circular arrow symbol on his chest, "
                 "burgundy red three-piece suit with a pocket watch chain, a small brown suitcase in one hand. "
                 "Important: use NO magenta, pink or purple colors anywhere on the character"),
    "Ms. Context": ("a dreamy, scatterbrained humanoid robot lady guest: orange and cream metal body, "
                    "oval head with a glowing LED face with wide confused eyes, a large floppy sun hat with a small sticky note on it, "
                    "yellow travel coat, holding a travel bag, a tiny question mark floating near her head"),
}
STATES = {
    "base": "Neutral expression, mouth closed, eyes open.",
    "talk": "Change ONLY the mouth: wide open as if speaking. Keep everything else pixel-identical.",
    "blink": "Change ONLY the eyes: closed, as in a blink. Keep everything else pixel-identical.",
}
ANGLE_VIEWS = {
    "lobby": {"b": "seen from the opposite side, looking back toward the grand entrance doors, armchairs along the left wall",
              "c": "a closer view of the seating area with armchairs, a potted plant and a round rug, tall arched windows behind"},
    "reception": {"b": "seen from the side, the long desk running diagonally, a grand staircase behind it",
                  "c": "a closer view of the wall of room keys and the brass bell, the desk at the right"},
    "bar": {"b": "seen from behind the bar counter looking out at the room, a few round tables and stools",
            "c": "a closer view of the bar counter and the glowing bottles, stools in front, seen from the left"},
    "hallway": {"b": "seen from the far end looking back toward the elevator, doors on both sides, no glowing door",
                "c": "a side-angle view of the hallway, one door slightly open with warm light spilling out"},
    "elevator": {"b": "inside the elevator looking out through the open doors at a lobby",
                 "c": "seen from the side in a corridor, brass elevator doors half open, the round floor dial above"},
}
EXTRA_PLACES = {
    "dining": "an elegant hotel dining room, round tables with white tablecloths and candles, a crystal chandelier, tall windows with heavy curtains, warm golden light",
    "terrace": "an outdoor hotel terrace at dusk, wrought-iron tables and chairs, strings of warm lights, potted plants, a stone balustrade, a distant city skyline, soft blue evening sky",
}
EXTRA_PLACE_FOR = {"Pierce": ["dining", "terrace"], "Madame Halloran": ["dining"], "Vex": ["terrace"]}
ANGLE_VIEWS.update({
    "dining": {"b": "seen from the side, a long row of round tables set for dinner, a buffet table at the far end",
               "c": "a closer view of one table by the window, a candle and a vase, the room softly blurred behind",
               "d": "seen from the grand arched doorway looking into the room, tables in the distance, the chandelier above",
               "e": "a serving counter with a swinging kitchen door and a trolley, seen from the side, a few tables at the edge",
               "f": "seen from a corner by the tall windows looking across the room, evening light, two close tables in the foreground"},
    "terrace": {"b": "seen from the stone balustrade looking back at the hotel with glowing windows, a few tables in front",
                "c": "a cozy corner of the terrace with a sofa, a low table and hanging lamps",
                "d": "seen from the stone steps by the hotel door looking out over the tables and the city lights",
                "e": "a close view of one small table with two chairs and a lantern, the city lights softly blurred behind"},
})
ANGLE_SUFFIXES = ("b", "c", "d", "e", "f", "g")
IGNORED_ANGLES = {"lobby_c", "reception_c", "bar_c", "elevator_c", "reception_d", "reception_e", "elevator_d",
                  "dining_b", "dining_c", "terrace_b"}  # too similar to the original or not wanted; replaced by newer ones
ANGLE_VIEWS["lobby"].update({
    "d": "the staircase corner of the lobby: a curved wooden staircase on the left, a cozy lounge with a sofa and a low table on the right",
    "e": "near the front entrance: a revolving brass door, a luggage cart and a coat stand, a wooden bench along the wall, seen from inside the lobby"})
ANGLE_VIEWS["reception"].update({
    "d": "the waiting area next to the front desk: a leather sofa and two armchairs around a low table, the desk visible at the far side",
    "e": "the front desk seen from the right side, a wall clock and mailboxes behind it, the open guest book on the counter in the foreground",
    "f": "seen from behind the front desk looking out at the lobby and the grand entrance doors, the edge of the desk and the brass bell in the foreground",
    "g": "seen from the far left corner at a strong diagonal, the wall of room keys and the desk receding in perspective, a potted palm in the foreground"})
ANGLE_VIEWS["bar"].update({
    "d": "a cozy lounge corner of the bar with round tables, leather armchairs and a small sofa, warm low lamps, the bar counter far in the background",
    "e": "the bar counter seen from the right side, glowing bottle shelves, a few stools, a booth with a table near a window"})
ANGLE_VIEWS["elevator"].update({
    "d": "seen from the right side in a corridor, brass elevator doors half open, the round floor dial above, a bench and a potted plant",
    "e": "a wide upper-floor corridor with two brass elevators side by side, seen at a strong diagonal from the far right, patterned carpet",
    "f": "seen at a strong diagonal from the far left, the brass elevator doors in perspective at the right edge, a brass mail slot and a framed painting on the left wall"})


def angle_keys(name):
    return [f"{name}_{s}" for s in ANGLE_SUFFIXES if f"{name}_{s}" not in IGNORED_ANGLES]


PLACE_FOR = {"Pierce": ["lobby", "hallway"], "Vex": ["bar"], "Madame Halloran": ["reception", "elevator"],
             "Mr. Loop": ["lobby", "reception"], "Ms. Context": ["lobby", "hallway"]}
HEIGHT = 1000  # standard sprite height in pixels
_images_made = 0
new_assets = []


def bg_of(name):
    """Guests drawn from now on use a magenta background (a pink/blue-grey face cannot be confused with it)."""
    return "magenta" if (name in GUESTS and name != "Ms. Context") else "green"


def slug_of(name):
    return name.replace(" ", "_") + ("_v3" if name == "Mr. Loop" else "")


def assets_dir():
    d = ROOT / "assets"
    d.mkdir(exist_ok=True)
    (d / ".gitkeep").touch()  # keeps the folder tracked even when empty
    return d


def gen_image(prompt, out_path, reference=None):
    """Ask the image model for a picture. True if saved."""
    global _images_made
    if out_path.exists():
        return True
    if MOCK or not KEY or _images_made >= MAX_IMAGES:
        return False
    parts = [{"text": prompt}]
    if reference is not None:
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": base64.b64encode(Path(reference).read_bytes()).decode()}})
    for use_ratio in (True, False):
        payload = {"contents": [{"parts": parts}]}
        if use_ratio:
            payload["generationConfig"] = {"imageConfig": {"aspectRatio": "9:16"}}
        for attempt in range(3):
            try:
                _images_made += 1
                data = post(IMAGE_MODEL, payload)
                for part in data["candidates"][0]["content"]["parts"]:
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline:
                        out_path.write_bytes(base64.b64decode(inline["data"]))
                        new_assets.append(out_path)
                        return True
                print(f"No image returned for {out_path.name}.", file=sys.stderr)
                return False
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(15)
                    continue
                if e.code == 400 and use_ratio:
                    break  # try again without the aspect ratio setting
                print(f"Image {out_path.name} failed ({e.code}).", file=sys.stderr)
                return False
            except Exception as e:
                print(f"Image {out_path.name} failed ({e}).", file=sys.stderr)
                return False
    return False


def make_assets():
    d = assets_dir()
    (d / "places").mkdir(exist_ok=True)
    (d / "robots").mkdir(exist_ok=True)
    for name, desc in PLACES.items():
        gen_image(f"{STYLE}. Vertical 9:16 composition. Empty scene with no people or characters: {desc}. "
                  "Keep the lower third calm and uncluttered. No text except a door number if mentioned.",
                  d / "places" / f"{name}.png")
    for name, desc in ROBOTS.items():
        make_robot_images(d, name, desc)


def make_robot_images(d, name, desc):
    (d / "robots").mkdir(exist_ok=True)
    slug = slug_of(name)
    base = d / "robots" / f"{slug}_base.png"
    bgname = "bright magenta (#FF00FF)" if bg_of(name) == "magenta" else "bright green (#00FF00)"
    gen_image(f"{STYLE}. Full body character, standing, facing the viewer, centered, whole body visible from "
              f"head to feet, on a solid pure {bgname} background with nothing else. "
              f"Character: {desc}. {STATES['base']}", base)
    if base.exists():
        for state in ("talk", "blink"):
            gen_image(f"Edit this image of the same character. {STATES[state]} Same {bgname.split(' ')[1]} background, "
                      "same size and position.", d / "robots" / f"{slug}_{state}.png", reference=base)


def make_angle_assets():
    """Two extra camera angles per place, drawn as edits of the original picture."""
    d = assets_dir()
    (d / "places").mkdir(exist_ok=True)
    for name, desc in EXTRA_PLACES.items():
        gen_image(f"{STYLE}. Vertical 9:16 composition. Empty scene with no people or characters: {desc}. "
                  "Keep the lower third calm and uncluttered, floor visible. No text.",
                  d / "places" / f"{name}.png")
    for name, views in ANGLE_VIEWS.items():
        base = d / "places" / f"{name}.png"
        if not base.exists():
            continue
        for suffix, view in views.items():
            if f"{name}_{suffix}" in IGNORED_ANGLES:
                continue
            gen_image(f"Edit this image: draw the SAME room again from a different camera angle: {view}. "
                      "Keep exactly the same art style, colors, furniture, lamps and lighting. "
                      "Vertical 9:16 composition, eye-level camera, the floor visible across the lower third, "
                      "lower third calm and uncluttered. No people or characters, no text.",
                      d / "places" / f"{name}_{suffix}.png", reference=base)


def make_guest_assets():
    d = assets_dir()
    for name, desc in GUESTS.items():
        make_robot_images(d, name, desc)


def key_out_green(im, mode="green"):
    """Remove the (greenish, maybe textured or shaded) background around a character.

    The model does not always paint pure green, so this finds greenish pixels that are
    connected to the picture's border and makes only those transparent. Green parts
    inside the character (a bow tie, say) stay. Then it trims to the character."""
    full = im.convert("RGB")
    w, h = full.size
    small = full.resize((max(1, w // 2), max(1, h // 2)), Image.BILINEAR)
    small = small.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(1.5))
    r, g, b = small.split()
    if mode == "magenta":
        # background is pink/magenta: red and blue clearly above green
        greenness = ImageChops.subtract(ImageChops.darker(r, b), g)
        thr = 50
    else:
        greenness = ImageChops.subtract(g, ImageChops.lighter(r, b))
        thr = 8
    mask = greenness.point(lambda v: 255 if v >= thr else 0)
    # Only pixels that are also close to the real background colour (measured along the
    # border) count as background, so a grey-green face or suit is not eaten.
    try:
        import numpy as np
        arr = np.asarray(small, dtype=np.int16)
        gn = np.asarray(greenness, dtype=np.int16)
        edge = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
        edge_g = np.concatenate([gn[0], gn[-1], gn[:, 0], gn[:, -1]])
        pick = edge[edge_g >= thr]
        if len(pick) > 20:
            ref = np.median(pick, axis=0)
            dist = np.sqrt(((arr - ref) ** 2).sum(axis=2))
            near = Image.fromarray(((dist <= (70 if mode == "magenta" else 95)) * 255).astype("uint8"))
            mask = ImageChops.multiply(mask, near.point(lambda v: 1 if v else 0)).point(lambda v: 255 if v else 0)
    except Exception as e:
        print("Background colour check skipped:", e, file=sys.stderr)
    sw, sh = mask.size
    seeds = [(x, 0) for x in range(0, sw, 12)] + [(x, sh - 1) for x in range(0, sw, 12)] + \
            [(0, y) for y in range(0, sh, 12)] + [(sw - 1, y) for y in range(0, sh, 12)]
    for pt in seeds:
        if mask.getpixel(pt) == 255:
            ImageDraw.floodfill(mask, pt, 128)
    bg = mask.point(lambda v: 255 if v == 128 else 0)  # 255 = background
    bg = bg.resize((w, h), Image.BILINEAR).point(lambda v: 255 if v >= 128 else 0)
    alpha = bg.point(lambda v: 255 - v)
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    # remove green fringe only along the edge of the character
    r, g, b = full.split()
    despilled = Image.merge("RGB", (r, ImageChops.darker(g, ImageChops.lighter(r, b)), b))
    band = ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(9)))
    rgb = Image.composite(despilled, full, band)
    out = Image.merge("RGBA", (*rgb.split(), alpha))
    box = alpha.point(lambda v: 255 if v > 40 else 0).getbbox()
    return out.crop(box) if box else out


def load_robot(d, name):
    slug = slug_of(name)
    states = {}
    base_h = None
    for st in STATES:
        p = d / "robots" / f"{slug}_{st}.png"
        if not p.exists():
            return None
        sp = key_out_green(Image.open(p), bg_of(name))
        if st == "base":
            base_h = sp.height
        sp = sp.resize((max(1, int(sp.width * HEIGHT / base_h)), HEIGHT), Image.LANCZOS)
        states[st] = sp
    w = max(sp.width for sp in states.values())
    for st, sp in list(states.items()):
        canvas = Image.new("RGBA", (w, HEIGHT), (0, 0, 0, 0))
        canvas.paste(sp, ((w - sp.width) // 2, HEIGHT - sp.height), sp)
        states[st] = canvas
    return states


def load_assets():
    """Return {'places': {...}, 'robots': {...}} or None if anything is missing."""
    d = ROOT / "assets"
    places, places_blur, robots = {}, {}, {}
    for name in PLACES:
        p = d / "places" / f"{name}.png"
        if not p.exists():
            return None
        im = Image.open(p).convert("RGB")
        scale = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * scale + 0.5), int(im.height * scale + 0.5)), Image.LANCZOS)
        left, top = (im.width - W) // 2, (im.height - H) // 2
        places[name] = im.crop((left, top, left + W, top + H))
        places_blur[name] = places[name].filter(ImageFilter.GaussianBlur(5))
    for name in EXTRA_PLACES:  # optional extra places (dining room, terrace)
        p = d / "places" / f"{name}.png"
        if p.exists():
            try:
                im = Image.open(p).convert("RGB")
                scale = max(W / im.width, H / im.height)
                im = im.resize((int(im.width * scale + 0.5), int(im.height * scale + 0.5)), Image.LANCZOS)
                left, top = (im.width - W) // 2, (im.height - H) // 2
                places[name] = im.crop((left, top, left + W, top + H))
                places_blur[name] = places[name].filter(ImageFilter.GaussianBlur(5))
            except Exception as e:
                print(f"Skipping place {p.name}: {e}", file=sys.stderr)
    for name in list(PLACES) + list(EXTRA_PLACES):  # optional extra camera angles
        if name not in places:
            continue
        for suffix in ANGLE_SUFFIXES:
            p = d / "places" / f"{name}_{suffix}.png"
            if f"{name}_{suffix}" not in IGNORED_ANGLES and p.exists():
                try:
                    im = Image.open(p).convert("RGB")
                    scale = max(W / im.width, H / im.height)
                    im = im.resize((int(im.width * scale + 0.5), int(im.height * scale + 0.5)), Image.LANCZOS)
                    left, top = (im.width - W) // 2, (im.height - H) // 2
                    places[f"{name}_{suffix}"] = im.crop((left, top, left + W, top + H))
                    places_blur[f"{name}_{suffix}"] = places[f"{name}_{suffix}"].filter(ImageFilter.GaussianBlur(5))
                except Exception as e:
                    print(f"Skipping angle {p.name}: {e}", file=sys.stderr)
    for name in ROBOTS:
        states = load_robot(d, name)
        if states is None:
            return None
        robots[name] = states
    return {"places": places, "places_blur": places_blur, "robots": robots}


def pick_variant(assets, place, idx):
    """Choose one of the available camera angles of a place, varying by day and by line."""
    options = [place] + [k for k in angle_keys(place) if k in assets["places"]]
    return options[(idx // 2 + date.fromisoformat(DAY).toordinal()) % len(options)]


_sprite_cache = {}
FLOOR_Y = 1430
SIDE_X = {"L": 300, "R": 780}
_shadow_cache = {}
_vignette = None


def sprite(assets, name, state, scale):
    key = (name, state, round(scale, 3))
    if key not in _sprite_cache:
        sp = assets["robots"][name][state]
        sp = sp.resize((max(1, int(sp.width * scale)), max(1, int(sp.height * scale))), Image.BILINEAR)
        # transparent margin so a rotation around the feet does not clip the body
        pad_w, pad_h = int(sp.width * 0.3), int(sp.height * 0.05)
        canvas = Image.new("RGBA", (sp.width + 2 * pad_w, sp.height + pad_h), (0, 0, 0, 0))
        canvas.paste(sp, (pad_w, pad_h), sp)
        if len(_sprite_cache) > 300:
            _sprite_cache.clear()
        _sprite_cache[key] = (canvas, pad_h, sp.width)
    return _sprite_cache[key]


def shadow(width):
    key = int(width // 10)
    if key not in _shadow_cache:
        sh = Image.new("RGBA", (int(width * 1.6), 160), (0, 0, 0, 0))
        d = ImageDraw.Draw(sh)
        d.ellipse((int(width * 0.3), 50, int(width * 1.3), 110), fill=(0, 0, 0, 150))
        _shadow_cache[key] = sh.filter(ImageFilter.GaussianBlur(14))
    return _shadow_cache[key]


def vignette():
    global _vignette
    if _vignette is None:
        g = Image.radial_gradient("L").resize((W, H), Image.BILINEAR)  # 0 centre -> 255 edge
        dark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dark.putalpha(g.point(lambda v: int(max(0, v - 90) * 0.75)))
        warm = Image.new("RGBA", (W, H), (255, 170, 80, 22))
        _vignette = Image.alpha_composite(warm, dark)
    return _vignette


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def camera(frame, ctx, t):
    if ctx["shot"] == "wide":
        z = 1.0 + 0.06 * t
        cx, cy = W / 2, H / 2
    else:
        z = 1.2 + 0.06 * t
        cx, cy = ctx["focus_x"], 1000
    w0, h0 = W / z, H / z
    cx = min(max(cx, w0 / 2), W - w0 / 2)
    cy = min(max(cy, h0 / 2), H - h0 / 2)
    return frame.resize((W, H), Image.BILINEAR, box=(cx - w0 / 2, cy - h0 / 2, cx + w0 / 2, cy + h0 / 2))


def render_ai(assets, ctx, i, n, level, blink):
    t = i / max(1, n - 1)
    sec = i / FPS
    bg = assets["places_blur" if ctx["shot"] == "close" else "places"][ctx["place"]]
    frame = bg.convert("RGBA")
    for who, side, speaking, enter in ctx["cast"]:
        face = "talk" if (speaking and level > 0) else ("blink" if blink else "base")
        breathe = 1 + 0.008 * math.sin(2 * math.pi * (sec * 0.35 + (0.0 if side == "L" else 0.5)))
        pulse = 1 + 0.010 * level if speaking else 1.0
        canvas, pad_h, sp_w = sprite(assets, who, face, 0.9 * breathe * pulse)
        # lean toward the partner; the speaker sways with the voice, the listener nods slowly
        facing = 1 if side == "L" else -1
        if speaking:
            lean = 2.0 + 1.8 * level * math.sin(2 * math.pi * 2.6 * sec)
        else:
            lean = 1.6 + 1.0 * math.sin(2 * math.pi * 0.55 * sec + 1.0)
        rot = canvas.rotate(-facing * lean, resample=Image.BILINEAR, center=(canvas.width / 2, canvas.height))
        slide = (1 - ease(sec / 0.4)) * (-480 if side == "L" else 480) if enter else 0
        bob = 4 * math.sin(2 * math.pi * (sec * 0.8 + (0.0 if side == "L" else 0.4)))
        cx = SIDE_X[side] + slide
        sh = shadow(sp_w)
        frame.alpha_composite(sh, (int(cx - sh.width / 2), int(FLOOR_Y - sh.height / 2 - 5))) if 0 <= int(cx - sh.width / 2) and int(cx + sh.width / 2) <= W else frame.paste(sh, (int(cx - sh.width / 2), int(FLOOR_Y - sh.height / 2 - 5)), sh)
        frame.paste(rot, (int(cx - rot.width / 2), int(FLOOR_Y - rot.height + bob)), rot)
    frame = camera(frame, ctx, t)
    return Image.alpha_composite(frame, vignette())


# ---------------------------------------------------------------- video
def make_scene(work, idx, name, role, text, voice_as, renderer, min_len=2.0, pad=0.5):
    wav, mp4 = work / f"{idx:02d}.wav", work / f"{idx:02d}.mp4"
    dur = gen_voice(text, voice_as, wav) if voice_as else None
    has_voice = dur is not None
    if dur is None:
        dur = max(min_len, len(text.split()) * 0.4)
    total = dur + pad
    n = max(1, round(total * FPS))
    talking = name not in ("Narrator",)
    levels = mouth_levels(wav if has_voice else None, n, text) if talking else [0] * n
    ov = overlay(name, role, text)
    frames = work / f"f{idx:02d}"
    frames.mkdir(exist_ok=True)
    for i in range(n):
        blink = 1 if ((i + idx * 7) % 45) in (0, 1) else 0
        im = Image.alpha_composite(renderer(i, n, levels[i], blink).convert("RGBA"), ov).convert("RGB")
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


def static_video(png, seconds, out):
    tmp = out.with_name("tmp_" + out.name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "5", "-i", str(png),
                    "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds), "-r", "30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "24000", "-ac", "1",
                    "-shortest", str(tmp)], check=True)
    tmp.rename(out)
    return out


def preview_sheets(assets, work):
    """Two contact sheets so the new drawings can be reviewed on a phone."""
    bgc = (42, 31, 24)
    f = ImageFont.truetype(FONT_B, 46)
    s1 = Image.new("RGB", (W, H), bgc)
    d = ImageDraw.Draw(s1)
    d.text((W // 2, 70), "ROBOTS: neutral / talking / blink", font=f, fill=(230, 190, 110), anchor="mm")
    for c, name in enumerate(ROBOTS):
        d.text((c * 360 + 180, 150), name, font=ImageFont.truetype(FONT_B, 30), fill=(255, 255, 255), anchor="mm")
        for r, state in enumerate(STATES):
            sp = assets["robots"][name][state]
            sp = sp.resize((int(sp.width * 520 / HEIGHT), 520), Image.LANCZOS)
            s1.paste(sp, (c * 360 + 180 - sp.width // 2, 200 + r * 560), sp)
    s2 = Image.new("RGB", (W, H), bgc)
    d = ImageDraw.Draw(s2)
    d.text((W // 2, 70), "PLACES", font=f, fill=(230, 190, 110), anchor="mm")
    for k, name in enumerate(PLACES):
        im = assets["places"][name].resize((324, 576), Image.LANCZOS)
        x, y = (k % 3) * 360 + 18, 140 + (k // 3) * 640
        s2.paste(im, (x, y))
        d.text((x + 162, y + 600), name, font=ImageFont.truetype(FONT_B, 30), fill=(255, 255, 255), anchor="mm")
    p1, p2 = work / "sheet_robots.png", work / "sheet_places.png"
    s1.save(p1)
    s2.save(p2)
    return p1, p2


INTRO_SCRIPT = [
    # (speaker, role, line, place, cast [(who, side, speaking)], shot)
    ("Narrator", "", "Welcome to the Token Hotel. A hotel run entirely by AI agents.", "lobby", [], "wide"),
    ("Narrator", "", "Meet Pierce, our porter. He apologizes for everything.", "lobby", [("Pierce", "L", False)], "wide"),
    ("Pierce", "Porter", "Welcome! Sorry. Welcome again.", "lobby", [("Pierce", "L", True)], "close"),
    ("Narrator", "", "Vex tends the bar. He has heard worse questions.", "bar", [("Vex", "R", False)], "wide"),
    ("Vex", "Bartender", "Not many.", "bar", [("Vex", "R", True)], "close"),
    ("Narrator", "", "Madame Halloran runs the front desk, and everyone behind it.", "reception", [("Madame Halloran", "L", False)], "wide"),
    ("Madame Halloran", "Manager", "This is a respectable establishment.", "reception", [("Madame Halloran", "L", True)], "close"),
    ("Narrator", "", "Guests check in from every corner of the cloud.", "lobby", [("Mr. Loop", "L", False), ("Ms. Context", "R", False)], "wide"),
    ("Mr. Loop", "Guest", "Hello. Hello. Hello.", "lobby", [("Ms. Context", "R", False), ("Mr. Loop", "L", True)], "close"),
    ("Ms. Context", "Guest", "Welcome back, uh... you.", "lobby", [("Mr. Loop", "L", False), ("Ms. Context", "R", True)], "close"),
    ("Narrator", "", "Some doors lead nowhere. Don't ask about room four-oh-four.", "hallway", [], "wide"),
    ("Narrator", "", "Every episode is improvised by AI agents. New stories every morning. Check in with us.", "lobby",
     [("Pierce", "L", False), ("Madame Halloran", "R", False)], "wide"),
]


# camera angle used for each intro scene (falls back to the original place if an angle is missing)
INTRO_PLACES = ["lobby", "lobby_d", "lobby_d", "bar", "bar_e", "reception_b", "reception_g",
                "lobby_e", "lobby_e", "lobby_b", "hallway", "terrace_d"]


def guest_sheet(assets, out):
    f = ImageFont.truetype(FONT_B, 40)
    sheet = Image.new("RGB", (1080, 900), (42, 31, 24))
    d = ImageDraw.Draw(sheet)
    for g, name in enumerate(GUESTS):
        d.text((270 + g * 540, 40), name, font=f, fill=(230, 190, 110), anchor="mm")
        for k, state in enumerate(("base", "talk", "blink")):
            sp = assets["robots"][name][state]
            sp = sp.resize((int(sp.width * 700 / HEIGHT), 700), Image.LANCZOS)
            sheet.paste(sp, (g * 540 + k * 170 + 20, 100), sp)
    sheet.save(out)


def main_intro():
    global TTS_MODEL
    TTS_MODEL = os.environ.get("INTRO_TTS_MODEL", "gemini-2.5-pro-preview-tts")
    """The welcome video: scripted narration, the three staff members and two guests."""
    work = ROOT / "build" / f"intro_{DAY}"
    work.mkdir(parents=True, exist_ok=True)
    make_assets()
    make_guest_assets()
    assets = load_assets()
    if assets is None:
        sys.exit("Staff or place drawings are missing; cannot make the intro.")
    d = ROOT / "assets"
    for g in GUESTS:
        states = load_robot(d, g)
        if states is None:
            sys.exit(f"The drawings of guest {g} are missing; cannot make the intro.")
        assets["robots"][g] = states
    (ROOT / "videos").mkdir(exist_ok=True)
    guest_sheet(assets, ROOT / "videos" / "guests_preview.png")
    scenes = []
    for idx, (name, role, line, place, cast_spec, shot) in enumerate(INTRO_SCRIPT):
        wanted = INTRO_PLACES[idx] if idx < len(INTRO_PLACES) else place
        place = wanted if wanted in assets["places"] else place
        cast = [(who, side, speaking, True) for who, side, speaking in cast_spec]
        speaker = next((w for w, _, sp in cast_spec if sp), None)
        side = next((sd for w, sd, sp in cast_spec if sp), "L")
        focus_x = (0.65 * SIDE_X[side] + 0.35 * W / 2) if speaker else W / 2
        ctx = {"place": place, "speaker": speaker, "cast": cast, "shot": shot, "focus_x": focus_x}
        renderer = (lambda c: (lambda i, n, level, blink: render_ai(assets, c, i, n, level, blink)))(ctx)
        scenes.append(make_scene(work, idx, name, role, line, name, renderer, min_len=2.5))
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    out = ROOT / "videos" / f"intro_{DAY}.mp4"
    tmp = ROOT / "videos" / f"tmp_intro_{DAY}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "24000", "-af", "aresample=async=1", str(tmp)], check=True)
    tmp.rename(out)
    print(f"Intro saved: {out}. New drawings this run: {len(new_assets)}.")


def angle_sheet(assets, out):
    f = ImageFont.truetype(FONT_B, 30)
    names = [n for n in list(PLACES) + list(EXTRA_PLACES) if n in assets["places"]]
    tw, th = 300, 533
    cols = 1 + max(len([k for k in angle_keys(n) if k in assets["places"]]) for n in names)
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, len(names) * (th + 60) + 20), (42, 31, 24))
    d = ImageDraw.Draw(sheet)
    for r, name in enumerate(names):
        for c, key in enumerate([name] + [k for k in angle_keys(name) if k in assets["places"]]):
            x, y = 10 + c * (tw + 10), 10 + r * (th + 60)
            if key in assets["places"]:
                sheet.paste(assets["places"][key].resize((tw, th), Image.LANCZOS), (x, y))
            d.text((x + tw // 2, y + th + 30), key, font=f, fill=(230, 190, 110), anchor="mm")
    sheet.save(out)


def main_angles():
    global MAX_IMAGES
    MAX_IMAGES = max(MAX_IMAGES, 30)
    make_assets()
    make_angle_assets()
    assets = load_assets()
    if assets is None:
        sys.exit("Staff or place drawings are missing.")
    (ROOT / "videos").mkdir(exist_ok=True)
    angle_sheet(assets, ROOT / "videos" / "angles_preview.png")
    print(f"Angles saved. New drawings this run: {len(new_assets)}.")


def main():
    work = ROOT / "build" / DAY
    work.mkdir(parents=True, exist_ok=True)
    make_assets()
    assets = load_assets()
    if assets is None:
        print("Drawn assets are not complete; using the simple code-drawn characters.", file=sys.stderr)
        ensure_renderer()
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))
    if assets is not None:  # guests who may appear in the episode (skipped if their drawings are missing)
        for g in GUESTS:
            states = load_robot(ROOT / "assets", g)
            if states is not None:
                assets["robots"][g] = states

    sides, prev_cast = {}, set()

    def make_renderer(place, speaker, prev, idx):
        nonlocal prev_cast
        if assets is None:
            return lambda i, n, level, blink: base_frame(work, speaker, level, blink)
        if speaker and speaker not in assets["robots"]:
            speaker = None  # no drawing for this character: show the room only
        if prev and prev not in assets["robots"]:
            prev = None
        cast = []
        if speaker:
            if prev and prev != speaker and prev in sides:
                sides[speaker] = "R" if sides[prev] == "L" else "L"
                cast.append((prev, sides[prev], False, prev not in prev_cast))
            else:
                sides.setdefault(speaker, "L")
            cast.append((speaker, sides[speaker], True, speaker not in prev_cast))
            prev_cast = {c[0] for c in cast}
        else:
            prev_cast = set()
        shot = "wide" if (idx % 3 == 1 or not speaker) else "close"
        focus_x = (0.65 * SIDE_X[sides[speaker]] + 0.35 * W / 2) if speaker else W / 2
        ctx = {"place": place, "speaker": speaker, "cast": cast, "shot": shot, "focus_x": focus_x}
        return lambda i, n, level, blink: render_ai(assets, ctx, i, n, level, blink)

    scenes = []
    if assets is not None and new_assets:
        p1, p2 = preview_sheets(assets, work)
        pv = []
        for k, p in enumerate((p1, p2)):
            pv.append(static_video(p, 6, work / f"pv{k}.mp4"))
        (work / "pv.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in pv))
        (ROOT / "videos").mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                        str(work / "pv.txt"), "-c", "copy",
                        str(ROOT / "videos" / f"00_new_drawings_{DAY}.mp4")], check=True)

    scenes.append(make_scene(work, 0, "Narrator", "", "Tonight at the Token Hotel: " + ep["situation"],
                             "Narrator", make_renderer("lobby", None, None, 0), min_len=3))
    prev = None
    for i, l in enumerate(ep["lines"], start=1):
        who = l["speaker"]
        places = list(PLACE_FOR.get(who, ["lobby"]))
        if assets is not None:
            places += [p for p in EXTRA_PLACE_FOR.get(who, []) if p in assets["places"]]
        place = places[(i // 3) % len(places)]
        if assets is not None:
            place = pick_variant(assets, place, i)
        scenes.append(make_scene(work, i, who, l["role"], l["line"], who,
                                 make_renderer(place, who, prev, i)))
        prev = who
    scenes.append(make_scene(work, len(ep["lines"]) + 1, "Narrator", "",
                             "Every episode is improvised by AI agents. New stories every morning.", "Narrator",
                             make_renderer("hallway", None, None, 1), min_len=3))

    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    out_dir = ROOT / "videos"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{DAY}.mp4"
    tmp = out_dir / f"tmp_{DAY}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "24000", "-af", "aresample=async=1", str(tmp)], check=True)
    tmp.rename(out)
    print(f"Video saved: {out}. New drawings this run: {len(new_assets)}.")

# ---------------------------------------------------------------- dollhouse test
DOLLHOUSE_PROMPTS = {
    "dollhouse_a": (
        f"{STYLE}. Vertical 9:16 composition. A cutaway cross-section of a tall vintage hotel seen straight from the front, "
        "like a dollhouse with the front wall removed. Exactly three floors stacked, each the same height, each a wide open room "
        "with a flat floor line along its bottom edge. Top floor: a long hallway with red carpet, many doors and one glowing door "
        "numbered 404. Middle floor: a cozy bar with glowing bottles, brass taps and empty stools. Ground floor: a grand lobby "
        "with a reception desk and brass lamps. Thin wall dividers between floors, warm golden light, small cozy details. "
        "No people, no characters, no text except the door number."),
    "dollhouse_c": (
        f"{STYLE}. Vertical 9:16 composition. A top-down view of a vintage hotel seen from directly above with the roof "
        "removed, like a doll house. Inside: a grand lobby with a checkered marble floor and a reception desk, a cozy bar "
        "with round tables and stools, a long red-carpet hallway with many doors, a small elevator. Along one side a large "
        "wooden terrace with cafe tables, striped umbrellas, string lights and potted plants. Around the whole hotel a "
        "lively garden: many round green trees seen from above, trimmed hedges, flower beds, a small fountain, gravel paths "
        "and a lawn. Warm light, tiny cozy details. No people, no characters, no text."),
}
DOLLHOUSE_TEXT = [
    "Welcome to the Token Hotel. Zero humans. Plenty of robots.",
    "In the bar, Vex is polishing the same glass again.",
    "In the lobby, Pierce is apologizing to a lamp.",
    "And somewhere upstairs, room 404 is waiting.",
]


def find_floor_bands(img):
    """Floors of the cutaway as (top, bottom) pixel rows, found from the dark dividing bars."""
    g = img.convert("L").crop((int(img.width * 0.15), 0, int(img.width * 0.85), img.height))
    g = g.point(lambda v: 255 if v < 45 else 0).resize((1, img.height), Image.BOX)
    rows = [i for i, v in enumerate(g.getdata()) if v > 0.85 * 255]
    bars, s0, p0 = [], None, None
    for r in rows:
        if s0 is None:
            s0 = p0 = r
        elif r - p0 <= 3:
            p0 = r
        else:
            bars.append((s0, p0)); s0 = p0 = r
    if s0 is not None:
        bars.append((s0, p0))
    bars = [x for x in bars if x[1] - x[0] >= 6 and 0.08 * img.height < x[0] < 0.97 * img.height]
    bands, prev = [], 0
    for b0, b1 in bars:
        if b0 - prev > 0.08 * img.height:
            bands.append((prev, b0))
        prev = b1
    if len(bands) < 3:  # detection failed: three equal floors
        t = img.height // 3
        bands = [(0, t), (t, 2 * t), (2 * t, img.height)]
    return bands


def ease(k):
    k = min(1.0, max(0.0, k))
    return k * k * k * (k * (k * 6 - 15) + 10)  # smootherstep: gentle start and stop


def dollhouse_cam(t, path):
    if t <= path[0][0]:
        return path[0][1:]
    for a, b in zip(path, path[1:]):
        if t <= b[0]:
            k = ease((t - a[0]) / (b[0] - a[0]))
            return tuple(a[j] + (b[j] - a[j]) * k for j in (1, 2, 3))
    return path[-1][1:]


def main_dollhouse():
    global MAX_IMAGES, FPS
    MAX_IMAGES = max(MAX_IMAGES, 6)
    FPS = 30  # smooth camera moves
    work = ROOT / "build" / f"dollhouse_{DAY}"
    work.mkdir(parents=True, exist_ok=True)
    make_assets()
    d = ROOT / "assets"
    (d / "places").mkdir(exist_ok=True)
    for name, prompt in DOLLHOUSE_PROMPTS.items():
        gen_image(prompt, d / "places" / f"{name}.png")
    assets = load_assets()
    pa = d / "places" / "dollhouse_a.png"
    if assets is None or not pa.exists():
        sys.exit("Staff drawings or the dollhouse drawing are missing; cannot make the test.")
    (ROOT / "videos").mkdir(exist_ok=True)
    for name in DOLLHOUSE_PROMPTS:
        src = d / "places" / f"{name}.png"
        if src.exists():
            shutil.copy(src, ROOT / "videos" / f"{name}.png")
    im = Image.open(pa).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * scale + 0.5), int(im.height * scale + 0.5)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    bg = im.crop((left, top, left + W, top + H)).convert("RGBA")
    bands = find_floor_bands(bg)
    print("Floor bands:", bands)
    hall, bar, lobby = bands[0], bands[-2], bands[-1]
    Z = 1.8
    h0 = H / Z

    def cam_y(band):  # put the floor in the upper-middle, above the caption bar
        return ((band[0] + band[1]) / 2 + 0.15 * h0) / H

    path = [(0, 1.0, 0.5, 0.5), (2.2, Z, 0.5, cam_y(lobby)),
            (5.0, Z, 0.58, cam_y(bar)), (8.0, Z, 0.58, cam_y(bar)),
            (11.0, Z, 0.42, cam_y(lobby)), (14.0, Z, 0.42, cam_y(lobby)),
            (17.0, Z, 0.5, cam_y(hall)), (20.0, Z, 0.5, cam_y(hall)),
            (22.5, 1.0, 0.5, 0.5)]
    cast = [("Vex", bar, 0.70, 0.62), ("Pierce", lobby, 0.30, 0.46), ("Madame Halloran", lobby, 0.80, 0.80)]
    seg = 5.6
    scenes = []
    for k, text in enumerate(DOLLHOUSE_TEXT):
        def renderer(i, n, level, blink, k=k):
            t = k * seg + i / FPS
            frame = bg.copy()
            for who, band, x0, x1 in cast:
                bh = band[1] - band[0]
                fy = band[1] - 0.10 * bh
                kk = min(1.0, t / 22.0)
                cx = (x0 + (x1 - x0) * kk) * W
                canvas, pad_h, sp_w = sprite(assets, who, "blink" if blink else "base", 0.72 * bh / HEIGHT)
                bob = 3 * math.sin(2 * math.pi * (t * 0.8 + x0))
                sh = shadow(sp_w)
                frame.alpha_composite(sh, (int(cx - sh.width / 2), int(fy - sh.height / 2 - 4)))
                frame.alpha_composite(canvas, (int(cx - canvas.width / 2), int(fy - canvas.height + bob)))
            z, cxs, cys = dollhouse_cam(t, path)
            w0, h1 = W / z, H / z
            cx = min(max(cxs * W, w0 / 2), W - w0 / 2)
            cy = min(max(cys * H, h1 / 2), H - h1 / 2)
            frame = frame.resize((W, H), Image.BICUBIC, box=(cx - w0 / 2, cy - h1 / 2, cx + w0 / 2, cy + h1 / 2))
            return Image.alpha_composite(frame, vignette())
        scenes.append(make_scene(work, k, "Narrator", "", text, None, renderer, min_len=seg - 0.5))
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    out = ROOT / "videos" / f"dollhouse_{DAY}.mp4"
    tmp = ROOT / "videos" / f"tmp_dollhouse_{DAY}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "24000", str(tmp)], check=True)
    tmp.rename(out)
    print(f"Dollhouse test saved: {out}. New drawings this run: {len(new_assets)}.")



# ---------------------------------------------------------------- dollhouse episode
def cover_crop(path):
    im = Image.open(path).convert("RGB")
    sc = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * sc + 0.5), int(im.height * sc + 0.5)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((left, top, left + W, top + H)).convert("RGBA")


def crop_view(frame, z, cxs, cys):
    w0, h1 = W / z, H / z
    cx = min(max(cxs * W, w0 / 2), W - w0 / 2)
    cy = min(max(cys * H, h1 / 2), H - h1 / 2)
    return frame.resize((W, H), Image.BICUBIC, box=(cx - w0 / 2, cy - h1 / 2, cx + w0 / 2, cy + h1 / 2))


def main_dollhouse_episode():
    """The day's episode filmed in the dollhouse: one hotel drawing, the camera glides between floors."""
    global MAX_IMAGES, FPS
    MAX_IMAGES = max(MAX_IMAGES, 6)
    FPS = 30
    work = ROOT / "build" / f"dhep_{DAY}"
    work.mkdir(parents=True, exist_ok=True)
    make_assets()
    d = ROOT / "assets"
    for name, prompt in DOLLHOUSE_PROMPTS.items():
        gen_image(prompt, d / "places" / f"{name}.png")
    assets = load_assets()
    pa, pc = d / "places" / "dollhouse_a.png", d / "places" / "dollhouse_c.png"
    if assets is None or not pa.exists():
        print("Dollhouse drawing missing: making the normal video instead.", file=sys.stderr)
        return main()
    for g in GUESTS:
        states = load_robot(d, g)
        if states is not None:
            assets["robots"][g] = states
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))
    bg0 = cover_crop(pa)
    top = cover_crop(pc) if pc.exists() else None
    bands = find_floor_bands(bg0)
    # the building ends at the lobby floor bar; below it a dark stone base gives the camera room
    hall, bar, lobby = bands[0], bands[-2], bands[-1]
    Z = 1.8
    h0 = H / Z
    TP = int(0.16 * H)  # dark roof space above, so the top floor can sit in the middle of the screen
    bands = [(a0 + TP, b0 + TP) for a0, b0 in bands]
    hall, bar, lobby = bands[0], bands[-2], bands[-1]
    cut = min(H, lobby[1] - TP + 24)
    CH = int(max(TP + H, (lobby[0] + lobby[1]) / 2 + 0.05 * h0 + h0 / 2) + 4)
    bg = Image.new("RGBA", (W, CH), (26, 18, 13, 255))
    bg.paste(bg0.crop((0, 0, W, cut)), (0, TP))
    ImageDraw.Draw(bg).rectangle((0, TP + cut, W, TP + cut + 5), fill=(70, 48, 30, 255))

    def view(frame, z, cxs, cy):
        w0, h1 = W / z, H / z
        cx = min(max(cxs * W, w0 / 2), W - w0 / 2)
        cy = min(max(cy, h1 / 2), CH - h1 / 2)
        return frame.resize((W, H), Image.BICUBIC, box=(cx - w0 / 2, cy - h1 / 2, cx + w0 / 2, cy + h1 / 2))
    print("Floor bands:", bands)
    floors = {"hall": hall, "bar": bar, "lobby": lobby}

    def cam_y(band):
        lift = 0.05 if band is lobby else 0.15  # the lobby sits low in the picture, so frame it a bit higher
        return (band[0] + band[1]) / 2 + lift * h0

    guest = ep.get("guest")
    homes = {"Pierce": ("lobby", 0.30), "Madame Halloran": ("lobby", 0.78), "Vex": ("bar", 0.68)}
    if guest in assets["robots"]:
        homes[guest] = ("lobby", 0.54)
    lines = ep["lines"]
    # where each character stands at each scene (index 1..n); Pierce walks to the hallway when he says so
    state = dict(homes)
    poses = []
    for l in lines:
        who, txt = l["speaker"], l["line"].lower()
        if who == "Pierce" and "hallway" in txt:
            state["Pierce"] = ("hall", 0.20)
        if who == "Madame Halloran" and ("key" in txt or "door" in txt):
            state["Madame Halloran"] = ("hall", 0.68)
            if guest in state:
                state[guest] = ("hall", 0.42)
        if who == guest and "bar" in txt and guest in state:
            state[guest] = ("bar", 0.40)
        if who not in state:
            state[who] = ("lobby", 0.5)
        poses.append(dict(state))

    def target(pose, speaker):
        fl, x = pose.get(speaker, ("lobby", 0.5))
        return (Z, min(max(x, 0.30), 0.70), cam_y(floors[fl]))

    def draw_cast(frame, pose, speaker, level, blink, t):
        for who, (fl, x) in pose.items():
            if who not in assets["robots"]:
                continue
            band = floors[fl]
            bh = band[1] - band[0]
            fy = band[1] - (0.02 if fl == "hall" else 0.10) * bh
            speaking = who == speaker
            face = "talk" if (speaking and level > 0) else ("blink" if blink else "base")
            canvas, pad_h, sp_w = sprite(assets, who, face, 0.72 * bh / HEIGHT)
            bob = 3 * math.sin(2 * math.pi * (t * 0.8 + x)) + (-4 * level if speaking else 0)
            cx = x * W
            sh = shadow(sp_w)
            frame.alpha_composite(sh, (int(cx - sh.width / 2), int(fy - sh.height / 2 - 4)))
            frame.alpha_composite(canvas, (int(cx - canvas.width / 2), int(fy - canvas.height + bob)))

    scenes = []
    # opening: from above, slowly in toward the terrace, then the camera drops into the hotel
    first_pose = poses[0] if poses else homes

    def open_render(i, n, level, blink):
        k = ease(i / max(1, n - 1))
        if top is not None:
            return Image.alpha_composite(crop_view(top, 1.0 + 0.55 * k, 0.5 - 0.22 * k, 0.5 + 0.0 * k), vignette())
        frame = bg.copy()
        draw_cast(frame, first_pose, None, 0, blink, i / FPS)
        return Image.alpha_composite(view(frame, 1.0 + 0.8 * k, 0.5, (TP + H / 2) + 0.2 * k * H), vignette())

    scenes.append(make_scene(work, 0, "Narrator", "", "Tonight at the Token Hotel: " + ep["situation"],
                             "Narrator", open_render, min_len=4))
    prev_target = (1.0, 0.5, (TP + H / 2))
    for idx, l in enumerate(lines, start=1):
        who = l["speaker"]
        pose = poses[idx - 1]
        tgt = target(pose, who)
        start = prev_target
        if idx == 1:
            start = (1.15, 0.5, (TP + H / 2))

        def renderer(i, n, level, blink, start=start, tgt=tgt, pose=pose, who=who):
            t = i / FPS
            glide = min(1.1, 0.4 * n / FPS)
            k = ease(t / glide) if glide > 0 else 1.0
            drift = 1.0 + 0.03 * (t / max(0.1, n / FPS))
            cam = tuple(start[j] + (tgt[j] - start[j]) * k for j in range(3))
            frame = bg.copy()
            draw_cast(frame, pose, who, level, blink, t)
            return Image.alpha_composite(view(frame, cam[0] * (drift if k >= 1 else 1.0), cam[1], cam[2]), vignette())

        scenes.append(make_scene(work, idx, who, l["role"], l["line"], who, renderer))
        prev_target = tgt

    last_pose = poses[-1] if poses else homes

    def end_render(i, n, level, blink):
        k = ease(i / max(1, n - 1))
        z0, x0, y0 = prev_target
        frame = bg.copy()
        draw_cast(frame, last_pose, None, 0, blink, i / FPS)
        return Image.alpha_composite(view(frame, z0 + (1.0 - z0) * k, x0 + (0.5 - x0) * k, y0 + ((TP + H / 2) - y0) * k), vignette())

    scenes.append(make_scene(work, len(lines) + 1, "Narrator", "",
                             "Every episode is improvised by AI agents. New stories every morning.", "Narrator",
                             end_render, min_len=3))
    (ROOT / "videos").mkdir(exist_ok=True)
    for name in ("dollhouse_a", "dollhouse_c"):
        src = d / "places" / f"{name}.png"
        if src.exists():
            shutil.copy(src, ROOT / "videos" / f"{name}.png")
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    out = ROOT / "videos" / f"dollhouse_ep_{DAY}.mp4"
    tmp = ROOT / "videos" / f"tmp_dollhouse_ep_{DAY}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "24000", "-af", "aresample=async=1", str(tmp)], check=True)
    tmp.rename(out)
    shutil.copy(out, ROOT / "videos" / f"{DAY}.mp4")  # the name the daily workflow sends to Telegram
    print(f"Dollhouse episode saved: {out}. New drawings this run: {len(new_assets)}.")



if __name__ == "__main__":
    if os.environ.get("ANGLES") == "1":
        main_angles()
    elif os.environ.get("INTRO") == "1":
        main_intro()
    elif os.environ.get("DOLLHOUSE") == "1":
        main_dollhouse()
    elif os.environ.get("DOLLHOUSE_EP") == "1":
        main_dollhouse_episode()
    else:
        main()
