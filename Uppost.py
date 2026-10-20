#!/usr/bin/env python3
"""
UpPost - send a video to your own TikTok drafts (Content Posting API, scope video.upload).

Setup (once):
    pip install requests

    Linux / macOS:
        export TIKTOK_CLIENT_KEY="your_sandbox_client_key"
        export TIKTOK_CLIENT_SECRET="your_sandbox_client_secret"
    Windows PowerShell:
        $env:TIKTOK_CLIENT_KEY="your_sandbox_client_key"
        $env:TIKTOK_CLIENT_SECRET="your_sandbox_client_secret"

Usage:
    1) Log in on https://nguyenkieuthinh.github.io/uppost/ and copy the code, then run
           python uppost.py login PASTE_CODE_HERE
       (the code expires within minutes and works only once)
    2) Upload a video to your TikTok drafts
           python uppost.py upload my_video.mp4

Never commit tokens.json or your client secret to GitHub.
"""

import json
import os
import sys
import time
from urllib.parse import unquote

import requests

BASE = "https://open.tiktokapis.com"
REDIRECT_URI = "https://nguyenkieuthinh.github.io/uppost/callback.html"
TOKEN_FILE = "tokens.json"

MB = 1024 * 1024
SINGLE_CHUNK_MAX = 64 * MB   # up to 64 MB can be sent as one chunk
CHUNK_SIZE = 32 * MB         # used for larger files


def need_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing environment variable {name}. See the setup notes at the top of this file.")
    return value


def save_tokens(data):
    keep = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "open_id": data.get("open_id"),
        "scope": data.get("scope"),
        "expires_at": int(time.time()) + int(data.get("expires_in", 0)),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(keep, f, indent=2)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        sys.exit("No tokens.json found. Run: python uppost.py login <code>")
    with open(TOKEN_FILE) as f:
        return json.load(f)


def token_request(payload):
    r = requests.post(
        f"{BASE}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=payload,
        timeout=30,
    )
    data = r.json()
    if "access_token" not in data:
        sys.exit(f"Token request failed: {json.dumps(data, indent=2)}")
    return data


def cmd_login(code):
    data = token_request({
        "client_key": need_env("TIKTOK_CLIENT_KEY"),
        "client_secret": need_env("TIKTOK_CLIENT_SECRET"),
        "code": unquote(code),
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    })
    save_tokens(data)
    print("Login OK. Token saved to tokens.json")
    print("Granted scope:", data.get("scope"))


def get_access_token():
    tokens = load_tokens()
    # Access tokens last about 24h; refresh a little early.
    if time.time() > tokens.get("expires_at", 0) - 300 and tokens.get("refresh_token"):
        data = token_request({
            "client_key": need_env("TIKTOK_CLIENT_KEY"),
            "client_secret": need_env("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        })
        save_tokens(data)
        print("Access token refreshed.")
        return data["access_token"]
    return tokens["access_token"]


def cmd_upload(path):
    if not os.path.isfile(path):
        sys.exit(f"File not found: {path}")

    access_token = get_access_token()
    size = os.path.getsize(path)

    if size <= SINGLE_CHUNK_MAX:
        chunk_size, total_chunks = size, 1
    else:
        chunk_size = CHUNK_SIZE
        total_chunks = size // chunk_size  # the last chunk takes the remainder

    init = requests.post(
        f"{BASE}/v2/post/publish/inbox/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            }
        },
        timeout=30,
    ).json()

    if init.get("error", {}).get("code") not in (None, "ok"):
        sys.exit(f"Init failed: {json.dumps(init, indent=2)}")

    upload_url = init["data"]["upload_url"]
    publish_id = init["data"]["publish_id"]
    print("Init OK. publish_id:", publish_id)

    with open(path, "rb") as f:
        for i in range(total_chunks):
            start = i * chunk_size
            is_last = i == total_chunks - 1
            end = size - 1 if is_last else start + chunk_size - 1
            f.seek(start)
            chunk = f.read(end - start + 1)
            resp = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                data=chunk,
                timeout=300,
            )
            print(f"Chunk {i + 1}/{total_chunks}: HTTP {resp.status_code}")
            if resp.status_code not in (200, 201, 206):
                sys.exit(f"Upload failed: {resp.text}")

    # Check the status a few times.
    for _ in range(6):
        time.sleep(3)
        st = requests.post(
            f"{BASE}/v2/post/publish/status/fetch/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
            timeout=30,
        ).json()
        status = st.get("data", {}).get("status")
        print("Status:", status)
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            print("Done. Open the TikTok app and check your inbox/notifications for the draft.")
            return
        if status == "FAILED":
            sys.exit(f"TikTok reported failure: {json.dumps(st, indent=2)}")
    print("Upload finished. If the draft is not visible yet, wait a minute and check the TikTok app.")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("login", "upload"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "login":
        cmd_login(sys.argv[2])
    else:
        cmd_upload(sys.argv[2])


if __name__ == "__main__":
    main()