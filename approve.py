#!/usr/bin/env python3
"""Check Telegram for a press on the "Approve & upload" button under a daily video.

Only presses from the owner's own Telegram account (CHAT_ID) count. Prints the episode date to upload into
$GITHUB_OUTPUT as day=YYYY-MM-DD (empty if there is nothing to do). Env: BOT_TOKEN, CHAT_ID.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://api.telegram.org/bot" + os.environ["BOT_TOKEN"] + "/"
OWNER = str(os.environ["CHAT_ID"])


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(API + method, data=data), timeout=45) as r:
        return json.load(r)


def answer(q, text):
    try:  # an old button press can no longer be answered; that must not stop the upload
        tg("answerCallbackQuery", callback_query_id=q["id"], text=text)
    except Exception as e:
        print("Could not answer the button press:", e)


def main():
    updates = tg("getUpdates", timeout=20, allowed_updates=json.dumps([])).get("result", [])
    print("Updates waiting in Telegram:", [(u.get("update_id"), (u.get("callback_query") or {}).get("data") or [k for k in u if k != "update_id"]) for u in updates])
    done = json.loads((ROOT / "transcripts" / "youtube_uploads.json").read_text()) \
        if (ROOT / "transcripts" / "youtube_uploads.json").exists() else {}
    day = ""
    for u in updates:
        q = u.get("callback_query")
        if not q:
            continue
        m = re.fullmatch(r"up:(\d{4}-\d{2}-\d{2})", q.get("data", ""))
        if str(q.get("from", {}).get("id")) != OWNER or not m:
            answer(q, "Not allowed")
            continue
        if m.group(1) in done:
            answer(q, "Already on YouTube")
            continue
        day = m.group(1)
        answer(q, "Uploading to YouTube...")
    if updates:  # mark them as read, so they are not handled twice
        tg("getUpdates", offset=updates[-1]["update_id"] + 1, timeout=0)
    if day:
        tg("sendMessage", chat_id=OWNER, text=f"Approved: uploading the {day} episode to YouTube (about 10 minutes).")
    print("Episode to upload:", day or "none")
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
        f.write(f"day={day}\n")


if __name__ == "__main__":
    main()
