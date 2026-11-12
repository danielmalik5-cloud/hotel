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
    "Mr. Loop": ("a polite, old-fashioned gentleman robot guest: tall slim body of polished silver and teal metal, "
                 "round head with a glowing LED face with kind but slightly glazed eyes, a spinning circular arrow symbol on his chest, "
                 "teal three-piece suit with a pocket watch chain, a small suitcase in one hand"),
    "Ms. Context": ("a dreamy, scatterbrained humanoid robot lady guest: orange and cream metal body, "
                    "oval head with a glowing LED face with wide confused eyes, a large floppy sun hat with a small sticky note on it, "
                    "yellow travel coat, holding a travel bag, a tiny question mark floating near her head"),
}
STATES = {
    "base": "Neutral expression, mouth closed, eyes open.",
    "talk": "Change ONLY the mouth: wide open as if speaking. Keep everything else pixel-identical.",
    "blink": "Change ONLY the eyes: closed, as in a blink. Keep everything else pixel-identical.",
}
PLACE_FOR = {"Pierce": ["lobby", "hallway"], "Vex": ["bar"], "Madame Halloran": ["reception", "elevator"]}
HEIGHT = 1000  # standard sprite height in pixels
_images_made = 0
new_assets = []


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
    slug = name.replace(" ", "_")
    base = d / "robots" / f"{slug}_base.png"
    gen_image(f"{STYLE}. Full body character, standing, facing the viewer, centered, whole body visible from "
              f"head to feet, on a solid pure bright green (#00FF00) background with nothing else. "
              f"Character: {desc}. {STATES['base']}", base)
    if base.exists():
        for state in ("talk", "blink"):
            gen_image(f"Edit this image of the same character. {STATES[state]} Same green background, "
                      "same size and position.", d / "robots" / f"{slug}_{state}.png", reference=base)


def make_guest_assets():
    d = assets_dir()
    for name, desc in GUESTS.items():
        make_robot_images(d, name, desc)


def key_out_green(im):
    """Remove the (greenish, maybe textured or shaded) background around a character.

    The model does not always paint pure green, so this finds greenish pixels that are
    connected to the picture's border and makes only those transparent. Green parts
    inside the character (a bow tie, say) stay. Then it trims to the character."""
    full = im.convert("RGB")
    w, h = full.size
    small = full.resize((max(1, w // 2), max(1, h // 2)), Image.BILINEAR)
    small = small.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(1.5))
    r, g, b = small.split()
    greenness = ImageChops.subtract(g, ImageChops.lighter(r, b))
    mask = greenness.point(lambda v: 255 if v >= 8 else 0)
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
    slug = name.replace(" ", "_")
    states = {}
    base_h = None
    for st in STATES:
        p = d / "robots" / f"{slug}_{st}.png"
        if not p.exists():
            return None
        sp = key_out_green(Image.open(p))
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
    for name in ROBOTS:
        states = load_robot(d, name)
        if states is None:
            return None
        robots[name] = states
    return {"places": places, "places_blur": places_blur, "robots": robots}


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
                    "-c", "copy", str(tmp)], check=True)
    tmp.rename(out)
    print(f"Intro saved: {out}. New drawings this run: {len(new_assets)}.")


def main():
    work = ROOT / "build" / DAY
    work.mkdir(parents=True, exist_ok=True)
    make_assets()
    assets = load_assets()
    if assets is None:
        print("Drawn assets are not complete; using the simple code-drawn characters.", file=sys.stderr)
        ensure_renderer()
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))

    sides, prev_cast = {}, set()

    def make_renderer(place, speaker, prev, idx):
        nonlocal prev_cast
        if assets is None:
            return lambda i, n, level, blink: base_frame(work, speaker, level, blink)
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
        places = PLACE_FOR.get(who, ["lobby"])
        place = places[(i // 3) % len(places)]
        scenes.append(make_scene(work, i, who, l["role"], l["line"], who,
                                 make_renderer(place, who, prev, i)))
        prev = who
    scenes.append(make_scene(work, len(ep["lines"]) + 1, "Narrator", "",
                             "Every line was written by an AI agent. New episode every day.", "Narrator",
                             make_renderer("hallway", None, None, 1), min_len=3))

    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    out_dir = ROOT / "videos"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{DAY}.mp4"
    tmp = out_dir / f"tmp_{DAY}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(tmp)], check=True)
    tmp.rename(out)
    print(f"Video saved: {out}. New drawings this run: {len(new_assets)}.")


if __name__ == "__main__":
    main_intro() if os.environ.get("INTRO") == "1" else main()
