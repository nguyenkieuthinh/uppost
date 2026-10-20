# UpPost

A personal tool that sends my own videos and photos to my own TikTok drafts, so
I can finish and publish them in the TikTok app. It uses the TikTok Content
Posting API with the `video.upload` scope: the tool only ever creates drafts in
the account owner's inbox. It never publishes on its own.

The site that handles the login step lives at
<https://nguyenkieuthinh.github.io/uppost/>.

## Setup

Install the one dependency:

```bash
pip install requests
```

Set your TikTok app credentials. The client key is public and already sits in
`index.html`; the client secret must never go into a file that is committed.

```bash
export TIKTOK_CLIENT_KEY="your_sandbox_client_key"
export TIKTOK_CLIENT_SECRET="your_sandbox_client_secret"
```

On Windows PowerShell:

```powershell
$env:TIKTOK_CLIENT_KEY="your_sandbox_client_key"
$env:TIKTOK_CLIENT_SECRET="your_sandbox_client_secret"
```

`ffmpeg` and `ffprobe` are needed for the `check` command. On Arch:

```bash
sudo pacman -S ffmpeg
```

## Logging in

1. Open <https://nguyenkieuthinh.github.io/uppost/> and choose **Login with
   TikTok**, then approve the `video.upload` permission.
2. TikTok returns to the callback page with an authorization code. Copy it.
3. Exchange it for a token:

```bash
python3 uppost.py login 'PASTE_CODE_HERE'
```

The code works once and expires within minutes. The token is written to
`tokens.json` with `chmod 600`; that file is in `.gitignore` and must stay out
of Git.

Access tokens last about 24 hours. The tool refreshes them on its own using
the stored refresh token, so you only log in again when the refresh token is
revoked.

## Commands

### `upload` — send a video to your drafts

```bash
python3 uppost.py upload my_video.mp4
```

The video is uploaded in chunks and lands in the TikTok app's inbox. Open the
app, tap the inbox notification, and publish it.

`api` is an alias for `upload`, so `python3 uppost.py api my_video.mp4` does
the same thing.

### `upload` with a note for the caption

```bash
python3 uppost.py upload my_video.mp4 "today goat 🔥 #fyp #viral"
python3 uppost.py upload my_video.mp4 @note.txt
```

**The note is the caption you write in the app, not text burned into the
video.** The note is written to `my_video.note.txt` next to the video and
copied to your clipboard, so you can paste it straight into the caption box.

This is a limitation of the API, not a shortcut. The video draft endpoint
(`/v2/post/publish/inbox/video/init/`) ignores a `post_info` block entirely:
it returns `ok` for a valid title, for an over-long title, and even for
`"post_info": "not an object"`. The photo endpoint does validate it and
rejects a bad body with `invalid_params`, so the difference is real, not a
fluke. TikTok's own documentation for the video upload endpoint lists only
`source_info` and no caption field.

To get a caption attached by the API you would need the `video.publish` scope
and the direct-post endpoint, which publishes straight to the account instead
of creating a draft, and locks videos to private viewing until the app passes
TikTok's audit.

### `check` — test a video before uploading it

```bash
python3 uppost.py check my_video.mp4
```

Checks the file against TikTok's upload rules so a bad video fails in a second
instead of after the upload. It runs automatically before every upload.

| Rule | Limit |
|------|-------|
| Container | mp4, webm, mov |
| Codec | H.264, H.265, VP8, VP9 |
| Frame rate | 23–60 FPS |
| Resolution | 360–4096 px on each side |
| Duration | up to 10 minutes |
| Size | up to 4 GB |

A file under 5 MB is fine. It just goes up as a single chunk, which the tool
already handles.

To upload anyway after a warning, pass `--force`:

```bash
python3 uppost.py upload my_video.mp4 --force
```

### `tag` — see which hashtags are getting traffic

```bash
python3 uppost.py tag
python3 uppost.py tag goat funnyvids pets
```

Prints live view and video counts for each tag, sorted by views, plus a
views-per-video column that shows how crowded a tag is. The last line is a
ready-to-paste list of hashtags.

TikTok's own trending list is not reachable from a script. It needs a signed
request that only their web app can make, and every public path to it returns
`url doesn't match` or `missing required fields`. The per-hashtag endpoint is
open, so this works on live numbers instead of a fixed list.

### `photo` — send images to your drafts

```bash
python3 uppost.py photo "My caption" https://example.com/img1.jpg https://example.com/img2.jpg
```

Up to 35 images. Unlike video, this one **does** set the caption through the
API: `post_info.title` shows as the title and `post_info.description` shows in
the editing flow, and the title is capped at 90 characters and the description
at 4000.

The images must be public HTTPS URLs on a domain or URL prefix you have
verified in the TikTok developer site. Without that you get
`url_ownership_unverified`.

### `cancel` — stop a share that is waiting to be published

```bash
python3 uppost.py cancel 'v_inbox_file~v2.123456789'
```

Marks the share as failed with `publish_cancelled`, which clears it out of the
TikTok inbox. Handy when a draft is not worth publishing.

It does not free a slot in the 5-per-24-hours cap, see below.

### `status.py` — check an upload without uploading again

```bash
python3 status.py 'v_inbox_file~v2.123456789'
```

Prints the raw status response for a `publish_id`. Useful when an upload looks
stuck.

## The API in short

| Endpoint | Used for | Scope |
|----------|----------|-------|
| `POST /v2/oauth/token/` | login and refresh | — |
| `POST /v2/post/publish/inbox/video/init/` | video draft | `video.upload` |
| `POST /v2/post/publish/content/init/` | photo draft | `video.upload` |
| `POST /v2/post/publish/status/fetch/` | check status | `video.upload` |
| `POST /v2/post/publish/cancel/` | cancel a pending share | `video.upload` |

The video flow is three steps: `init` returns a `publish_id` and an
`upload_url`, the file is `PUT` to that URL in chunks, then the status is
polled until it reports `SEND_TO_USER_INBOX`.

## Limits and errors

| Message | What it means |
|---------|---------------|
| `spam_risk_too_many_pending_share` | The 5-per-24-hours upload cap was hit. See below for what actually frees a slot. |
| `url_ownership_unverified` | The image URLs are not on a verified domain. Add it in the developer site. |
| `scope_not_authorized` | The token does not carry the scope this call needs. |
| `access_token_invalid` | The token expired and could not be refreshed. Log in again. |
| `rate_limit_exceeded` | 6 requests per minute on the init endpoints, 30 on the status endpoint. |
| `frame_rate_check_failed` | The video's frame rate is outside 23–60 FPS. Run `check` on it. |
| `spam_risk_user_banned_from_posting` | The account cannot post. This one is not fixable from here. |

Chunking rules: each chunk must be at least 5 MB and at most 64 MB, except the
last one, which may be larger. Files over 64 MB go up in 32 MB chunks.

### The 5-per-24-hours cap

TikTok's docs say: "There may be at most 5 pending shares within any 24-hour
period." What that counts in practice was measured on a real account, and the
answer is not what the wording suggests.

| Action | Does it free a slot? |
|--------|----------------------|
| Publishing a pending share | No, not on its own |
| Cancelling a pending share (`POST /v2/post/publish/cancel/`) | No, not on its own |
| Both, and leaving 0 pending | Still blocked |

What was observed: after 5 shares, with 1 published and 4 cancelled or failed
and 0 pending, `init` still returned `spam_risk_too_many_pending_share`, and
kept returning it for 10 minutes of retries. The cap appears to count shares
inside a rolling 24-hour window rather than shares awaiting approval, so
publishing or cancelling does not clear it. Expect to wait out the window.

The error only blocks the `init` endpoints. `status/fetch` and `cancel/` keep
working, so an existing upload can still be checked and cancelled while the
cap is active.

`POST /v2/post/publish/cancel/` is worth knowing about either way. It takes a
`publish_id` and moves that share to `FAILED` with `fail_reason:
publish_cancelled`, which stops a draft nobody is going to publish from sitting
in the inbox.

## Files

| File | What it is |
|------|------------|
| `uppost.py` | The tool. |
| `status.py` | Checks the status of one upload. |
| `index.html` | The login page. Holds the public client key. |
| `callback.html` | Where TikTok sends the authorization code. |
| `tokens.json` | Your token. Git-ignored, never commit it. |

## Notes for the future

- The photo command's `photo_cover_index` was `1`, but TikTok counts from `0`.
  It is now `0`, which is the first image.
- Photo posts send the same text as both title and description. They are now
  separate limits, so a long caption is no longer cut short at 90 characters.
- The draft endpoint's silence on `post_info` is worth re-testing if TikTok
  documents captions for video uploads later.
