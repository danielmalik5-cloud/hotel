#!/usr/bin/env python3
"""Upload an episode video to the Token Hotel YouTube channel.

Environment variables:
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN - GitHub secrets, never in this file
  DAY      - episode date (YYYY-MM-DD), default today (UTC)
  PRIVACY  - private (default), unlisted or public. Until the Google Cloud project passes the
             YouTube API audit, YouTube keeps every API upload private whatever this says.
  MOCK=1   - build the title and description and print them, upload nothing

Writes videos/youtube.txt with the result (one line), for the Telegram message.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DAY = os.environ.get("DAY") or date.today().isoformat()
PRIVACY = os.environ.get("PRIVACY", "private")
MOCK = os.environ.get("MOCK") == "1"
TAGS = ["AI agents", "AI animation", "The Token Hotel", "AI comedy", "AI characters", "multi agent",
        "AI shorts", "funny AI", "Shorts"]
CATEGORY_ENTERTAINMENT = "24"


def episode_text():
    pkg_file = ROOT / "transcripts" / f"{DAY}_package.json"
    if pkg_file.exists():  # texts written by package.py
        pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
        TAGS[:] = pkg.get("youtube_tags") or TAGS
        return pkg["youtube_title"], pkg["youtube_description"]
    ep = json.loads((ROOT / "transcripts" / f"{DAY}.json").read_text(encoding="utf-8"))
    title = (ep.get("title") or "A night at the Token Hotel").strip()
    full_title = f"{title} | The Token Hotel"
    if len(full_title) > 95:  # YouTube allows 100 characters
        full_title = title[:95]
    lines = [
        ep.get("situation", "").strip(),
        "",
        "Every episode is improvised by AI agents. Comment a guest for tomorrow! 👇",
        "",
        "#Shorts #AI #AIagents #AIanimation #TheTokenHotel",
    ]
    return full_title, "\n".join(lines).strip()


def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
                                timeout=60) as r:
        return json.load(r)["access_token"]


def upload(video, title, description):
    token = access_token()
    meta = {
        "snippet": {"title": title, "description": description, "tags": TAGS,
                    "categoryId": CATEGORY_ENTERTAINMENT, "defaultLanguage": "en"},
        "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},  # YouTube's altered or synthetic content label
    }
    size = video.stat().st_size
    start = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    with urllib.request.urlopen(start, timeout=60) as r:
        session = r.headers["Location"]
    put = urllib.request.Request(session, data=video.read_bytes(), method="PUT",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"})
    with urllib.request.urlopen(put, timeout=600) as r:
        return json.load(r)


PLAYLIST_TITLE = "The Token Hotel – Season 1"


def add_to_playlist(video_id):
    """Put the new episode at the end of the season playlist. Returns a short note for Telegram."""
    try:
        token = access_token()
        hdr = {"Authorization": f"Bearer {token}"}
        req = urllib.request.Request("https://www.googleapis.com/youtube/v3/playlists?part=snippet&mine=true&maxResults=50",
                                     headers=hdr)
        with urllib.request.urlopen(req, timeout=60) as r:
            lists = json.load(r).get("items", [])
        pl = next((p["id"] for p in lists if p["snippet"]["title"].strip() == PLAYLIST_TITLE), None)
        if not pl:
            return "Playlist not found, the episode was not added to it."
        body = {"snippet": {"playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
        req = urllib.request.Request("https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={**hdr, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
        return "Added to the Season 1 playlist."
    except urllib.error.HTTPError as e:
        return f"Could not add it to the playlist ({e.code}): add it by hand in YouTube Studio."
    except Exception as e:
        return f"Could not add it to the playlist ({e}): add it by hand in YouTube Studio."


def main():
    out = ROOT / "videos" / "youtube.txt"
    out.parent.mkdir(exist_ok=True)
    title, description = episode_text()
    print("Title:", title)
    print("Description:\n" + description)
    if MOCK:
        out.write_text(f"YouTube (mock): {title}\n")
        return
    video = ROOT / "videos" / f"{DAY}.mp4"
    if not video.exists():
        sys.exit(f"No video found: {video}")
    try:
        res = upload(video, title, description)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:600]
        out.write_text(f"YouTube upload failed ({e.code}): {body}\n")
        sys.exit(f"Upload failed: {e.code} {body}")
    vid = res.get("id", "?")
    status = res.get("status", {}).get("privacyStatus", "?")
    note = add_to_playlist(vid) if vid != "?" else ""
    out.write_text(f"YouTube upload OK: https://youtu.be/{vid} (status: {status})\n{note}\n")
    log = ROOT / "transcripts" / "youtube_uploads.json"
    done = json.loads(log.read_text()) if log.exists() else {}
    done[DAY] = {"id": vid, "status": status}
    log.write_text(json.dumps(done, indent=1))
    print(out.read_text())


if __name__ == "__main__":
    main()
