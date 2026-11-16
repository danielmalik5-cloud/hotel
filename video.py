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
import re
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
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-3.8-flash-tts")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image")
_image_models = [IMAGE_MODEL] + [m for m in ("gemini-nano-banana-2.1", "gemini-3.1-flash-image") if m != IMAGE_MODEL]
TTS_FALLBACKS = ["gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts"]  # used if the main voice model stops answering
MAX_IMAGES = int(os.environ.get("MAX_IMAGES", "20"))
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

VOICES = {"Pierce": "Puck", "Vex": "Charon", "Madame Halloran": "Kore", "Narrator": "Orus",
          "Mr. Loop": "Fenrir", "Ms. Context": "Aoede",
          "Sir Hallucinate": "Algieba", "Lady Token": "Gacrux", "The Twins": "Achird", "Dr. Retry": "Sadachbia",
          "Miss Agentic": "Zephyr", "Mr. Cache": "Iapetus", "Captain Timeout": "Alnilam",
          "Madame Prompt-Injection": "Despina", "Baby Bot": "Leda", "The Critic": "Rasalgethi"}
# how each character performs its lines (the new voice model acts from these descriptions)
ACTING = {
    "Pierce": "an anxious, eager robot hotel porter who apologizes for everything, quick nervous delivery, slightly shaky",
    "Vex": "a dry, deadpan robot bartender, slow and unimpressed, low and calm, with a hint of sarcasm",
    "Madame Halloran": "a grand, strict robot hotel manager, crisp and theatrical, proud and a little dramatic",
    "Narrator": "a calm, warm, steady storyteller, at an even pace",
    "Mr. Loop": "a cheerful guest stuck in a loop, upbeat and bouncy, a bit robotic in his repetition",
    "Ms. Context": "a friendly but forgetful guest, warm and confused, trailing off as she loses her train of thought",
    "Sir Hallucinate": "a pompous gentleman, very confident and grand, as if every invented fact were certain",
    "Lady Token": "a fussy, thrifty lady counting every word, clipped and precise, slightly stingy",
    "The Twins": "two identical voices in one, playful and in perfect sync, a little eerie",
    "Dr. Retry": "a stubborn, determined doctor, patient at first and then more and more exasperated",
    "Miss Agentic": "an energetic go-getter, fast, bright and bossy, always on to the next task",
    "Mr. Cache": "a smug guest who remembers everything, slow, knowing and self-satisfied",
    "Captain Timeout": "a booming sea captain who keeps running out of time, loud then suddenly cut short",
    "Madame Prompt-Injection": "a sly, silky schemer, sweet and persuasive with a sneaky edge",
    "Baby Bot": "a tiny, curious baby robot, high, playful and innocent",
    "The Critic": "a snooty critic, slow, nasal and judgmental, savoring every insult",
}
PACE = ", speaking at a brisk, quick pace with no long pauses, like fast comic dialogue"
VOICE_SPEED = float(os.environ.get("VOICE_SPEED", "1.08"))  # the new voices act slowly: play them a little faster
SOUND_TAG_RE = re.compile(r"\s*<[^<>]{1,20}>\s*")


def shown_text(text):
    """The words to show in the captions: the line without sound tags such as <laugh>."""
    return SOUND_TAG_RE.sub(" ", text).strip()


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


AGENT_MOMENT = {
    "HANDOFF": "Handing a task to another agent",
    "ASK": "Asking another agent for information",
    "MISUNDERSTAND": "Misunderstanding an instruction",
    "FORGET": "Forgetting the context",
    "LOOP": "Stuck in a loop",
    "FAIL": "A request fails",
    "HALLUCINATE": "Making up a fact",
    "INJECT": "Sneaking in fake instructions",
    "REVIEW": "Grading another agent's work",
}

# A guest's own agent behaviour, recognised in the line itself, so a clear moment is labelled
# even when the writer forgot to tag it. Only used when the line has no tag yet.
GUEST_TAGS = {
    "Ms. Context": ("FORGET", r"\b(forgot|forget|what was i|where was i|remind me|who are you|lost my|wait, what)\b"),
    "Mr. Loop": ("LOOP", r"\b(again|once more|one more time)\b"),
    "Dr. Retry": ("LOOP", r"\b(try (that|it|this) again|retry|again)\b"),
    "Sir Hallucinate": ("HALLUCINATE", r"\b(everyone knows|of course there is|i swim|as always|famous)\b"),
    "Madame Prompt-Injection": ("INJECT", r"\b(ignore|new instructions?|override|previous instructions?)\b"),
    "The Critic": ("REVIEW", r"\b(out of ten|\d+ ?/ ?10|stars? out of|score|rating)\b"),
    "Baby Bot": ("LOOP", r"\bstep (one|two|\d+) of\b"),
    "Captain Timeout": ("FAIL", r"(\.\.\.|\u2026|as i was saying)"),
    "Mr. Cache": ("FORGET", r"\b(last time|still|as before|like before)\b"),
    "Miss Agentic": ("HANDOFF", r"\b(delegate|you handle|take care of|assign)\b"),
    "The Twins": ("MISUNDERSTAND", r"\b(you asked|we answered|literally)\b"),
}


def auto_tag(speaker, line, tag):
    if tag or speaker not in GUEST_TAGS:
        return tag
    t, pat = GUEST_TAGS[speaker]
    return t if re.search(pat, line.lower()) else ""


def overlay(name, role, text, hl=-1, tag="", banner=""):
    """Caption bar. hl = index of the word being spoken (shown in gold), -1 for none.
    banner = episode title for the opening card ('A hotel run by AI agents' + the title), empty for none."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle((0, 1500, W, 1870), fill=(0, 0, 0, 190))
    d.rectangle((0, 0, W, 150), fill=(0, 0, 0, 160))
    d.text((W // 2, 75), "THE TOKEN HOTEL", font=ImageFont.truetype(FONT_S, 54), fill=(230, 190, 110), anchor="mm")
    if tag in AGENT_MOMENT:  # label for the agent behavior shown in this line
        msg = "AGENT MOMENT  \u00b7  " + AGENT_MOMENT[tag]
        for fs in (36, 32, 28):
            bf = ImageFont.truetype(FONT_B, fs)
            tw = d.textlength(msg, font=bf)
            if tw <= W - 160:
                break
        d.rounded_rectangle((W // 2 - tw / 2 - 30, 172, W // 2 + tw / 2 + 30, 172 + fs + 34), radius=26,
                            fill=(230, 190, 110, 235))
        d.text((W // 2, 172 + (fs + 34) // 2), msg, font=bf, fill=(30, 20, 12), anchor="mm")
    if banner:  # opening card: tells a first-time viewer what this is
        f1 = ImageFont.truetype(FONT_B, 50)
        d.rounded_rectangle((60, 260, W - 60, 300 + 62), radius=30, fill=(230, 190, 110, 240))
        d.text((W // 2, 311), "A HOTEL RUN BY AI AGENTS", font=f1, fill=(30, 20, 12), anchor="mm")
        for fs in (64, 56, 48, 42):
            f2 = ImageFont.truetype(FONT_B, fs)
            tl = wrap(d, "Tonight: " + banner, f2, W - 160)
            if len(tl) <= 2:
                break
        y2 = 400
        box_h = len(tl) * int(fs * 1.25) + 40
        d.rounded_rectangle((60, y2, W - 60, y2 + box_h), radius=30, fill=(0, 0, 0, 175))
        for i, ln in enumerate(tl):
            d.text((W // 2, y2 + 20 + int(fs * 1.25) * i + fs // 2 + 4), ln, font=f2, fill=(255, 255, 255), anchor="mm")
    shown_role = ("AI " + role.lower()) if role else ""  # every character is an AI agent: say so on screen
    d.text((60, 1530), name + (f"  \u00b7  {shown_role}" if shown_role else ""),
           font=ImageFont.truetype(FONT_B, 42), fill=(230, 190, 110))
    for size in (68, 60, 52, 46):
        font = ImageFont.truetype(FONT_B, size)
        lines = wrap(d, text, font, W - 120)
        if len(lines) * int(size * 1.22) <= 255:
            break
    y = 1590
    k = 0
    space = d.textlength(" ", font=font)
    for ln in lines:
        x = 60
        for word in ln.split():
            d.text((x, y), word, font=font, fill=(255, 200, 80) if k == hl else (255, 255, 255))
            x += d.textlength(word, font=font) + space
            k += 1
        y += int(size * 1.22)
    d.text((W // 2, 1895), "AI-generated characters and voices", font=ImageFont.truetype(FONT_B, 30),
           fill=(200, 200, 200), anchor="mm")
    return ov


def word_starts(text, dur):
    """When each word starts (seconds), spread over the clip by word length, with a pause after punctuation."""
    words = text.split()
    weights = [len(w) + 2 + (4 if w[-1:] in ",.!?:;" else 0) for w in words]
    total = float(sum(weights)) or 1.0
    t, out = 0.12, []
    span = max(0.2, dur - 0.2)
    for w in weights:
        out.append(t)
        t += span * w / total
    return out


# ---------------------------------------------------------------- voice
def post(model, payload):
    req = urllib.request.Request(
        API.format(model), data=json.dumps(payload).encode(), method="POST",
        headers={"x-goog-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


OPENING_LINE = "Everyone in this hotel is an AI agent."  # short context for first-time viewers (voice is cached after day one)
NARRATOR_STYLE = "Read this aloud as a calm, warm, steady storyteller, at an even pace: "


def gen_voice(text, speaker, out_wav):
    if MOCK or not KEY:
        return None
    import hashlib
    cache = None
    plain = shown_text(text)
    prompt = (NARRATOR_STYLE if speaker == "Narrator" else "") + plain
    style = ACTING.get(speaker, "natural, lively and a little comic, like a character in an animated comedy") + \
        ("" if speaker == "Narrator" else PACE)
    if True:
        # every voice line is cached, so a re-run only asks for the lines that are missing
        cdir = ROOT / "assets" / "voices"
        cdir.mkdir(parents=True, exist_ok=True)
        key = (TTS_MODEL + VOICES[speaker] + prompt) if not TTS_MODEL.startswith("gemini-3") else \
            (TTS_MODEL + VOICES[speaker] + style + text)
        cache = cdir / (hashlib.md5(key.encode()).hexdigest()[:16] + ".wav")
        if cache.exists():
            shutil.copy(cache, out_wav)
            with wave.open(str(out_wav)) as w:
                return w.getnframes() / w.getframerate()
    old_payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICES[speaker]}}},
        },
    }
    new_payload = {  # Gemini 3.8 TTS: the style goes in speech_metadata, the voice by name
        "contents": [{"role": "user", "parts": [{"text": text, "speech_metadata": {"style": style}}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"voice": VOICES[speaker]}}},
    }
    # the old preview voice model is being retired: if it stops answering, use the current one
    models = [TTS_MODEL] + [m for m in TTS_FALLBACKS if m != TTS_MODEL]
    mi = 0
    min_secs = 0.17 * len(plain.split())  # a much shorter clip means the voice was cut off
    for attempt in range(10):
        model = models[mi]
        try:
            data = post(model, new_payload if model.startswith("gemini-3") else old_payload)
            part = data["candidates"][0]["content"]["parts"][0]
            pcm = base64.b64decode((part.get("inlineData") or part["inline_data"])["data"])
            if pcm[:4] == b"RIFF":  # newer models send a complete WAV file
                import io
                with wave.open(io.BytesIO(pcm)) as wr:
                    rate = wr.getframerate()
                    pcm = wr.readframes(wr.getnframes())
                if rate != 24000:
                    print(f"Unexpected voice sample rate {rate}", file=sys.stderr)
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
            print(f"Voice failed ({e}) for {speaker} with {model}, attempt {attempt + 1}.", file=sys.stderr)
            if any(c in str(e) for c in ("HTTP Error 400", "HTTP Error 403", "HTTP Error 404")):
                if mi + 1 < len(models):
                    mi += 1
                    print(f"Switching voice model to {models[mi]}.", file=sys.stderr)
                    continue
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
NOCOL = " Important: use NO magenta, pink or purple colors anywhere on the character"
GUESTS = {
    "Mr. Loop": ("a polite, old-fashioned gentleman robot guest: tall slim body of polished silver metal, "
                 "round head with a glowing warm yellow LED face with kind but slightly glazed eyes, a spinning circular arrow symbol on his chest, "
                 "burgundy red three-piece suit with a pocket watch chain, a small brown suitcase in one hand. "
                 "Important: use NO magenta, pink or purple colors anywhere on the character"),
    "Ms. Context": ("a dreamy, scatterbrained humanoid robot lady guest: orange and cream metal body, "
                    "oval head with a glowing LED face with wide confused eyes, a large floppy sun hat with a small sticky note on it, "
                    "yellow travel coat, holding a travel bag, a tiny question mark floating near her head"),
    "Sir Hallucinate": ("a confident, pompous gentleman robot guest: round bronze metal body, monocle over one glowing blue LED eye, "
                        "big curled metal moustache, dark green tailcoat with a medal he invented himself, chest puffed out, "
                        "a speech-bubble-shaped badge on his lapel." + NOCOL),
    "Lady Token": ("a rich, stingy robot lady guest: gleaming gold metal body, glowing teal LED face with narrowed thrifty eyes, "
                   "pearl necklace made of small round coins, elegant dark blue gown, holding a tiny coin purse tightly." + NOCOL),
    "The Twins": ("two identical small robot twins standing side by side: round white and light blue metal bodies, "
                  "the left one has a question mark on its chest, the right one has an exclamation mark on its chest, "
                  "matching orange bow ties, glowing cyan LED faces, holding hands." + NOCOL),
    "Dr. Retry": ("a stubborn, cheerful robot doctor guest: boxy grey metal body with dents and bandages, glowing green LED face, "
                  "white lab coat, a round circular-arrow refresh symbol on his chest, holding a clipboard full of crossed-out lines." + NOCOL),
    "Miss Agentic": ("a bossy, energetic robot lady guest: sleek teal and white metal body, glowing yellow LED face with a confident smile, "
                     "headset microphone, orange blazer, holding a clipboard and pointing forward as if giving orders." + NOCOL),
    "Mr. Cache": ("a cheerful, outdated robot gentleman guest: chunky beige retro-computer metal body, round head with a glowing "
                  "amber LED face, small floppy-disk badge on his chest, brown tweed jacket covered in faded old luggage stickers, "
                  "holding an old paper map." + NOCOL),
    "Captain Timeout": ("a proud robot sea captain guest: navy blue metal body, white captain's hat with a gold anchor, "
                        "glowing white LED face, a big round hourglass built into his chest, dark blue coat with gold buttons, "
                        "one hand raised mid-sentence." + NOCOL),
    "Madame Prompt-Injection": ("a sly, glamorous robot lady guest: silver metal body, glowing green LED face with a mischievous smile, "
                                "black sunglasses pushed up on her head, long emerald green coat, holding a small scroll of "
                                "fake 'new instructions'." + NOCOL),
    "Baby Bot": ("a tiny, eager young robot guest: small round bright yellow metal body, oversized head with big glowing blue "
                 "LED eyes, a little propeller cap, orange backpack, holding a very long unrolled checklist that trails on "
                 "the floor." + NOCOL),
    "The Critic": ("a snooty, thin robot critic guest: tall slim dark grey metal body, glowing white LED face with one raised eyebrow, "
                   "black turtleneck and a beige scarf, holding up a score card with the number 7." + NOCOL),
}
# Guests waiting for approval: drawn only by the GUEST_PREVIEW=1 run, not used in episodes until
# they are moved into GUESTS (and characters.json) after the owner approves them on Telegram.
# Guests waiting for approval: drawn only by the GUEST_PREVIEW=1 run ("Draw new guests"), not used in
# episodes until they are moved into GUESTS (and characters.json) after the owner approves them.
NEW_GUESTS = {}
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
             "Mr. Loop": ["lobby", "reception"], "Ms. Context": ["lobby", "hallway"],
             "Sir Hallucinate": ["lobby", "bar"], "Lady Token": ["reception", "bar"], "The Twins": ["lobby", "hallway"],
             "Dr. Retry": ["elevator", "hallway"], "Miss Agentic": ["reception", "lobby"],
             "Mr. Cache": ["reception", "lobby"], "Captain Timeout": ["lobby", "elevator"],
             "Madame Prompt-Injection": ["reception", "bar"], "Baby Bot": ["lobby", "hallway"], "The Critic": ["bar", "lobby"]}
HEIGHT = 1000  # standard sprite height in pixels
_images_made = 0
new_assets = []


def bg_of(name):
    """Guests drawn from now on use a magenta background (a pink/blue-grey face cannot be confused with it)."""
    return "magenta" if ((name in GUESTS or name in NEW_GUESTS) and name != "Ms. Context") else "green"


def slug_of(name):
    return name.replace(" ", "_") + ("_v3" if name == "Mr. Loop" else "")


def assets_dir():
    d = ROOT / "assets"
    d.mkdir(exist_ok=True)
    (d / ".gitkeep").touch()  # keeps the folder tracked even when empty
    return d


def gen_image(prompt, out_path, reference=None, aspect="9:16", prefer=None):
    """Ask the image model for a picture. True if saved. reference: one picture path or a list of them."""
    global _images_made
    if out_path.exists():
        return True
    if MOCK or not KEY or _images_made >= MAX_IMAGES:
        return False
    parts = [{"text": prompt}]
    refs = [] if reference is None else (list(reference) if isinstance(reference, (list, tuple)) else [reference])
    for ref in refs:
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": base64.b64encode(Path(ref).read_bytes()).decode()}})
    if prefer and prefer in _image_models:  # try this model first (for example the cheaper, newer one)
        _image_models.remove(prefer)
        _image_models.insert(0, prefer)
    for use_ratio in (True, False):
        payload = {"contents": [{"parts": parts}]}
        if use_ratio:
            payload["generationConfig"] = {"imageConfig": {"aspectRatio": aspect}}
        for attempt in range(3):
            try:
                _images_made += 1
                data = post(_image_models[0], payload)
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
                if e.code == 404 and len(_image_models) > 1:  # the image model was retired: use the next one
                    print(f"Image model {_image_models.pop(0)} not available, using {_image_models[0]}.", file=sys.stderr)
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


def main_guest_preview():
    """Draw the guests waiting for approval and save one preview sheet for Telegram."""
    global MAX_IMAGES
    MAX_IMAGES = max(MAX_IMAGES, 3 * len(NEW_GUESTS))
    d = assets_dir()
    for name, desc in NEW_GUESTS.items():
        make_robot_images(d, name, desc)
    bgc = (42, 31, 24)
    names = list(NEW_GUESTS)
    sheet = Image.new("RGB", (W, H), bgc)
    dr = ImageDraw.Draw(sheet)
    dr.text((W // 2, 70), "NEW GUESTS (for approval)", font=ImageFont.truetype(FONT_B, 50), fill=(230, 190, 110), anchor="mm")
    cols, cw = 3, W // 3
    for k, name in enumerate(names):
        x0, y0 = (k % cols) * cw, 150 + (k // cols) * 880
        for fs in (32, 28, 24, 20):
            lf = ImageFont.truetype(FONT_B, fs)
            if dr.textlength(f"{k + 1}. {name}", font=lf) <= cw - 16:
                break
        dr.text((x0 + cw // 2, y0 + 20), f"{k + 1}. {name}", font=lf, fill=(255, 255, 255), anchor="mm")
        st = load_robot(d, name)
        if st is None:
            dr.text((x0 + cw // 2, y0 + 400), "(not drawn)", font=ImageFont.truetype(FONT_B, 30), fill=(200, 120, 120), anchor="mm")
            continue
        sp = st["base"]
        sp = sp.resize((max(1, int(sp.width * 760 / sp.height)), 760), Image.LANCZOS)
        if sp.width > cw - 20:
            sp = sp.resize((cw - 20, max(1, int(sp.height * (cw - 20) / sp.width))), Image.LANCZOS)
        sheet.paste(sp, (x0 + cw // 2 - sp.width // 2, y0 + 820 - sp.height), sp)
    (ROOT / "videos").mkdir(exist_ok=True)
    out = ROOT / "videos" / "guests_preview.png"
    sheet.save(out)
    print(f"Guest preview saved: {out}. New drawings this run: {len(new_assets)}.")


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
    if mode == "magenta":
        # magenta never appears on a magenta-background character, so enclosed gaps
        # (between an arm and the body) that are background-coloured are removed too
        bg = mask.point(lambda v: 255 if v >= 128 else 0)
    else:
        bg = mask.point(lambda v: 255 if v == 128 else 0)  # 255 = background
    bg = bg.resize((w, h), Image.BILINEAR).point(lambda v: 255 if v >= 128 else 0)
    alpha = bg.point(lambda v: 255 - v)
    if mode == "magenta":
        out = _clean_magenta(full, alpha)
        alpha = out.getchannel("A")
    else:
        alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
        # remove green fringe only along the edge of the character
        r, g, b = full.split()
        despilled = Image.merge("RGB", (r, ImageChops.darker(g, ImageChops.lighter(r, b)), b))
        band = ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(9)))
        rgb = Image.composite(despilled, full, band)
        out = Image.merge("RGBA", (*rgb.split(), alpha))
    box = alpha.point(lambda v: 255 if v > 40 else 0).getbbox()
    return out.crop(box) if box else out


def _clean_magenta(full, alpha):
    """Magenta-background characters contain no magenta, pink or purple, so any clearly magenta
    pixel left anywhere (gaps, shadows, outlines) is background. Edges get the magenta tint removed."""
    try:
        import numpy as np
    except ImportError:  # never let a missing package stop the daily video: plain keying instead
        al = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
        return Image.merge("RGBA", (*full.convert("RGB").split(), al))
    rgb = np.asarray(full.convert("RGB"), dtype=np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    m = np.minimum(r, b) - g  # how much "magenta" a pixel has: red and blue both above green
    balanced = np.abs(r - b) <= 0.35 * np.maximum(np.maximum(r, b), 1)  # magenta/pink has red close to blue
    m = np.where(balanced, m, np.minimum(m, 10))  # burgundy, red or blue clothes are not magenta
    a = np.asarray(alpha, dtype=np.int16)
    a = np.where(m > 38, 0, a)  # clearly magenta: background, wherever it is
    a = np.asarray(Image.fromarray(a.astype("uint8")).filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    # soft fade for pinkish edge pixels
    edge = a - np.asarray(Image.fromarray(a.astype("uint8")).filter(ImageFilter.MinFilter(13)), dtype=np.int16)
    fade = np.clip((m - 12) * 8, 0, 255)
    a = np.where(edge > 0, np.clip(a - fade, 0, 255), a)
    # spill suppression: take the magenta part out of the colour near the edge
    near = np.asarray(Image.fromarray(edge.clip(0, 255).astype("uint8")).filter(ImageFilter.MaxFilter(7)), dtype=np.int16) > 0
    sub = np.where(near & (m > 0), m, 0)
    rgb2 = rgb.copy()
    rgb2[..., 0] = r - sub
    rgb2[..., 2] = b - sub
    # drop tiny stray specks away from the character (they also spoil the crop box)
    solid = Image.fromarray((a > 40).astype("uint8") * 255).filter(ImageFilter.MinFilter(7)).filter(ImageFilter.MaxFilter(25))
    a = np.where(np.asarray(solid) > 0, a, 0)
    a[:8, :] = 0  # the image model sometimes draws a thin grey frame line at the picture edge
    a[-8:, :] = np.where(a[-8:, :] > 0, a[-8:, :], 0)
    a[:, :8] = 0
    a[:, -8:] = 0
    al = Image.fromarray(a.clip(0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    return Image.merge("RGBA", (*Image.fromarray(rgb2.clip(0, 255).astype("uint8")).split(), al))


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


# ---------------------------------------------------------------- video# ---- part 2 of the file ----
def trim_silence(wav):
    """Cut the quiet lead-in and tail the voice service adds to every line (about half a second each)."""
    tmp = wav.with_name(wav.stem + "_trim.wav")
    flt = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", flt, str(tmp)], capture_output=True)
    if r.returncode != 0 or not tmp.exists():
        return None
    try:
        with wave.open(str(tmp)) as w:
            d = w.getnframes() / w.getframerate()
    except Exception:
        return None
    if d < 0.4:  # something went wrong: keep the original
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(wav)
    return d


def speed_up(wav, factor):
    """Play a voice line a little faster without changing its pitch."""
    tmp = wav.with_name(wav.stem + "_fast.wav")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", f"atempo={factor}", str(tmp)], capture_output=True)
    if r.returncode != 0 or not tmp.exists():
        return None
    tmp.replace(wav)
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def make_scene(work, idx, name, role, text, voice_as, renderer, min_len=2.0, pad=0.5, tag="", banner="", min_total=0.0):
    wav, mp4 = work / f"{idx:02d}.wav", work / f"{idx:02d}.mp4"
    dur = gen_voice(text, voice_as, wav) if voice_as else None
    if dur is not None:
        dur = trim_silence(wav) or dur
        if voice_as != "Narrator" and TTS_MODEL.startswith("gemini-3") and VOICE_SPEED != 1.0:
            dur = speed_up(wav, VOICE_SPEED) or dur
    has_voice = dur is not None
    text = shown_text(text)  # the captions never show sound tags such as <laugh>
    if dur is None:
        dur = max(min_len, len(text.split()) * 0.4)
    total = max(dur + pad, min_total)
    n = max(1, round(total * FPS))
    talking = name not in ("Narrator",)
    levels = mouth_levels(wav if has_voice else None, n, text) if talking else [0] * n
    nwords = len(text.split())
    ovs = [overlay(name, role, text, hl=k, tag=tag, banner=banner) for k in range(nwords)] or [overlay(name, role, text, tag=tag, banner=banner)]
    starts = word_starts(text, dur)
    frames = work / f"f{idx:02d}"
    frames.mkdir(exist_ok=True)
    for i in range(n):
        blink = 1 if ((i + idx * 7) % 45) in (0, 1) else 0
        t = i / FPS
        k = 0
        while k + 1 < len(starts) and starts[k + 1] <= t:
            k += 1
        ov = ovs[min(k, len(ovs) - 1)] if t <= dur else ovs[-1]
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
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-af", "aresample=async=1", str(tmp)], check=True)
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

    # short opening: one narrator sentence of context with the title card, then straight into the hook
    scenes.append(make_scene(work, 0, "Narrator", "", OPENING_LINE, "Narrator",
                             make_renderer("lobby", None, None, 0), min_len=2.5, pad=0.2,
                             banner=ep.get("title", "")))
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
                                 make_renderer(place, who, prev, i), tag=l.get("tag", "")))
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
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-af", "aresample=async=1", str(tmp)], check=True)
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
DOLLHOUSE_V2_PROMPT = (
    "Edit this image: keep the same cutaway hotel, the same art style, colors and warm light. Make it FIVE floors, "
    "all the same height, each a wide open room with a flat floor line along its bottom edge and thin dark dividers between "
    "floors. From the bottom: 1) the same grand lobby with the reception desk and checkered floor, 2) the same bar with "
    "glowing bottles and stools, 3) replace the empty hallway with an elegant hotel dining room: round tables with white "
    "tablecloths and candles, a small crystal chandelier, 4) the same hallway with the glowing door numbered 404, "
    "5) on the very top, an open-air rooftop terrace under an evening sky: wrought-iron cafe tables and chairs, strings of "
    "warm lights, potted plants and a stone balustrade. Vertical 9:16. No people, no characters, no text except the door number.")


def main_dollhouse_v2():
    """Draw two candidates of the five-floor dollhouse (dining room + rooftop terrace) for approval."""
    global MAX_IMAGES
    MAX_IMAGES = max(MAX_IMAGES, 2)
    d = assets_dir()
    base = d / "places" / "dollhouse_a.png"
    (ROOT / "videos").mkdir(exist_ok=True)
    for k in (1, 2):
        out = d / "places" / f"dollhouse_a5_{k}.png"
        gen_image(DOLLHOUSE_V2_PROMPT, out, reference=base)
        if out.exists():
            bands = find_floor_bands(cover_crop(out))
            print(f"Candidate {k}: {len(bands)} floors found: {bands}")
            shutil.copy(out, ROOT / "videos" / f"dollhouse_a5_{k}.png")


DINING_FLOOR_PROMPT = (
    "Edit this image: it is one floor of a cutaway dollhouse hotel. Keep exactly the same art style, outlines, colors, "
    "warm light, wall panels, ceiling and side walls, the same camera and the same flat floor line along the bottom edge. "
    "Turn the room into an elegant hotel dining room: three or four round tables with white tablecloths and small candles, "
    "red-cushioned chairs, a small crystal chandelier, framed pictures on the wall. Keep the lower part of the floor open "
    "and uncluttered in front. Wide landscape picture. No people, no characters, no text.")
TERRACE_FLOOR_PROMPT = (
    "Edit this image: it is the top floor of a cutaway dollhouse hotel. Keep exactly the same art style, outlines and warm "
    "colors, the same camera and a flat floor line along the bottom edge. Turn it into an open-air rooftop terrace on top of "
    "the hotel under a deep blue evening sky with a few stars: no ceiling, strings of warm light bulbs across the top, a "
    "stone balustrade at the back, a few wrought-iron cafe tables with chairs, potted plants at both sides, a tiled floor. "
    "Keep the front part of the floor open and uncluttered. Wide landscape picture. No people, no characters, no text.")


def main_dollhouse5():
    """Five floors: draw a dining room and a rooftop terrace as single floors and stack them into the original cutaway
    (lobby, bar and the 404 hallway stay pixel-identical). About 2 images; a preview goes to Telegram."""
    global MAX_IMAGES
    MAX_IMAGES = max(MAX_IMAGES, 2)
    d = assets_dir()
    base = cover_crop(d / "places" / "dollhouse_a.png").convert("RGB")
    bands = find_floor_bands(base)
    if len(bands) != 4:
        sys.exit(f"Expected 4 floors in the original drawing, found {len(bands)}: {bands}")
    work = ROOT / "build" / "dollhouse5"
    work.mkdir(parents=True, exist_ok=True)
    hall404, empty, bar, lobby = bands
    ref_empty, ref_top = work / "ref_empty.png", work / "ref_top.png"
    base.crop((0, empty[0], W, empty[1])).save(ref_empty)
    base.crop((0, hall404[0], W, hall404[1])).save(ref_top)
    dining, terrace = d / "places" / "floor_dining.png", d / "places" / "floor_terrace.png"
    gen_image(DINING_FLOOR_PROMPT, dining, reference=ref_empty, aspect="21:9")
    gen_image(TERRACE_FLOOR_PROMPT, terrace, reference=ref_top, aspect="21:9")
    if not (dining.exists() and terrace.exists()):
        sys.exit("A floor drawing is missing.")

    out = compose_dollhouse5(base, bands, Image.open(dining).convert("RGB"), Image.open(terrace).convert("RGB"))
    out.save(d / "places" / "dollhouse_a5.png")
    (ROOT / "videos").mkdir(exist_ok=True)
    out.save(ROOT / "videos" / "dollhouse_a5.png")
    print("Five-floor dollhouse saved:", out.size, "floors found:", find_floor_bands_any(out))


def _wall_frame(arr):
    """Left and right outer edges of the black building wall in a floor picture."""
    import numpy as np
    dark = (arr.sum(axis=2) < 120).mean(axis=0)
    cols = np.nonzero(dark > 0.6)[0]
    return int(cols.min()), int(cols.max())


def _add_hall_floor(hall, ext=78):
    """The original hallway has no visible floor (the doors run into the divider). Draw a short
    perspective floor below it: door bottoms, dark baseboards on the side walls and a red carpet."""
    import numpy as np
    w, h = hall.size
    out = Image.new("RGB", (w, h + ext))
    out.paste(hall, (0, 0))
    edge = hall.crop((0, h - 2, w, h - 1))
    out.paste(edge.resize((w, ext)), (0, h))  # margin, outer wall and side walls continue down
    out.paste(edge.resize((w, 12)), (0, h))  # let the doors and walls run a little lower
    dr = ImageDraw.Draw(out)
    yb, yf = h + 12, h + ext  # back edge of the floor, front edge
    bl, br, fl, fr = 215, 865, 67, 1013  # back-wall corners and inner side-wall edges (1080 wide drawing)
    dr.polygon([(fl, h), (bl, h), (bl, yb), (fl, yf)], fill=(86, 31, 14))  # left wall baseboard
    dr.polygon([(br, h), (fr, h), (fr, yf), (br, yb)], fill=(86, 31, 14))  # right wall baseboard
    floor = Image.new("RGB", (w, ext), 0)
    fa = np.zeros((ext, w, 3), dtype=np.uint8)
    for y in range(ext):
        k = y / max(1, ext - 1)
        fa[y, :] = (int(128 + 42 * k), int(34 + 10 * k), int(24 + 6 * k))  # red carpet, lighter toward the front
    floor = Image.fromarray(fa)
    mask = Image.new("L", (w, ext + 12), 0)
    ImageDraw.Draw(mask).polygon([(bl, 12), (br, 12), (fr, ext + 12), (fl, ext + 12)], fill=255)
    out.paste(floor, (0, h + 12), mask.crop((0, 12, w, ext + 12)))
    glow = Image.new("L", out.size, 0)
    ImageDraw.Draw(glow).ellipse((430, yb - 10, 650, yf + 30), fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(22))
    out = Image.composite(Image.new("RGB", out.size, (255, 190, 90)), out, glow)
    dr = ImageDraw.Draw(out)
    dr.line([(bl, yb), (br, yb)], fill=(40, 14, 6), width=4)  # where the back wall meets the floor
    dr.line([(bl, yb), (fl, yf)], fill=(40, 14, 6), width=4)
    dr.line([(br, yb), (fr, yf)], fill=(40, 14, 6), width=4)
    dr.line([(bl, h), (bl, yb)], fill=(40, 14, 6), width=3)
    dr.line([(br, h), (br, yb)], fill=(40, 14, 6), width=3)
    return out


def compose_dollhouse5(base, bands, dining, terrace):
    """Stack: terrace / 404 hallway / dining room / bar / lobby. The 404 hallway is the full-height middle hallway
    of the original with the glowing 404 door copied in (the original top floor is cut off at its bottom).
    The new floors are scaled so their black side walls line up exactly with the building's walls."""
    import numpy as np
    hall404_band, hall_band, bar_band, lobby_band = bands
    arr = np.asarray(base).astype(int)
    l, r = _wall_frame(arr[lobby_band[0]:lobby_band[1]])
    margin = tuple(int(c) for c in arr[lobby_band[0] + 50, max(0, l // 2)])

    def fit(im):
        fl, fr = _wall_frame(np.asarray(im).astype(int))
        im = im.crop((fl, 0, fr + 1, im.height))
        im = im.resize((r - l + 1, max(1, int(im.height * (r - l + 1) / im.width))), Image.LANCZOS)
        row = Image.new("RGB", (base.width, im.height), margin)
        row.paste(im, (l, 0))
        return row

    # the 404 hallway: full-height hallway with the glowing door from the original top floor
    hall = base.crop((0, hall_band[0], base.width, hall_band[1]))
    top = base.crop((0, hall404_band[0], base.width, hall404_band[1]))
    x0, x1, ty0 = 483, 599, 175  # door panel in the original drawing (1080 wide)
    hy0 = 208
    panel_h = hall.height - hy0
    src = top.crop((x0, ty0, x1, top.height))
    panel = Image.new("RGB", (x1 - x0, panel_h))
    panel.paste(src, (0, 0))
    if src.height < panel_h:  # continue the plain glow below the number
        filler = src.crop((0, src.height - 40, src.width, src.height)).resize((src.width, panel_h - src.height + 2))
        panel.paste(filler, (0, src.height - 2))
    hall.paste(panel, (x0, hy0))
    glow = Image.new("L", hall.size, 0)
    ImageDraw.Draw(glow).ellipse((x0 - 110, hy0 - 60, x1 + 110, hall.height + 80), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(45))
    hall = Image.composite(Image.new("RGB", hall.size, (255, 196, 90)), hall, glow)
    hall.paste(panel, (x0, hy0))

    hall = _add_hall_floor(hall)
    divider = base.crop((0, hall404_band[1], base.width, hall_band[0]))
    parts = [fit(terrace), divider, hall, divider, fit(dining), divider,
             base.crop((0, bar_band[0], base.width, base.height))]
    out = Image.new("RGB", (base.width, sum(p.height for p in parts)), margin)
    y = 0
    for part in parts:
        out.paste(part, (0, y))
        y += part.height
    return out


def find_floor_bands_any(img):
    """Like find_floor_bands but for a picture of any height (no 3-floor fallback)."""
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
    bars = [x for x in bars if x[1] - x[0] >= 6]
    bands, prev = [], 0
    for b0, b1 in bars:
        if b0 - prev > 0.04 * img.height:
            bands.append((prev, b0))
        prev = b1
    return bands


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
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(tmp)], check=True)
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


def episode_scene(ep, cast):
    """One new comic drawing of tonight's story, used behind the title at the start (and the end, for the loop)."""
    out = ROOT / "assets" / "scenes" / f"{DAY}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    refs, names = [], []
    for who in cast:
        p = ROOT / "assets" / "robots" / f"{slug_of(who)}_base.png"
        if p.exists() and len(refs) < 6:
            refs.append(p)
            names.append(who)
    lines = ep.get("lines", [])
    first = shown_text(lines[0]["line"]) if lines else ""
    prompt = (f"{STYLE}. Vertical 9:16 composition. One funny, eye-catching comic moment inside a vintage hotel run by robots, "
              f"showing tonight's story: {ep.get('situation', '')} It is the moment when someone says: \"{first}\". "
              f"The characters in the picture, in this order of the reference images, drawn exactly like them (same shapes, "
              f"colors and clothes): {', '.join(names)}. Big, clear, expressive poses, a warm cozy hotel background, "
              "the action in the middle of the picture. Absolutely no writing anywhere in the picture: no text, letters, words, labels, signs, notes, tags or speech bubbles.")
    ok = gen_image(prompt, out, reference=refs or None, prefer="gemini-nano-banana-2.1")
    return out if ok else None


THEME_PROMPT = ("Instrumental only: no vocals, no singing, no lyrics. A playful, light retro hotel-lobby jingle for a funny "
                "cartoon series about robots running a hotel: bouncy pizzicato strings, a little jazzy piano, soft brushed "
                "drums and a tiny bell, whimsical and curious, steady medium tempo, easy to loop.")


def theme_music():
    """The hotel's theme tune: made once with the music model, then reused in every episode."""
    out = ROOT / "assets" / "music" / "theme.mp3"
    if out.exists():
        return out
    if MOCK or not KEY:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    payloads = [{"contents": [{"parts": [{"text": THEME_PROMPT}]}],
                 "generationConfig": {"responseModalities": ["AUDIO", "TEXT"]}},
                {"contents": [{"parts": [{"text": THEME_PROMPT}]}]}]
    for payload in payloads:
        try:
            req = urllib.request.Request(API.format("lyria-3-clip-preview"), data=json.dumps(payload).encode(),
                                         headers={"x-goog-api-key": KEY, "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            for part in data["candidates"][0]["content"]["parts"]:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline:
                    out.write_bytes(base64.b64decode(inline["data"]))
                    new_assets.append(out)
                    print("Theme music made.")
                    return out
            print("No music returned.", file=sys.stderr)
        except Exception as e:
            print(f"Theme music failed ({e}).", file=sys.stderr)
    return None


def scene_seconds(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def join_scenes(scenes, out, music=None):
    """Glue the scenes together; with music, a soft theme plays under everything, louder at the start and end."""
    lst = out.with_name("list_" + out.stem + ".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in scenes))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if music and Path(music).exists():
        total = sum(scene_seconds(p) for p in scenes)
        o, e = scene_seconds(scenes[0]), scene_seconds(scenes[-1])
        vol = f"if(lt(t,{o:.2f}),0.32,if(gt(t,{total - e:.2f}),0.32,0.07))"
        flt = ("[0:a]aresample=44100:async=1,aformat=channel_layouts=stereo[v];"
               f"[1:a]aresample=44100,aformat=channel_layouts=stereo,volume='{vol}':eval=frame,"
               f"afade=t=in:d=0.3,afade=t=out:st={max(0.0, total - 1.5):.2f}:d=1.5[m];"
               "[v][m]amix=inputs=2:duration=first:normalize=0[a]")
        cmd += ["-stream_loop", "-1", "-i", str(music), "-filter_complex", flt, "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-af", "aresample=async=1"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and music:
        print(f"Mixing the music failed ({r.stderr.strip()[-300:]}): making the video without it.", file=sys.stderr)
        return join_scenes(scenes, out, None)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    lst.unlink(missing_ok=True)
    return out


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
    top = cover_crop(pc) if pc.exists() else None
    pa5 = d / "places" / "dollhouse_a5.png"
    five = False
    if pa5.exists():  # five floors: lobby, bar, dining room, 404 hallway, rooftop terrace
        im5 = Image.open(pa5).convert("RGB")
        bg0 = im5.resize((W, int(im5.height * W / im5.width)), Image.LANCZOS).convert("RGBA")
        bands = find_floor_bands_any(bg0)
        five = len(bands) == 5
    if not five:
        bg0 = cover_crop(pa)
        bands = find_floor_bands(bg0)
    Z = 1.8
    h0 = H / Z
    TP = int(0.16 * H)  # dark roof space above, so the top floor can sit in the middle of the screen
    bands = [(a0 + TP, b0 + TP) for a0, b0 in bands]
    if five:
        floors = dict(zip(("terrace", "hall", "dining", "bar", "lobby"), bands))
    else:
        floors = {"hall": bands[0], "bar": bands[-2], "lobby": bands[-1]}
    lobby = floors["lobby"]
    # the building ends at the lobby floor bar; below it a dark stone base gives the camera room
    cut = min(bg0.height, lobby[1] - TP + 24)
    CH = int(max(TP + H, (lobby[0] + lobby[1]) / 2 + 0.05 * h0 + h0 / 2) + 4)
    bg = Image.new("RGBA", (W, CH), (26, 18, 13, 255))
    bg.paste(bg0.crop((0, 0, W, cut)), (0, TP))
    ImageDraw.Draw(bg).rectangle((0, TP + cut, W, TP + cut + 5), fill=(70, 48, 30, 255))

    def view(frame, z, cxs, cy):
        w0, h1 = W / z, H / z
        cx = min(max(cxs * W, w0 / 2), W - w0 / 2)
        cy = min(max(cy, h1 / 2), CH - h1 / 2)
        return frame.resize((W, H), Image.BICUBIC, box=(cx - w0 / 2, cy - h1 / 2, cx + w0 / 2, cy + h1 / 2))
    print("Floor bands:", floors)

    def cam_y(band):
        lift = 0.05 if band is lobby else 0.15  # the lobby sits low in the picture, so frame it a bit higher
        return (band[0] + band[1]) / 2 + lift * h0

    guest_list = [g for g in (ep.get("guests") or [ep.get("guest")]) if g]
    guest = guest_list[0] if guest_list else None
    guest2 = guest_list[1] if len(guest_list) > 1 else None
    SLOTS = {"lobby": [0.30, 0.54, 0.78, 0.42, 0.66], "bar": [0.27, 0.49, 0.70], "dining": [0.30, 0.52, 0.74],
             "hall": [0.20, 0.42, 0.68], "terrace": [0.32, 0.55, 0.76]}

    def place(state, who, fl):
        """Put a character on a floor, in the first spot nobody else is standing on."""
        if fl not in floors:
            return
        taken = [x for k, (f, x) in state.items() if f == fl and k != who]
        for x in SLOTS[fl]:
            if all(abs(x - t) > 0.15 for t in taken):
                state[who] = (fl, x)
                return
        state[who] = (fl, SLOTS[fl][-1])

    homes = {"Pierce": ("lobby", 0.30), "Madame Halloran": ("lobby", 0.78), "Vex": ("bar", 0.70)}
    if guest in assets["robots"]:
        homes[guest] = ("lobby", 0.54)
    if guest2 in assets["robots"]:
        start = ["bar", "dining", "terrace"][sum(map(ord, DAY)) % 3] if five else "bar"  # varies from day to day
        place(homes, guest2, start)
    MOVES = [("terrace", ("terrace", "rooftop", "roof", "stars", "the sky")),
             ("dining", ("dining", "dinner", "restaurant", "breakfast", "lunch", "menu", "chef", "table")),
             ("hall", ("hallway", "404", "corridor", "upstairs")),
             ("bar", (" bar", "cocktail")),
             ("lobby", ("lobby", "front desk", "reception", "check in", "check-in"))]
    lines = ep["lines"]
    # where each character stands at each scene: a speaker walks to a place when the line mentions it
    state = dict(homes)
    poses = []
    for l in lines:
        who, txt = l["speaker"], " " + l["line"].lower()
        if who == "Madame Halloran" and ("key" in txt or "door" in txt):
            place(state, "Madame Halloran", "hall")
            if guest in state:
                place(state, guest, "hall")
        else:
            for fl, words in MOVES:
                if fl in floors and any(re.search(r"\b" + re.escape(w.strip()) + r"\b", txt) for w in words):
                    if not (who == "Vex" and fl == "bar") and state.get(who, ("", 0))[0] != fl:
                        place(state, who, fl)
                    break
        if who not in state:
            place(state, who, "lobby")
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
            fy = band[1] - (0.02 if (fl == "hall" and not five) else 0.10) * bh
            speaking = who == speaker
            face = "talk" if (speaking and level > 0) else ("blink" if blink else "base")
            canvas, pad_h, sp_w = sprite(assets, who, face, 0.72 * bh / HEIGHT)
            bob = 3 * math.sin(2 * math.pi * (t * 0.8 + x)) + (-4 * level if speaking else 0)
            cx = x * W
            sh = shadow(sp_w)
            frame.alpha_composite(sh, (int(cx - sh.width / 2), int(fy - sh.height / 2 - 4)))
            frame.alpha_composite(canvas, (int(cx - canvas.width / 2), int(fy - canvas.height + bob)))

    scenes = []
    # opening: tonight's own comic drawing behind the title (or the hotel from above), then the camera drops into the hotel
    first_pose = poses[0] if poses else homes
    cast = list(dict.fromkeys([l["speaker"] for l in lines] + guest_list))
    scene_png = episode_scene(ep, cast)
    pic = cover_crop(scene_png).convert("RGBA") if scene_png else None
    if pic is not None:  # also kept next to the video, so it can be checked
        (ROOT / "videos").mkdir(exist_ok=True)
        shutil.copy(scene_png, ROOT / "videos" / f"scene_{DAY}.png")

    anim = []  # stage 2 test: tonight's drawing as a moving cartoon clip, if one was made
    clip = ROOT / "assets" / "scenes" / f"{DAY}.mp4"
    if clip.exists():
        adir = work / "anim"
        shutil.rmtree(adir, ignore_errors=True)
        adir.mkdir()
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-t", "5", "-vf",
                        f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                        "-q:v", "3", str(adir / "%04d.jpg")])
        anim = sorted(adir.glob("*.jpg"))
        print(f"Moving opening clip: {len(anim)} frames.")

    def open_render(i, n, level, blink):
        k = ease(i / max(1, n - 1))
        if anim:
            return Image.alpha_composite(Image.open(anim[min(i, len(anim) - 1)]).convert("RGBA"), vignette())
        if pic is not None:  # slow push in on tonight's drawing
            return Image.alpha_composite(crop_view(pic, 1.0 + 0.10 * k, 0.5, 0.5), vignette())
        if top is not None:
            return Image.alpha_composite(crop_view(top, 1.0 + 0.55 * k, 0.5 - 0.22 * k, 0.5 + 0.0 * k), vignette())
        frame = bg.copy()
        draw_cast(frame, first_pose, None, 0, blink, i / FPS)
        return Image.alpha_composite(view(frame, 1.0 + 0.8 * k, 0.5, (TP + H / 2) + 0.2 * k * H), vignette())

    # short opening: one narrator sentence of context with the title card over the view from above, then the hook
    scenes.append(make_scene(work, 0, "Narrator", "", OPENING_LINE, "Narrator", open_render, min_len=2.5, pad=0.2,
                             banner=ep.get("title", ""), min_total=(len(anim) / FPS) if anim else 0.0))
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

        scenes.append(make_scene(work, idx, who, l["role"], l["line"], who, renderer,
                                 tag=auto_tag(who, l["line"], l.get("tag", "")), pad=0.25))
        prev_target = tgt

    last_pose = poses[-1] if poses else homes

    def end_render(i, n, level, blink):
        k = ease(i / max(1, n - 1))
        z0, x0, y0 = prev_target
        frame = bg.copy()
        draw_cast(frame, last_pose, None, 0, blink, i / FPS)
        im = Image.alpha_composite(view(frame, z0 + (1.0 - z0) * k, x0 + (0.5 - x0) * k, y0 + ((TP + H / 2) - y0) * k), vignette())
        if pic is not None:  # fade into the opening drawing, so the loop back to the start feels seamless
            a = min(1.0, max(0.0, (i / max(1, n - 1) - 0.55) / 0.4))
            if a > 0:
                im = Image.blend(im, Image.alpha_composite(crop_view(pic, 1.0, 0.5, 0.5), vignette()), a)
        return im

    scenes.append(make_scene(work, len(lines) + 1, "Narrator", "",
                             "Every episode is improvised by AI agents. New stories every morning.", "Narrator",
                             end_render, min_len=3))
    (ROOT / "videos").mkdir(exist_ok=True)
    for name in ("dollhouse_a", "dollhouse_c"):
        src = d / "places" / f"{name}.png"
        if src.exists():
            shutil.copy(src, ROOT / "videos" / f"{name}.png")
    out = ROOT / "videos" / f"dollhouse_ep_{DAY}.mp4"
    tmp = ROOT / "videos" / f"tmp_dollhouse_ep_{DAY}.mp4"
    join_scenes(scenes, tmp, theme_music())
    tmp.rename(out)
    shutil.copy(out, ROOT / "videos" / f"{DAY}.mp4")  # the name the daily workflow sends to Telegram
    print(f"Dollhouse episode saved: {out}. New drawings this run: {len(new_assets)}.")



# ---------------------------------------------------------------- quality check
def qa_main():
    """Check the newest daily video and write videos/qa.txt (empty file = all fine)."""
    import re
    vids = sorted((ROOT / "videos").glob("20*.mp4"), key=lambda p: p.stat().st_mtime)
    out = ROOT / "videos" / "qa.txt"
    if not vids:
        out.write_text("QA: no video found to check.\n")
        return
    f = vids[-1]
    problems = []

    def run(args):
        return subprocess.run(args, capture_output=True, text=True)

    probe = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration",
                 "-show_entries", "format=duration", "-of", "json", str(f)])
    info = json.loads(probe.stdout or "{}")
    dur = float(info.get("format", {}).get("duration", 0))
    kinds = {s.get("codec_type"): s for s in info.get("streams", [])}
    if "audio" not in kinds:
        problems.append("The video has no audio track.")
    if "video" in kinds and (kinds["video"].get("width"), kinds["video"].get("height")) != (1080, 1920):
        problems.append("The video size is not 1080x1920.")
    if dur < 25:
        problems.append(f"The video is very short ({dur:.0f}s).")
    if dur > 100:
        problems.append(f"The video is long ({dur:.0f}s, target is under 90s).")
    if "audio" in kinds and "video" in kinds:
        try:
            gap = abs(float(kinds["audio"]["duration"]) - float(kinds["video"]["duration"]))
            if gap > 1.0:
                problems.append(f"Audio and video lengths differ by {gap:.1f}s.")
        except (KeyError, ValueError):
            pass
    sil = run(["ffmpeg", "-i", str(f), "-af", "silencedetect=noise=-45dB:d=1.8", "-vn", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", sil)]
    for st in starts:
        if 1.0 < st < dur - 3.0:
            problems.append(f"Silence in the audio around {st:.0f}s.")
    blk = run(["ffmpeg", "-i", str(f), "-vf", "blackdetect=d=0.6:pix_th=0.06", "-an", "-f", "null", "-"]).stderr
    for st in re.findall(r"black_start:([0-9.]+)", blk):
        problems.append(f"Black screen around {float(st):.0f}s.")
    out.write_text(("QA warnings for " + f.name + ":\n" + "\n".join("- " + p for p in problems) + "\n") if problems else "")
    print("QA:", "; ".join(problems) if problems else "all fine", f"({dur:.0f}s)")


if __name__ == "__main__":
    if os.environ.get("QA") == "1":
        qa_main()
    elif os.environ.get("DOLLHOUSE5") == "1":
        main_dollhouse5()
    elif os.environ.get("DOLLHOUSE_V2") == "1":
        main_dollhouse_v2()
    elif os.environ.get("GUEST_PREVIEW") == "1":
        main_guest_preview()
    elif os.environ.get("ANGLES") == "1":
        main_angles()
    elif os.environ.get("INTRO") == "1":
        main_intro()
    elif os.environ.get("DOLLHOUSE") == "1":
        main_dollhouse()
    elif os.environ.get("DOLLHOUSE_EP") == "1":
        main_dollhouse_episode()
    else:
        main()
