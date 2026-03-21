# iPhone → Instagram: Complete Setup Guide

This guide walks you through **every tap** to connect your iPhone Camera Roll
to the automation pipeline. You'll end up with two Shortcuts:

1. **"Post to IG"** — one-tap: select media → Claude generates caption → posts to Instagram
2. **"IG Caption"** — generate a caption you can preview/copy without uploading

---

## Part 1: Start the Server (Your Computer)

### 1a. Install & Configure (one-time)

```bash
cd instagram-claude-automation
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Open .env and fill in:
#   IG_USER_ID=your_id
#   ACCESS_TOKEN=your_token
#   ANTHROPIC_API_KEY=sk-ant-...
#   UPLOAD_API_KEY=pick_any_secret_string
```

Setting a permanent `UPLOAD_API_KEY` in `.env` means you won't need to update
your Shortcut every time you restart the server.

### 1b. Start the Server

```bash
python main.py server --auto-post --topic "lifestyle"
```

Output:
```
Starting upload server on http://0.0.0.0:5555
Auto-post: ON
Mock mode: OFF
```

### 1c. Find Your Computer's IP Address

Your iPhone needs to reach the server over Wi-Fi. Find your IP:

```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I | awk '{print $1}'

# Windows
ipconfig | findstr IPv4
```

Example: `192.168.1.42` — you'll use `http://192.168.1.42:5555` in the Shortcuts.

### 1d. Quick Test (from Terminal)

```bash
# Should return {"status":"ok",...}
curl http://192.168.1.42:5555/health
```

---

## Part 2: Create "Post to IG" Shortcut (One-Tap Posting)

Open the **Shortcuts** app on your iPhone. Tap **+** in the top right.

### Action 1: Receive Input

1. Tap the text at the very top that says **"Any"** (or **"Shortcut Input"**)
2. Change it to: **Receive [Images and Media] from [Share Sheet]**
   - Tap "Any" → uncheck all except **Images** and **Media**

### Action 2: Ask for Topic

1. Tap **+ Add Action** → search **"Ask for Input"**
2. Configure:
   - Question: `What's this post about?`
   - Input Type: **Text**
   - Default Answer: `lifestyle` (or whatever your default is)

### Action 3: Upload to Server

1. Tap **+ Add Action** → search **"Get Contents of URL"**
2. Configure:
   - **URL**: `http://YOUR_IP:5555/shortcut/upload-and-post`
   - Tap **Show More**
   - **Method**: POST
   - **Headers**: Add header:
     - Key: `X-API-Key`
     - Value: `your_upload_api_key` (from your `.env`)
   - **Request Body**: **Form**
   - Add these form fields:
     - `file` → tap value → select **Shortcut Input** (the media)
     - `topic` → tap value → select **Provided Input** (from Ask for Input)
     - `confirm` → type `true`
     - `post_type` → type `reel` (or `auto` to let server decide)

### Action 4: Show Result

1. Tap **+ Add Action** → search **"Get Dictionary Value"**
2. Get **Value** for key `message` in **Contents of URL**
3. Tap **+ Add Action** → search **"Show Alert"** (or **"Show Notification"**)
4. Set text to the **Dictionary Value** from the previous step

### Final Steps

1. Tap the shortcut name at the top → rename to **"Post to IG"**
2. Tap the **settings icon** (ⓘ) at the top
3. Enable **"Show in Share Sheet"**
4. Under **Share Sheet Types**: select **Images** and **Media**
5. Tap **Done**

### How to Use

1. Open **Photos** → find a video or photo
2. Tap **Share** (the box-with-arrow icon)
3. Scroll down → tap **"Post to IG"**
4. Type what it's about (e.g., "morning workout") or accept the default
5. Wait ~10 seconds → notification shows "Reel posted! Caption: ..."

---

## Part 3: Create "IG Caption" Shortcut (Caption Generator)

This shortcut generates a caption you can preview, copy, and paste into
Instagram manually. No media upload needed.

### Action 1: Ask for Topic

1. **+ Add Action** → **"Ask for Input"**
2. Question: `What's the caption about?`
3. Input Type: **Text**

### Action 2: Get Caption from Server

1. **+ Add Action** → **"Get Contents of URL"**
2. URL: `http://YOUR_IP:5555/shortcut/caption`
3. Method: **POST**
4. Headers: `X-API-Key` → `your_key`
5. Request Body: **Form**
   - `topic` → **Provided Input**
   - `with_hashtags` → `true`

### Action 3: Extract and Show

1. **+ Add Action** → **"Get Dictionary Value"**
   - Key: `full_caption`
   - Dictionary: **Contents of URL**
2. **+ Add Action** → **"Quick Look"**
   - Input: **Dictionary Value** (shows the caption as a preview)
3. **+ Add Action** → **"Copy to Clipboard"**
   - Input: **Dictionary Value**
4. **+ Add Action** → **"Show Notification"**
   - Title: "Caption copied!"

### How to Use

1. Open **Shortcuts** → tap **"IG Caption"**
2. Type your topic → tap Done
3. Preview appears → dismiss it
4. Caption is copied to clipboard → paste anywhere

---

## Part 4: Create "Batch Upload" Shortcut (Multiple Photos)

For uploading an entire album or selection of photos:

### Action 1: Find Photos

1. **+ Add Action** → **"Find Photos"**
2. Add Filter: **Album** is **[pick your album]**
3. Sort by: **Creation Date**, **Latest First**
4. Limit: **10** (adjust as needed)

### Action 2: Loop and Upload

1. **+ Add Action** → **"Repeat with Each"**
   - Input: **Photos**
2. Inside the repeat block:
   - **+ Add Action** → **"Get Contents of URL"**
   - URL: `http://YOUR_IP:5555/upload`
   - Method: **POST**
   - Headers: `X-API-Key` → `your_key`
   - Body Form:
     - `file` → **Repeat Item**
     - `topic` → `batch upload`

### Action 3: Done

1. **+ Add Action** → **"Show Notification"**
2. Text: `Uploaded photos to inbox!`

Files land in the `media_inbox/` folder. Post them individually later:
```bash
python main.py --type reel --file media_inbox/FILE.mp4 --topic "my day"
```

---

## Part 5: Making It Work From Anywhere

By default, the server only works when your iPhone and computer are on the
**same Wi-Fi network**. Here's how to make it work from anywhere:

### Option A: Tailscale (Recommended)

Free, secure, no port forwarding needed.

1. Install **Tailscale** on your Mac/PC: [tailscale.com/download](https://tailscale.com/download)
2. Install **Tailscale** on your iPhone from the App Store
3. Sign in with the same account on both
4. Your computer gets a stable IP like `100.64.0.2`
5. Update your Shortcuts to use `http://100.64.0.2:5555/...`

Works from any network — cellular, coffee shop WiFi, etc.

### Option B: ngrok

```bash
ngrok http 5555
```

Gives you a URL like `https://abc123.ngrok-free.app` — use that in Shortcuts.
Downside: URL changes each restart (pay $8/mo for a fixed one).

### Option C: Cloudflare Tunnel

```bash
cloudflared tunnel --url http://localhost:5555
```

Free, stable, but slightly more setup.

---

## Part 6: Full Workflow Example

Here's the complete flow from iPhone to Instagram:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌───────────┐
│   iPhone     │     │  Your Server │     │   Claude     │     │ Instagram │
│  Camera Roll │────▶│  (port 5555) │────▶│  (Anthropic) │────▶│ Graph API │
│              │     │              │     │              │     │           │
│ Share Sheet  │     │ Saves file   │     │ Generates    │     │ Creates   │
│ "Post to IG" │     │ to inbox     │     │ caption +    │     │ container │
│              │     │              │     │ hashtags     │     │ Publishes │
└─────────────┘     └──────────────┘     └─────────────┘     └───────────┘
       │                    │                    │                    │
       │    HTTP POST       │   API call         │   API calls       │
       │    with media      │   with topic       │   with video +    │
       │    + topic         │                    │   caption         │
       └────────────────────┴────────────────────┴────────────────────┘
                              ~15 seconds total
```

### End-to-End Test (Mock Mode First)

Start server in mock mode:
```bash
python main.py server --auto-post --mock --no-auth
```

Test from another terminal:
```bash
# Create a dummy video
echo "fake" > /tmp/test.mp4

# Upload it
curl -X POST http://localhost:5555/shortcut/upload-and-post \
  -F "file=@/tmp/test.mp4" \
  -F "topic=test post" \
  -F "confirm=true"
```

Expected response:
```json
{
  "status": "posted",
  "caption": "[MOCK] This is a mock Claude response for testing.",
  "media_id": "mock_media_id",
  "message": "[MOCK] Reel posted about 'test post'!"
}
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Shortcut says "Could not connect" | Server not running, or wrong IP. Check `curl http://IP:5555/health` |
| "401 Unauthorized" | Wrong API key in Shortcut header. Check `.env` UPLOAD_API_KEY |
| Shortcut hangs for >30s | Video too large or server still processing. Check server terminal |
| "Unsupported file type" | iPhone sent HEIC — the server accepts it. Check the file extension |
| Works on WiFi but not cellular | Need Tailscale/ngrok. See Part 5 above |
| Server crashed | Check terminal for error. Restart with `python main.py server --auto-post` |

## API Endpoints Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/upload` | POST | Upload single file to inbox |
| `/upload/batch` | POST | Upload multiple files |
| `/inbox` | GET | List files in inbox |
| `/inbox/post/<file>` | POST | Post an inbox file to IG |
| `/inbox/generate-caption` | POST | Generate caption only |
| `/shortcut/upload-and-post` | POST | iOS Shortcut: upload + caption + post |
| `/shortcut/caption` | POST | iOS Shortcut: generate caption text |
