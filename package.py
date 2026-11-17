#!/usr/bin/env python3
"""Write the upload texts for an episode (YouTube title, description, tags and a TikTok caption).

Reads transcripts/<DAY>.json, asks Claude once (a fraction of a cent) and saves transcripts/<DAY>_package.json.
Also writes videos/package.html: the texts ready to copy, for the Telegram message.
Env: ANTHROPIC_API_KEY, DAY (default today UTC), MOCK=1 for no API call.
"""
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAY = os.environ.get("DAY") or datetime.now(timezone.utc).date().isoformat()
MOCK = os.environ.get("MOCK") == "1"
ENDING = "Every episode is improvised by AI agents. Comment a guest for tomorrow! 👇"
HASHTAGS = "#Shorts #AI #AIagents #AIanimation #TheTokenHotel"
TIKTOK_TAGS = "#AI #AIagents #AIanimation #TheTokenHotel #fyp"
BASE_TAGS = ["AI agents", "AI animation", "The Token Hotel", "AI comedy", "AI characters", "robots", "cartoon", "Shorts"]

RULES = (
    "You write upload texts for a funny daily YouTube Short of the series The Token Hotel (AI agents run a hotel). "
    "Reply with ONLY a JSON object with these keys:\n"
    '"title": the episode question plus one fitting emoji, at most 70 characters (no series name),\n'
    '"teaser": two short sentences that tease the episode without spoiling the ending, plain English, '
    "naming the characters,\n"
    '"tags": 4 extra short YouTube tags about this episode (lowercase words, no #),\n'
    '"tiktok": a very short hook for TikTok, at most 60 characters, with one or two emojis.'
)


def ask_claude(user_text):
    body = json.dumps({"model": os.environ.get("MODEL", "claude-haiku-5-5"), "max_tokens": 3000, "system": RULES,
                       "messages": [{"role": "user", "content": user_text}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.load(r)
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))


def make_package(ep):
    title = (ep.get("title") or "A night at the Token Hotel").strip()
    got = {}
    if not MOCK and os.environ.get("ANTHROPIC_API_KEY"):
        script = "\n".join(f"{l['speaker']}: {re.sub(r'<[^>]+>', '', l['line']).strip()}" for l in ep["lines"])
        try:
            reply = ask_claude(f"Episode question: {title}\nStory: {ep.get('situation', '')}\n\nScript:\n{script}")
            m = re.search(r"\{.*\}", reply, re.S)
            got = json.loads(m.group(0)) if m else {}
        except Exception as e:
            print(f"Package texts fell back to defaults ({e}).", file=sys.stderr)
    yt_title = str(got.get("title") or title).strip()[:70]
    teaser = str(got.get("teaser") or ep.get("situation", "")).strip()
    extra = [str(t).strip().lstrip("#") for t in (got.get("tags") or []) if str(t).strip()][:4]
    hook = str(got.get("tiktok") or title).strip()[:80]
    return {
        "youtube_title": f"{yt_title} | The Token Hotel"[:100],
        "youtube_description": f"{teaser}\n\n{ENDING}\n\n{HASHTAGS}",
        "youtube_tags": BASE_TAGS + [t for t in extra if t.lower() not in (b.lower() for b in BASE_TAGS)],
        "tiktok_caption": f"{hook} {ENDING} {TIKTOK_TAGS}",
    }


def main():
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))
    out = ROOT / "transcripts" / f"{DAY}_package.json"
    pkg = make_package(ep)
    out.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    e = html.escape
    msg = (f"<b>Upload texts {DAY}</b>\n\n<b>YouTube title</b>\n<pre>{e(pkg['youtube_title'])}</pre>\n"
           f"<b>YouTube description</b>\n<pre>{e(pkg['youtube_description'])}</pre>\n"
           f"<b>YouTube tags</b>\n<pre>{e(', '.join(pkg['youtube_tags']))}</pre>\n"
           f"<b>TikTok caption</b>\n<pre>{e(pkg['tiktok_caption'])}</pre>")
    (ROOT / "videos").mkdir(exist_ok=True)
    (ROOT / "videos" / "package.html").write_text(msg, encoding="utf-8")
    print(json.dumps(pkg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
