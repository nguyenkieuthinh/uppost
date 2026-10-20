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

Up to 35 images. The limit was confirmed against the API: 35 images get
through, 36 come back as `invalid_params`. The tool refuses more than 35
before it sends anything.

Unlike video, this one **does** set the caption through the API:
`post_info.title` shows as the title and `post_info.description` shows in the
editing flow, and the title is capped at 90 characters and the description at
4000.

The caption was confirmed on a published post: the title and the full
description, hashtags included, came through untouched.

The images must be public HTTPS URLs on a domain or URL prefix you have
verified in the TikTok developer site. Without that you get
`url_ownership_unverified`.

To note down a sound, pass the id of a sound from the TikTok app:

```bash
python3 uppost.py photo "My caption" https://example.com/img1.jpg --music 7387754233984227846
```

A photo post carries one sound. `--music` also takes a link instead of a bare
id, so you can paste whatever you copied out of the app:

| What you pass | What happens |
|---------------|--------------|
| `7691584836313827380` | used as the id |
| `https://www.tiktok.com/sound/7691584836313827380` | the number at the end is the id |
| `https://www.tiktok.com/@user/video/7698323909124345108` | the sound of that video is read and used |
| `https://vt.tiktok.com/ZS9UgJ4JpwScP-CnxwM/` | a sound share link: the sound id is read off the redirect |

**The sound still has to be picked in the app.** The field is sent to TikTok
and then ignored, so a published post ends up with whatever sound TikTok
chose. See "Sound on a photo post" for the measurement behind that.

See the section on sound below for how to find a sound that fits.

For a longer caption, keep it in a file and point `--desc` at it. For a long
list of images, put one URL per line and point `--urls` at that file:

```bash
python3 uppost.py photo "Midnight Wanderlust" --urls images.txt \
    --desc @captions/wallpapers.txt --music 7691584836313827380
```

`--desc` takes the path with an `@` in front of it, and `--urls` takes the
plain path. A file this repo already has:

| File | What it is |
|------|------------|
| `url/list.txt` | the seven wallpaper URLs, one per line |
| `captions/wallpapers.txt` | the English caption and its 20 hashtags |

A ready-to-paste command for the wallpaper set:

```bash
python3 uppost.py photo "Midnight Wanderlust" \
    --urls /home/thinh/antigravity/uppost/url/list.txt \
    --desc @/home/thinh/antigravity/uppost/captions/wallpapers.txt \
    --music 7691584836313827380
```

### `prep` — resize images to what TikTok accepts

```bash
python3 uppost.py prep ./out ~/Pictures/Wallpapers/*.jpg
```

TikTok takes WebP or JPEG, at most 1080p, and at most 20 MB per image. Wallpaper
files run far past that, so this scales them down and re-encodes them as JPEG.
The originals are never touched; the copies go to the output directory.

The resized files still have to be served over HTTPS from a verified domain
before `photo` can use them.

### `music` — get the sound id off a video

```bash
python3 uppost.py music https://www.tiktok.com/@user/video/7698804964629466389
python3 uppost.py music 7698804964629466389
```

Prints the sound id used by a video, plus its title and author. This is the
id you pass to `photo --music`. It reads the video's embed page, so it needs
no login and works for any public video.

### `sounds` — list the sounds an account is using

```bash
python3 uppost.py sounds setuphype tomsguide
```

Prints the sound id, title and author for each sound on the account's recent
videos. This is how you find a sound that fits, without the app.

Each account's embed page lists its video ids, and each video's embed page
names the sound it uses, so this needs no login and no signed request. It
works for any public account.

### `quota` — check whether the API will take another share

```bash
python3 uppost.py quota
python3 uppost.py quota --shares
```

Says whether an upload would go through right now, and how long until it
would. It does not create a share.

The cap is enforced by the `init` endpoint, and the only way to ask that
endpoint anything is to call it. So the probe points at a domain that is
deliberately not verified. The endpoint checks in a fixed order, and the
answer says which check it stopped at:

| Answer | Means |
|--------|-------|
| `url_ownership_unverified` | the cap let the request through, so an upload should work |
| `spam_risk_too_many_pending_share` | the cap is still in the way |
| `invalid_params` | the request shape was rejected, which would be a bug in this tool |

A probe that reaches the URL check never created a share, so running it
costs nothing.

`--shares` adds the list of shares made in the last 24 hours, with the time
each one frees a slot. Every share this tool makes is recorded in
`shares.log`, and the top 32 bits of a publish id are its creation time, so
the window can be worked out without guessing.

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

## Sound on a photo post

A photo post can carry a sound from TikTok, but the field that does it is not
in the documentation. `post_info.music_id` was found by probing the endpoint:
it is the only audio field it recognises.

The photo endpoint validates `post_info` strictly, which makes it usable as an
oracle. A recognised field given a wrong type comes back as
`400 invalid_params`, while an unknown field is ignored and the request falls
through to the URL check:

| Field | Result |
|-------|--------|
| `post_info.music_id` | `400 invalid_params` when given a number, so it is a **string** |
| `post_info.audio`, `sound`, `audio_info`, `music`, `sound_id`, `audio_url`, and about ten more | ignored, no error |
| `post_info.auto_add_music` | ignored for `MEDIA_UPLOAD`; documented to work only for `DIRECT_POST` |

`--music` takes that id as a string.

### It does not actually attach the sound

This is the important part, and it was measured rather than assumed. A photo
post was created with `post_info.music_id` set to a specific sound, the post
was published from the app, and the published post carries a **different**
sound. The one that was asked for is not on the post at all.

So `music_id` is a field the endpoint recognises, validates, and then ignores.
It is not a way to choose the sound on a photo post.

The documented way to get music on a photo is `post_info.auto_add_music`, and
the documentation says it works only for `post_mode: DIRECT_POST`, not for
`MEDIA_UPLOAD`. A `MEDIA_UPLOAD` draft is the only mode this tool uses,
because `DIRECT_POST` publishes straight to the account and needs the
`video.publish` scope.

**The sound on a photo draft has to be picked in the app.** Open the draft
from the inbox, choose the sound there, and publish. The `--music` flag
records the id you wanted and prints it back, which is useful for keeping
track of it, but it does not set the sound.


### Finding the id

Open the sound in the TikTok app, choose **Share**, and copy the link. The id
is the long number at the end of it:

```
https://www.tiktok.com/sound/7387754233984227846
                                       ^^^^^^^^^^^^^^ this
```

TikTok's own pages are rendered in JavaScript, so scraping a sound page for
the id does not work, and their music API needs a signed request.

There is a faster route when you already know a video that uses the sound.
The `music` command reads the sound off any video's embed page and prints the
id:

```bash
python3 uppost.py music https://www.tiktok.com/@user/video/7698804964629466389
```

```
video   7698804964629466389
music   7698804998703827713
title   original sound
author  THINH NK 2.0
type    original sound

Ready to paste:
7698804998703827713
```

It takes a full link, a `vm.tiktok.com` share link, or a bare video id, and it
works on other people's videos as well as your own. The embed page carries
the sound metadata in plain HTML, so no signing or login is involved.

A share link that points at a **sound** rather than a video works too, and is
read straight off the redirect:

```bash
python3 uppost.py music https://vt.tiktok.com/ZS9UgJ4JpwScP-CnxwM/
```

```
music   7525403525971528465
type    original sound (shared from the app)

Ready to paste:
7525403525971528465
```

Sharing a sound from the app gives a link that redirects to
`/music/<slug>-<id>`, with the id also in the `share_music_id` query
parameter. The sound page itself is rendered in JavaScript, so the id comes
from the redirect target rather than the page body.

### Finding a sound that fits

A photo post takes one sound, so the question is which one. The `sounds`
command lists what an account is using:

```bash
python3 uppost.py sounds edits tomsguide
```

Accounts that post wallpapers, setups and edits are the ones worth looking
at. Among the sounds that turned up, the ones that matched a dark wallpaper
post best were:

| Sound | Id |
|-------|-----|
| CRAMPS (Slowed) - nevora & zhyar | `7691584836313827380` |
| EUCLID - Slowed - KLEAVE & SXCREDMANE | `7689157194702194689` |
| NA PISTOLA (SLOWED) - wither & zhyar | `7689590403520530484` |
| Basement Replay - Mildred Gander | `7664055506831394858` |
| Coffee & Vinyl - Emi Izumi | `7629028310059599882` |
| Late Night Loops - Chuckles the Band | `7656790142947297289` |
| Sci-fi ambient with a desolate and lonely - harryfaoki | `7223823859698894850` |
| MILLION DOLLAR BABY (VHS) - Tommy Richman | `7362317730454308880` |

Any of these can be passed to `photo --music`. If a different one is wanted,
find the id with `sounds` or `music` and pass that instead.

### Verifying the domain

Photo posts pull the images from a URL, so TikTok has to trust that the URL
belongs to you. Until the domain is verified, every photo post fails with
`url_ownership_unverified`, and no amount of retrying helps.

There are two ways to verify, and either one works:

**A domain** covers the whole host and every path under it. TikTok asks you to
add a signature string to the domain's DNS records, in a TXT record.

**A URL prefix** covers one exact path. It is `https://` + host + path + `/`,
and it must be a real domain, not an IP address. TikTok gives you a
verification file to upload to that prefix, then you press **Verify** in the
portal.

The portal hands out a file named `tiktok<token>.txt` whose content is
`tiktok-developers-site-verification=<token>`. Put that file in the repo at
the prefix path, and the same signature in a meta tag in the page head:

```html
<meta name="tiktok-developers-site-verification" content="<token>">
```

Both shapes are in this repo, so whichever check the portal runs finds one.
The prefix used here is `https://nguyenkieuthinh.github.io/uppost/`, and the
images under `wallpapers/` are served from that same prefix, so they can be
posted straight away.

### What is not settled

A photo post with a sound was uploaded successfully and reached
`SEND_TO_USER_INBOX`, so the field is accepted end to end. But the published
post carries a different sound than the one that was asked for, so the field
is accepted and then ignored. See the section above.

For video, there is no sound field at all. The draft endpoint ignores
`post_info` completely, and `media_type: VIDEO` is rejected by the photo
endpoint, so there is no route to attach music to a video draft through the
API. Set the sound in the app instead.

## Limits and errors

| Message | What it means |
|---------|---------------|
| `spam_risk_too_many_pending_share` | The 5-per-24-hours upload cap was hit. See below for what actually frees a slot. |
| `reached_active_user_cap` | The daily quota for active publishing users of your app was reached. A different limit from the 5-share cap. |
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

A second measurement sharpened this. Ten shares were created inside a
24-hour window, and cancelling six of them did not help: the cap was still
hit with only two left pending, one of which had already been published.
The counter tracks every share that was created, not the ones waiting for
approval, and a slot only comes back when the oldest share drops out of the
24-hour window.

The publish id carries its own timestamp, so the wait can be calculated
without guessing. The top 32 bits are a Unix time:

```bash
python3 -c "import datetime; print(datetime.datetime.fromtimestamp(7698804288848332821 >> 32))"
```

The `quota` command does this for every share and prints the time the next
slot frees.

`uppost.py cancel` prints a line saying cancelling does not free a slot.
That is right, and it is worth keeping in mind before spending a cancel on a
draft you actually want.

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
| `shares.log` | Every share id this tool has made, one per line. The `quota` command reads it. |
| `retry_photo.sh` | Retries one photo post every 20 minutes until the 24-hour cap lets it through. Run it when the cap is in the way. |

## Notes for the future

- The photo command's `photo_cover_index` was `1`, but TikTok counts from `0`.
  It is now `0`, which is the first image.
- Photo posts send the same text as both title and description. They are now
  separate limits, so a long caption is no longer cut short at 90 characters.
- The draft endpoint's silence on `post_info` is worth re-testing if TikTok
  documents captions for video uploads later.
