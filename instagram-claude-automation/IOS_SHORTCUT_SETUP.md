# iPhone Setup — Connect Your Photo Library

This guide covers **3 methods** to get your iPhone photos/videos into the automation pipeline. Pick the one that fits your workflow.

---

## Method 1: iOS Shortcuts (Recommended — One-Tap Posting)

This creates a **Share Sheet shortcut** so you can select any photo/video in your Camera Roll, tap Share → "Post to Instagram", and it gets uploaded + posted automatically.

### Step 1: Start the Upload Server

On your computer (must be on the same Wi-Fi as your iPhone):

```bash
cd instagram-claude-automation
python upload_server.py --auto-post --topic "my content"
```

Note the **API key** printed on startup and your computer's **local IP** (e.g., `192.168.1.100`).

Find your IP:
```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I | awk '{print $1}'

# Windows
ipconfig | findstr IPv4
```

### Step 2: Create the iOS Shortcut

1. Open the **Shortcuts** app on your iPhone
2. Tap **+** to create a new shortcut
3. Add these actions in order:

#### Action 1: "Receive" input
- Tap **"Any"** at the top → select **"Receive Media from Share Sheet"**
- Accept: **Images, Media**

#### Action 2: "Get Details of Images"
(This gets the file data)

#### Action 3: "Get Contents of URL" (this is the HTTP request)
- **URL**: `http://YOUR_COMPUTER_IP:5555/upload`
- **Method**: POST
- **Headers**:
  - Key: `X-API-Key` → Value: `YOUR_API_KEY_FROM_SERVER`
- **Request Body**: Form
  - Key: `file` → Value: **Shortcut Input** (tap the variable)
  - Key: `topic` → Value: `my content` (or use "Ask Each Time")
  - Key: `auto_post` → Value: `true`

#### Action 4: "Show Result"
- Input: **Contents of URL** (the response)

4. Name it **"Post to Instagram"**
5. Tap the **settings icon** → Enable **"Show in Share Sheet"**
6. Limit to: **Images, Media**

### Step 3: Use It

1. Open **Photos** app
2. Select one or more photos/videos
3. Tap **Share** → scroll down → **"Post to Instagram"**
4. Done! Claude generates the caption and it posts automatically.

### Batch Upload Shortcut (Multiple Files)

For uploading your whole camera roll or albums, create a second shortcut:

#### Action 1: "Find Photos"
- Add filter: **Album is [your album]** (or no filter for all)
- Sort by: Date Taken, Latest First
- Limit: 10 (adjust as needed)

#### Action 2: "Repeat with Each" (loop over photos)
- Inside the loop:
  - **"Get Contents of URL"**
    - URL: `http://YOUR_IP:5555/upload`
    - Method: POST
    - Headers: `X-API-Key: YOUR_KEY`
    - Body Form: `file` = Repeat Item, `topic` = your topic

#### Action 3: "Show Notification"
- "Uploaded X photos!"

---

## Method 2: iCloud Photos Sync + Folder Watcher

If you want **automatic, hands-free syncing** of your entire photo library:

### macOS Setup

1. Enable **iCloud Photos** on your iPhone (Settings → [Your Name] → iCloud → Photos)
2. On your Mac, enable iCloud Photos in **System Settings → Apple ID → iCloud → Photos**
3. Photos sync to: `~/Pictures/Photos Library.photoslibrary`

For a **simpler folder approach**, use iCloud Drive:
- Create a folder in Files app: `iCloud Drive/InstaQueue/`
- That syncs to: `~/Library/Mobile Documents/com~apple~CloudDocs/InstaQueue/`

4. Run the watcher:

```bash
python media_watcher.py \
  --watch-dir ~/Library/Mobile\ Documents/com~apple~CloudDocs/InstaQueue/ \
  --auto-post \
  --topic "my content"
```

### Any Platform (Dropbox/Google Drive/OneDrive)

1. Install the sync client on both iPhone and computer
2. Set up a shared folder (e.g., `Dropbox/InstaQueue/`)
3. On iPhone, save/move photos to that folder
4. Run the watcher on your computer:

```bash
python media_watcher.py \
  --watch-dir ~/Dropbox/InstaQueue/ \
  --auto-post \
  --topic "travel"
```

### How the Watcher Works

- Monitors the folder for new files
- Waits for the file to finish syncing (stable file size)
- Generates a Claude-powered caption
- Uploads and posts to Instagram as a Reel (videos) or queues (images)

---

## Method 3: AirDrop + Manual Post

Simplest approach, no server needed:

1. AirDrop photos/videos from iPhone to your Mac
2. They land in `~/Downloads/`
3. Post directly:

```bash
python main.py --type reel --file ~/Downloads/my_video.mp4 --topic "day in my life"
```

Or watch the Downloads folder:

```bash
python media_watcher.py --watch-dir ~/Downloads --topic "lifestyle"
```

---

## Method Comparison

| Feature | Shortcuts (1) | Folder Sync (2) | AirDrop (3) |
|---------|:---:|:---:|:---:|
| One-tap from iPhone | Yes | No (auto) | No |
| Batch upload | Yes | Yes | Manual |
| Auto-posting | Yes | Yes | No |
| Works over internet | With port forwarding | With cloud sync | No |
| Setup difficulty | Medium | Easy | None |
| Needs server running | Yes | Yes | No |

---

## Making It Work Over the Internet (Optional)

By default, the upload server only works on your local network. To access it from anywhere:

### Option A: Tailscale (Recommended — Free & Secure)
1. Install Tailscale on your computer and iPhone
2. Both devices get a stable IP on your Tailscale network
3. Use the Tailscale IP in your shortcut (e.g., `http://100.x.x.x:5555/upload`)

### Option B: ngrok (Quick & Easy)
```bash
ngrok http 5555
```
Use the ngrok URL in your shortcut (e.g., `https://abc123.ngrok.io/upload`).
Note: URL changes each time unless you pay for a static domain.

### Option C: Cloudflare Tunnel (Free & Stable)
```bash
cloudflared tunnel --url http://localhost:5555
```

---

## Security Notes

- The upload server generates a random **API key** on each start — save it
- Set a permanent key in `.env`: `UPLOAD_API_KEY=your_chosen_key`
- Never expose the server to the internet without authentication
- Use HTTPS in production (Tailscale/ngrok handle this automatically)
- The server validates file types and sizes before accepting uploads
