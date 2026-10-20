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
    3) Upload a video with a note for the caption
           python uppost.py upload my_video.mp4 "your note #hashtag"
           python uppost.py upload my_video.mp4 @note.txt      (read the note from a file)
       The note is saved next to the video and copied to the clipboard, so you
       can paste it into the caption box in the TikTok app.
    4) Check a video against TikTok's rules before uploading it
           python uppost.py check my_video.mp4
    5) Cancel a share that is waiting to be published
           python uppost.py cancel 'v_inbox_file~v2.123456789'
    6) See which hashtags are getting the most traffic
           python uppost.py tag
           python uppost.py tag goat funnyvids
    7) Send a photo post (1-35 images) to your TikTok drafts
       Images must be public https URLs on a URL prefix you verified in TikTok
           python uppost.py photo "Caption" https://.../img1.jpg https://.../img2.jpg
       Attach a sound from the TikTok app by its id
           python uppost.py photo "Caption" https://.../img1.jpg --music 7387754233984227846

Never commit tokens.json or your client secret to GitHub.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import unquote

import requests

BASE = "https://open.tiktokapis.com"
REDIRECT_URI = "https://nguyenkieuthinh.github.io/uppost/callback.html"
TOKEN_FILE = "tokens.json"
SHARE_LOG = "shares.log"        # every share this tool made, one id per line

MB = 1024 * 1024
SINGLE_CHUNK_MAX = 64 * MB   # up to 64 MB can be sent as one chunk
CHUNK_SIZE = 32 * MB         # used for larger files
NOTE_MAX = 2200              # TikTok's caption limit, in UTF-16 runes
PHOTO_TITLE_MAX = 90         # photo post title limit
PHOTO_DESC_MAX = 4000        # photo post description limit
MAX_PHOTOS = 35              # TikTok's limit for a photo post
PHOTO_MAX_SIDE = 1080        # TikTok's "maximum 1080p" limit for photos
PHOTO_MAX_BYTES = 20 * MB    # TikTok's per-image size limit

# TikTok's own limits for a video draft, from the media transfer guide.
MAX_VIDEO_BYTES = 4 * 1024 * MB
MAX_VIDEO_SECONDS = 600
MIN_FPS, MAX_FPS = 23, 60
MIN_SIDE, MAX_SIDE = 360, 4096
ALLOWED_VIDEO_CODECS = ("h264", "hevc", "vp8", "vp9")
ALLOWED_VIDEO_FORMATS = ("mp4", "webm", "mov")

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")

# Tags that are worth checking, and the ones people reach for by default.
SEED_TAGS = (
    "fyp", "foryou", "viral", "trending", "fypmood", "challenge",
    "funnyvids", "pets", "goat", "fypシ",
)


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


def record_share(publish_id):
    """Remember a share id, so the quota command can see the history."""
    try:
        with open(SHARE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{publish_id}\n")
    except OSError:
        pass   # a missing history is not worth failing an upload over


def known_shares():
    """Every share id this tool has made, newest first."""
    try:
        with open(SHARE_LOG, encoding="utf-8") as f:
            ids = [line.strip() for line in f if line.strip()]
    except OSError:
        return []
    seen = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    seen.sort(key=share_time, reverse=True)
    return seen


def share_time(publish_id):
    """The time a share was created, from the id itself.

    The top 32 bits of the number after "v2." are a Unix timestamp.
    """
    m = re.search(r"v2\.(\d+)", publish_id or "")
    if not m:
        return 0
    return int(m.group(1)) >> 32


def read_note(arg, limit=NOTE_MAX):
    """Resolve the note argument: an inline string, or @path to read a file."""
    if arg is None:
        return None
    if arg.startswith("@"):
        path = arg[1:]
        if not os.path.isfile(path):
            sys.exit(f"Note file not found: {path}")
        with open(path, encoding="utf-8") as f:
            note = f.read().strip()
    else:
        note = arg.strip()
    if not note:
        sys.exit("The note is empty.")
    length = len(note.encode("utf-16-le")) // 2   # TikTok counts UTF-16 runes
    if length > limit:
        print(f"Note is {length} chars, truncating to {limit}.")
        note = note.encode("utf-16-le")[: limit * 2].decode("utf-16-le", "ignore")
    return note


def save_note(path, note):
    """Save the note next to the video so it can be copied into the TikTok app."""
    out = f"{os.path.splitext(path)[0]}.note.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(note + "\n")
    return out


def copy_to_clipboard(text):
    """Put the note on the clipboard so it can be pasted into the caption box."""
    for tool, args in (("wl-copy", []), ("xclip", ["-selection", "clipboard"]),
                       ("xsel", ["--clipboard", "--input"]), ("pbcopy", [])):
        if not shutil.which(tool):
            continue
        try:
            # Some of these stay alive to serve clipboard requests, so they get
            # their own process and a short grace period rather than a wait.
            process = subprocess.Popen([tool] + args, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            process.communicate(input=text.encode("utf-8"), timeout=2)
        except subprocess.TimeoutExpired:
            pass
        except (OSError, subprocess.SubprocessError):
            continue
        if process.returncode in (0, None):
            return True
    return False


def check_video(path):
    """Check a video against TikTok's upload rules before sending it.

    Returns (ok, problems). An empty problem list means TikTok will take it.
    """
    if not os.path.isfile(path):
        sys.exit(f"File not found: {path}")
    if not shutil.which("ffprobe"):
        sys.exit("ffprobe is not installed, cannot check the video.")

    problems = []
    size = os.path.getsize(path)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type,codec_name,width,height,r_frame_rate",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        info = json.loads(probe.stdout)
    except ValueError:
        sys.exit(f"ffprobe could not read {path}")

    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        problems.append("The file has no video stream.")
        return False, problems

    fmt = (info.get("format", {}).get("format_name") or "").lower()
    container = fmt.split(",")[0]
    if container not in ALLOWED_VIDEO_FORMATS:
        problems.append(f"Container '{container}' is not supported (use mp4, webm or mov).")

    codec = (video.get("codec_name") or "").lower()
    if codec not in ALLOWED_VIDEO_CODECS:
        problems.append(f"Codec '{codec}' is not supported (use H.264, H.265, VP8 or VP9).")

    rate = video.get("r_frame_rate") or "0/1"
    try:
        num, den = (int(x) for x in rate.split("/"))
        fps = num / den if den else 0
    except (ValueError, ZeroDivisionError):
        fps = 0
    if fps and not (MIN_FPS <= fps <= MAX_FPS):
        problems.append(f"Frame rate {fps:.2f} FPS is outside {MIN_FPS}-{MAX_FPS} FPS.")

    width, height = video.get("width") or 0, video.get("height") or 0
    for side, label in ((width, "width"), (height, "height")):
        if side and not (MIN_SIDE <= side <= MAX_SIDE):
            problems.append(f"{label} {side}px is outside {MIN_SIDE}-{MAX_SIDE}px.")

    duration = float(info.get("format", {}).get("duration") or 0)
    if duration > MAX_VIDEO_SECONDS:
        problems.append(f"Duration {duration:.1f}s is over the {MAX_VIDEO_SECONDS}s limit.")

    if size > MAX_VIDEO_BYTES:
        problems.append(f"Size {size / MB:.0f} MB is over the {MAX_VIDEO_BYTES // MB} MB limit.")
    # A file under 5 MB is not a problem: it just has to go up as a single chunk,
    # which cmd_upload already does.

    return not problems, problems


def cmd_check(path):
    ok, problems = check_video(path)
    size = os.path.getsize(path)
    print(f"File: {path} ({size / MB:.1f} MB)")
    if ok:
        print("OK, this video fits TikTok's upload rules.")
        return
    print("Problems:")
    for problem in problems:
        print("  -", problem)
    sys.exit(1)


def cmd_upload(path, note=None):
    if not os.path.isfile(path):
        sys.exit(f"File not found: {path}")

    ok, problems = check_video(path)
    if not ok:
        print("This video does not meet TikTok's rules:")
        for problem in problems:
            print("  -", problem)
        print("Fix these, or pass --force to upload anyway.")
        if "--force" not in sys.argv:
            sys.exit(1)

    access_token = get_access_token()
    size = os.path.getsize(path)

    if size <= SINGLE_CHUNK_MAX:
        chunk_size, total_chunks = size, 1
    else:
        chunk_size = CHUNK_SIZE
        total_chunks = size // chunk_size  # the last chunk takes the remainder

    body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        }
    }
    # The draft endpoint ignores post_info, so the note is not sent here.
    # It lives in the burned-in video and in the saved .note.txt file.

    init = requests.post(
        f"{BASE}/v2/post/publish/inbox/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=body,
        timeout=30,
    ).json()

    if init.get("error", {}).get("code") not in (None, "ok"):
        sys.exit(f"Init failed: {json.dumps(init, indent=2)}")

    upload_url = init["data"]["upload_url"]
    publish_id = init["data"]["publish_id"]
    record_share(publish_id)
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
            deliver_note(path, note)
            return
        if status == "FAILED":
            sys.exit(f"TikTok reported failure: {json.dumps(st, indent=2)}")
    print("Upload finished. If the draft is not visible yet, wait a minute and check the TikTok app.")
    deliver_note(path, note)


def deliver_note(path, note):
    """Hand the note over so it can be pasted into the caption in the app.

    The video draft endpoint ignores captions, so the note cannot be attached
    by the API. It is saved next to the video and copied to the clipboard
    instead, ready to paste into the caption box in the TikTok app.
    """
    if not note:
        return
    saved = save_note(path, note)
    print("Note saved to", saved)
    if copy_to_clipboard(note):
        print("Note copied to the clipboard. Paste it into the caption in the app.")
    else:
        print("Could not reach the clipboard. Copy the note from the file above.")


def cmd_quota(show_shares=False):
    """Report whether the API will take another share, without making one.

    The upload cap is enforced by the init endpoint, and the only way to ask
    it is to call it. A call that would actually create a share is no good
    for a probe, so this one points at a domain that is deliberately not
    verified.

    The endpoint checks in a fixed order: the request shape first, then the
    cap, then the URL. So the answers are readable:

    | Answer | Means |
    |--------|-------|
    | `url_ownership_unverified` | the cap let the request through |
    | `spam_risk_too_many_pending_share` | the cap is still in the way |
    | `invalid_params` | the request shape was rejected, check this tool |

    A probe that returns `url_ownership_unverified` costs nothing: the
    request never got as far as creating a share.
    """
    access_token = get_access_token()
    body = {
        "post_info": {"title": "quota probe"},
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            # A domain that is not verified, so the request cannot succeed
            # even if the cap lets it through.
            "photo_images": ["https://quota-probe.invalid/probe.jpg"],
        },
        "post_mode": "MEDIA_UPLOAD",
        "media_type": "PHOTO",
    }
    r = requests.post(
        f"{BASE}/v2/post/publish/content/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json=body,
        timeout=30,
    )
    try:
        result = r.json()
    except ValueError:
        sys.exit(f"Probe failed: HTTP {r.status_code} {r.text[:300]}")
    code = result.get("error", {}).get("code")

    if code == "spam_risk_too_many_pending_share":
        print("Blocked. The 24-hour share cap is still in the way.")
        print("No share was created by this probe.")
    elif code == "url_ownership_unverified":
        print("Ready. The cap let the request through, and the probe then")
        print("failed on its deliberately unverified URL, so no share was made.")
        print("A photo or video upload should go through now.")
    elif code in (None, "ok"):
        print("Ready, but the probe was accepted outright. No share was created")
        print("because the URL is not a real one.")
    else:
        print(f"Unexpected answer: {code}")
        print(json.dumps(result, indent=2))

    if show_shares:
        print()
        print_share_history(access_token)
    elif code == "spam_risk_too_many_pending_share":
        print()
        print_share_history(access_token)


def print_share_history(access_token):
    """Every share this tool made in the last 24 hours, and when a slot frees."""
    shares = known_shares()
    if not shares:
        print("No shares recorded in shares.log yet.")
        return
    now = time.time()
    in_window = 0
    print(f"Shares made in the last 24 hours ({len(shares)}):")
    for pid in shares:
        made = share_time(pid)
        if not made:
            continue
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(made))
        age = now - made
        if age > 86400:
            print(f"  {pid:<32} {when}  outside the window")
            continue
        in_window += 1
        frees = made + 86400
        left = frees - now
        soon = ""
        if 0 < left <= 86400:
            soon = f"  slot frees in {format_gap(left)} ({time.strftime('%H:%M', time.localtime(frees))})"
        print(f"  {pid:<32} {when}{soon}")
    if in_window:
        oldest = min(share_time(p) for p in shares if share_time(p))
        free_at = oldest + 86400
        if free_at > now:
            print()
            print(f"Oldest share in the window: {time.strftime('%Y-%m-%d %H:%M', time.localtime(oldest))}.")
            print(f"A slot frees at {time.strftime('%Y-%m-%d %H:%M', time.localtime(free_at))}, "
                  f"in {format_gap(free_at - now)}.")


def format_gap(seconds):
    """A duration in days, hours and minutes."""
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def cmd_cancel(publish_id):
    """Cancel a share that is still waiting to be published."""
    access_token = get_access_token()
    r = requests.post(
        f"{BASE}/v2/post/publish/cancel/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={"publish_id": publish_id},
        timeout=30,
    )
    try:
        body = r.json()
    except ValueError:
        sys.exit(f"Cancel failed: HTTP {r.status_code} {r.text[:300]}")
    error = body.get("error", {})
    if r.status_code != 200 or error.get("code") not in (None, "ok"):
        sys.exit(f"Cancel failed: {json.dumps(body, indent=2)}")
    print(f"Cancelled {publish_id}")
    print("It now shows as FAILED with fail_reason publish_cancelled.")
    print("Note: this does not free a slot in the 5-per-24-hours upload cap.")


def cmd_photo(title, urls, music_id=None, auto_music=None, description=None):
    access_token = get_access_token()

    if len(urls) > MAX_PHOTOS:
        sys.exit(f"Too many images: {len(urls)}. TikTok takes at most {MAX_PHOTOS}.")

    # The title is the short headline, the description is the caption body.
    # If only one text is given it serves as both, so a one-line post still
    # lands with the words the user wrote.
    body_text = description if description is not None else title
    post_info = {
        "title": title[:PHOTO_TITLE_MAX],
        "description": body_text[:PHOTO_DESC_MAX],
    }
    if music_id:
        # The sound to attach. Accepts a bare id, a sound link, or a video
        # link whose sound is read off its embed page.
        resolved, info = resolve_music_id(str(music_id))
        if not resolved:
            sys.exit(f"Could not work out a sound id from: {music_id}\n"
                     "Pass a sound id, a tiktok.com/sound/... link, "
                     "or a video link.")
        post_info["music_id"] = str(resolved)
        if info:
            print(f"Sound: {info['name']} - {info['author']}  (id {resolved})")
        print("Note: TikTok accepts this sound id but does not apply it to a "
              "photo draft. Pick the sound in the app before publishing.")
    if auto_music is not None:
        post_info["auto_add_music"] = auto_music

    init = requests.post(
        f"{BASE}/v2/post/publish/content/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": post_info,
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": 0,
                "photo_images": urls,
            },
            "post_mode": "MEDIA_UPLOAD",
            "media_type": "PHOTO",
        },
        timeout=30,
    ).json()

    code = init.get("error", {}).get("code")
    if code not in (None, "ok"):
        if code == "url_ownership_unverified":
            sys.exit("TikTok does not recognise this domain as yours.\n"
                     "Add it under URL properties in the TikTok for Developers site,\n"
                     "then run this again. The verification file for this domain is:\n"
                     "  https://nguyenkieuthinh.github.io/uppost/"
                     "tiktoknZIRTB9kqIlBLFSfXjUNdWvIxMX2SAY8.txt")
        sys.exit(f"Init failed: {json.dumps(init, indent=2)}")

    publish_id = init["data"]["publish_id"]
    record_share(publish_id)
    print("Init OK. publish_id:", publish_id)

    for _ in range(10):
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
    print("Request sent. Check the TikTok app in a minute.")


def cmd_tag(names, limit=10):
    """Show which hashtags are worth using, ranked by how much traffic they get.

    TikTok's own trending list needs a signed request that only their web app
    can make, so this uses the per-hashtag endpoint instead, which is open.
    It reports live view and video counts for each candidate, and a reach
    score: views per video shows whether a tag is crowded or worth jumping on.
    """
    candidates = list(names) if names else list(SEED_TAGS)
    rows = []
    for name in candidates:
        stats = hashtag_stats(name)
        if stats is None:
            print(f"#{name}: could not reach TikTok", file=sys.stderr)
            continue
        rows.append((name, stats))

    rows.sort(key=lambda row: row[1]["views"], reverse=True)
    rows = rows[:limit]

    print(f"{'tag':<24}{'views':>18}{'videos':>16}{'views/video':>14}")
    for name, stats in rows:
        reach = stats["views"] / stats["videos"] if stats["videos"] else 0
        print(f"#{name:<23}{stats['views']:>18,}{stats['videos']:>16,}{reach:>14,.0f}")

    # Offer the top tags as ready-to-paste hashtags.
    print("\nReady to paste:")
    print(" ".join(f"#{name}" for name, _ in rows))


def cmd_prep(paths, out_dir, quality=88):
    """Resize images to what TikTok accepts for a photo post.

    TikTok takes WebP or JPEG, at most 1080p, and at most 20 MB each. The
    originals are never touched; the resized copies go to out_dir.
    """
    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    for path in paths:
        if not os.path.isfile(path):
            sys.exit(f"File not found: {path}")
        im = Image.open(path)
        if im.mode in ("RGBA", "P", "LA"):
            # Flatten onto black: JPEG has no alpha channel.
            flat = Image.new("RGB", im.size, (0, 0, 0))
            im = im.convert("RGBA")
            flat.paste(im, mask=im.split()[-1])
            im = flat
        else:
            im = im.convert("RGB")
        im.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), Image.LANCZOS)
        name = os.path.splitext(os.path.basename(path))[0][:30] + ".jpg"
        out = os.path.join(out_dir, name)
        im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        size = os.path.getsize(out)
        print(f"{out}  {im.size[0]}x{im.size[1]}  {size / MB:.2f} MB")


def cmd_music(target):
    """Print the sound id used by a TikTok video, ready for `photo --music`.

    Accepts a full video link, a share link, or a bare video id. The embed
    page carries the sound metadata in plain HTML, so no signing is needed.
    A share link that points at a sound rather than a video gives the sound
    id directly.
    """
    # A sound page already carries the id in its own path.
    if "/sound/" in target or "/music/" in target:
        m = re.findall(r"\d{15,22}", target)
        if m:
            print(f"music   {m[-1]}")
            print("type    sound page link")
            print(f"\nReady to paste:\n{m[-1]}")
            return

    video_id = extract_video_id(target)
    if not video_id:
        video_id = resolve_short_link(target)
    if video_id:
        info = sound_info(video_id)
        if info:
            print(f"video   {video_id}")
            print(f"music   {info['music_id']}")
            print(f"title   {info['name']}")
            if info.get("author"):
                print(f"author  {info['author']}")
            print(f"type    {'original sound' if info.get('original') else 'licensed sound'}")
            print(f"\nReady to paste:\n{info['music_id']}")
            return
    music_id = music_id_from_share_link(target)
    if music_id:
        print(f"music   {music_id}")
        print("type    original sound (shared from the app)")
        print(f"\nReady to paste:\n{music_id}")
        return
    sys.exit(f"No sound found for: {target}\n"
             "Expected a video link like https://www.tiktok.com/@user/video/1234567890\n"
             "or a sound share link, which redirects to /music/<slug>-<id>.")


def cmd_sounds(handles, limit=20):
    """List the sounds used by a TikTok account's recent videos.

    A photo post can carry one sound, so this is for picking one that fits.
    Each account's embed page lists its video ids, and each video's embed
    page names the sound it uses, so no signed request is needed.
    """
    if not handles:
        sys.exit("Usage: python uppost.py sounds <user> [user ...]")
    for handle in handles:
        handle = handle.lstrip("@")
        vids = account_video_ids(handle)
        if not vids:
            print(f"@{handle}: no videos found")
            continue
        print(f"\n@{handle}: {len(vids)} videos")
        seen = {}
        for vid in vids:
            info = sound_info(vid)
            if not info:
                continue
            key = info["music_id"]
            if key not in seen:
                seen[key] = (info, vid)
        for key, (info, vid) in list(seen.items())[:limit]:
            kind = "original" if info["original"] else "licensed"
            print(f"  {key}  {info['name'][:40]:<40} {info['author'][:22]:<22} {kind}")


def account_video_ids(handle):
    """The video ids on a TikTok account's embed page, newest first."""
    try:
        r = requests.get(f"https://www.tiktok.com/embed/@{handle}",
                         headers={"User-Agent": BROWSER_UA}, timeout=25)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    ids = []
    for m in re.finditer(r"/video/(\d{15,22})", r.text):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    ids.sort(reverse=True)   # higher id means newer video
    return ids


def resolve_music_id(value):
    """Turn whatever the user passed to --music into a sound id.

    Accepts a bare id, a sound link, a video link, or a share link. A sound
    link already ends in the id; a video link needs its embed page read.
    """
    value = value.strip()
    if re.fullmatch(r"\d{15,22}", value):
        return value, None

    # A sound link: the id is the last number in it.
    if "/sound/" in value or "/music/" in value:
        m = re.findall(r"\d{15,22}", value)
        if m:
            return m[-1], None

    # A video link: read the sound off its embed page.
    video_id = extract_video_id(value)
    if not video_id:
        video_id = resolve_short_link(value)
    if video_id:
        info = sound_info(video_id)
        if info:
            return info["music_id"], info

    # A short link that points at a sound rather than a video. Following it
    # lands on /music/<slug>-<id>, where the id is the sound id.
    music_id = music_id_from_share_link(value)
    if music_id:
        return music_id, None
    return None, None


def music_id_from_share_link(url):
    """The sound id in a short share link that points at a sound.

    Sharing a sound gives a link that redirects to
    /music/<slug>-<id>?...&share_music_id=<id>. Following the redirect is
    what tells a sound link apart from a video link.
    """
    if not url.startswith("http"):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": BROWSER_UA},
                         timeout=20, allow_redirects=True)
    except requests.RequestException:
        return None
    final = r.url or ""
    if "/music/" not in final and "/sound/" not in final:
        return None
    m = re.search(r"share_music_id=(\d{15,22})", final)
    if m:
        return m.group(1)
    m = re.search(r"/(?:music|sound)/[^/?]*?-(\d{15,22})", final)
    if m:
        return m.group(1)
    return None


def extract_video_id(target):
    """Pull the numeric video id out of a link, a share link, or a bare id."""
    digits = re.findall(r"\d{15,22}", target)
    for candidate in digits:
        # A link can carry both a video id and a user id; the video one comes
        # after "/video/". When the input is a bare id there is only one.
        if "/video/" in target and target.index(candidate) < target.index("/video/"):
            continue
        return candidate
    return None


def resolve_short_link(url):
    """Follow a vm.tiktok.com share link and read the video id off the end."""
    if not url.startswith("http"):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": BROWSER_UA},
                         timeout=20, allow_redirects=True)
    except requests.RequestException:
        return None
    return extract_video_id(r.url)


def sound_info(video_id):
    """The sound attached to a video, read from its embed page."""
    try:
        r = requests.get(
            f"https://www.tiktok.com/embed/v2/{video_id}",
            headers={"User-Agent": BROWSER_UA},
            timeout=25,
        )
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    html = r.text
    block = re.search(r'"musicInfos":(\{.*?\}),"', html)
    if not block:
        return None
    try:
        data = json.loads(block.group(1))
    except ValueError:
        return None
    music_id = data.get("musicId")
    if not music_id:
        return None
    return {
        "music_id": music_id,
        "name": data.get("musicName") or "",
        "author": data.get("authorName") or "",
        "original": bool(data.get("original")),
    }


def hashtag_stats(name):
    """Live view and video counts for one hashtag, or None if it is unknown."""
    name = name.lstrip("#").strip()
    if not name:
        return None
    try:
        r = requests.get(
            f"https://www.tiktok.com/api/challenge/detail/?challengeName={name}&aid=1988",
            headers={"User-Agent": BROWSER_UA},
            timeout=20,
        )
        info = r.json().get("challengeInfo", {})
    except (requests.RequestException, ValueError):
        return None
    stats = info.get("statsV2", {})
    views = int(stats.get("viewCount") or 0)
    videos = int(stats.get("videoCount") or 0)
    if not views and not videos:
        return None
    return {"views": views, "videos": videos}


def main():
    cmds = ("login", "upload", "api", "check", "cancel", "photo", "tag", "music",
            "sounds", "prep", "quota")
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "quota":
        cmd_quota(show_shares="--shares" in sys.argv[2:])
        return
    if sys.argv[1] == "tag":
        cmd_tag(sys.argv[2:])
        return
    if sys.argv[1] == "music":
        if len(sys.argv) < 3:
            sys.exit('Usage: python uppost.py music <tiktok video link or id>')
        cmd_music(sys.argv[2])
        return
    if sys.argv[1] == "sounds":
        if len(sys.argv) < 3:
            sys.exit('Usage: python uppost.py sounds <user> [user ...]')
        cmd_sounds(sys.argv[2:])
        return
    if sys.argv[1] == "prep":
        if len(sys.argv) < 4:
            sys.exit('Usage: python uppost.py prep <out_dir> <image> [image ...]')
        cmd_prep(sys.argv[3:], sys.argv[2])
        return
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "login":
        cmd_login(sys.argv[2])
    elif sys.argv[1] == "check":
        cmd_check(sys.argv[2])
    elif sys.argv[1] == "cancel":
        cmd_cancel(sys.argv[2])
    elif sys.argv[1] in ("upload", "api"):
        # `api` is an alias for `upload`: same API call, shorter to type.
        note = read_note(sys.argv[3]) if len(sys.argv) > 3 else None
        cmd_upload(sys.argv[2], note)
    else:
        if len(sys.argv) < 4:
            sys.exit('Usage: python uppost.py photo "Title" URL1 [URL2 ...]\n'
                     '       python uppost.py photo "Title" URL1 --music 7387754233984227846\n'
                     '       python uppost.py photo "Title" URL1 --desc @caption.txt')
        music_id = None
        auto_music = None
        description = None
        args = []
        rest = sys.argv[3:]
        i = 0
        while i < len(rest):
            arg = rest[i]
            if arg == "--music" and i + 1 < len(rest):
                music_id = rest[i + 1]
                i += 2
            elif arg == "--desc" and i + 1 < len(rest):
                description = read_note(rest[i + 1], PHOTO_DESC_MAX)
                i += 2
            elif arg == "--urls" and i + 1 < len(rest):
                # A file with one image URL per line, for long lists.
                path = rest[i + 1]
                if not os.path.isfile(path):
                    sys.exit(f"URL list not found: {path}")
                with open(path, encoding="utf-8") as f:
                    args.extend(line.strip() for line in f
                               if line.strip() and not line.startswith("#"))
                i += 2
            elif arg == "--auto-music":
                auto_music = True
                i += 1
            elif arg == "--no-auto-music":
                auto_music = False
                i += 1
            else:
                args.append(arg)
                i += 1
        cmd_photo(sys.argv[2], args, music_id, auto_music, description)


if __name__ == "__main__":
    main()