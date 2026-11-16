#!/usr/bin/env python3
"""Daily views summary for The Token Hotel YouTube channel, sent to Telegram.

Reads only PUBLIC numbers (views, likes, comments) with an API key, so it needs no
login and works before the YouTube API audit is passed.

Environment variables:
  YT_API_KEY or GOOGLE_API_KEY - an API key with "YouTube Data API v3" enabled
  BOT_TOKEN, CHAT_ID           - Telegram (optional: without them the text is only printed)
  HANDLE                       - channel handle, default @TheTokenHotel

Keeps yesterday's numbers in stats/youtube.json so the message can show the change.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
STORE = ROOT / "stats" / "youtube.json"
HANDLE = os.environ.get("HANDLE", "@TheTokenHotel")
API = "https://www.googleapis.com/youtube/v3/"


def get(endpoint, **params):
    key = os.environ.get("YT_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    params["key"] = key
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        raise SystemExit(f"YouTube API error {e.code}: {body}")


def fetch():
    ch = get("channels", part="contentDetails,statistics", forHandle=HANDLE)
    if not ch.get("items"):
        raise SystemExit(f"Channel {HANDLE} not found")
    item = ch["items"][0]
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    subs = int(item["statistics"].get("subscriberCount", 0))
    ids, token = [], None
    while True:
        args = dict(part="contentDetails", playlistId=uploads, maxResults=50)
        if token:
            args["pageToken"] = token
        pl = get("playlistItems", **args)
        ids += [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        token = pl.get("nextPageToken")
        if not token:
            break
    videos = {}
    for k in range(0, len(ids), 50):
        vs = get("videos", part="snippet,statistics", id=",".join(ids[k:k + 50]))
        for v in vs.get("items", []):
            st = v.get("statistics", {})
            videos[v["id"]] = {
                "title": v["snippet"]["title"],
                "published": v["snippet"]["publishedAt"][:10],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
            }
    return {"subs": subs, "videos": videos}


def short(title, n=38):
    title = title.replace(" | The Token Hotel", "")
    return title if len(title) <= n else title[: n - 1] + "…"


def delta(now, before):
    d = now - before
    return f" (+{d})" if d > 0 else ""


def report(cur, prev):
    pv = prev.get("videos", {}) if prev else {}
    tv = sum(v["views"] for v in cur["videos"].values())
    ptv = sum(v["views"] for v in pv.values()) if pv else tv
    lines = [f"📊 The Token Hotel on YouTube, {datetime.now(timezone.utc):%d/%m}",
             f"Total views: {tv}{delta(tv, ptv)}",
             f"Subscribers: {cur['subs']}{delta(cur['subs'], prev.get('subs', cur['subs']) if prev else cur['subs'])}",
             ""]
    vids = sorted(cur["videos"].items(), key=lambda kv: kv[1]["published"], reverse=True)
    for vid, v in vids:
        b = pv.get(vid, {})
        lines.append(f"• {short(v['title'])}: {v['views']} views{delta(v['views'], b.get('views', v['views']))}, "
                     f"{v['likes']} 👍, {v['comments']} 💬")
    best = max(vids, key=lambda kv: kv[1]["views"] - pv.get(kv[0], {}).get("views", 0), default=None)
    if best and prev:
        gain = best[1]["views"] - pv.get(best[0], {}).get("views", 0)
        if gain > 0:
            lines += ["", f"Best today: {short(best[1]['title'])} (+{gain})"]
    return "\n".join(lines)


def send(text):
    bot, chat = os.environ.get("BOT_TOKEN"), os.environ.get("CHAT_ID")
    if not (bot and chat):
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    for attempt in range(5):  # Telegram sometimes drops the connection: try again
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{bot}/sendMessage", data=data, timeout=60)
            return
        except Exception as e:
            print("Telegram send failed, retrying:", e)
            __import__("time").sleep(5)
    sys.exit("Could not send the summary to Telegram")


def main():
    if os.environ.get("MOCK") == "1":
        cur = {"subs": 3, "videos": {"a": {"title": "Room 404 | The Token Hotel", "published": "2026-11-14",
                                             "views": 120, "likes": 4, "comments": 1}}}
    else:
        cur = fetch()
    prev = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else None
    text = report(cur, prev)
    print(text)
    send(text)
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
