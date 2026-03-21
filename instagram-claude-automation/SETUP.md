# Instagram Claude Automation — Setup Guide

## Prerequisites

- Python 3.10+
- An Instagram **Business** or **Creator** account
- A Facebook Page connected to your Instagram account
- A Meta (Facebook) Developer App
- An Anthropic API key

## Step 1: Meta App & Permissions

1. Go to [Meta for Developers](https://developers.facebook.com/) and create an app (type: **Business**).
2. Add the **Instagram Graph API** product to your app.
3. Under **App Review**, request these permissions:
   - `instagram_business_content_publish`
   - `instagram_business_basic`
   - `pages_show_list`
   - `pages_read_engagement`
4. Generate a **Page Access Token** in the Graph API Explorer with the permissions above.

## Step 2: Get Your Instagram User ID

Using the Graph API Explorer or curl:

```bash
curl "https://graph.facebook.com/v22.0/me?fields=instagram_business_account&access_token=YOUR_TOKEN"
```

The response will include `instagram_business_account.id` — that's your `IG_USER_ID`.

## Step 3: Get a Long-Lived Token

Short-lived tokens expire in ~1 hour. Exchange for a long-lived token (~60 days):

```bash
curl "https://graph.facebook.com/v22.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=YOUR_APP_ID&\
client_secret=YOUR_APP_SECRET&\
fb_exchange_token=YOUR_SHORT_LIVED_TOKEN"
```

Save the returned `access_token` as your `ACCESS_TOKEN`.

## Step 4: Anthropic API Key

1. Sign up at [console.anthropic.com](https://console.anthropic.com/).
2. Create an API key and save it as `ANTHROPIC_API_KEY`.

## Step 5: Project Setup

```bash
cd instagram-claude-automation

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env with your real values
```

## Step 6: Test (Mock Mode)

Run the test suite with mock mode — no real API calls:

```bash
python -m pytest tests/ -v
```

Try the CLI in mock mode:

```bash
python main.py --type reel --video-url https://example.com/video.mp4 --topic "test" --mock -v
python main.py --generate-only --topic "fitness tips" --mock
```

## Step 7: Post for Real

```bash
# Generate content + post a Reel
python main.py --type reel \
  --video-url https://your-hosted-video.com/reel.mp4 \
  --topic "morning routine" \
  --audience "productivity enthusiasts" \
  --tone "energetic and motivational"

# Post a Story from an image URL
python main.py --type story --image-url https://your-hosted-image.com/photo.jpg

# Upload a local video as a Reel
python main.py --type reel --file ./my_video.mp4 --topic "day in my life"

# Only generate content (no posting)
python main.py --generate-only --topic "healthy eating" --audience "beginners"

# Interactive Claude chat
python main.py --interactive
```

## Video Requirements

- **Reels**: 3-90 seconds, MP4, H.264 codec, AAC audio, max 1GB
- **Stories**: Up to 60 seconds for video, or a single image (JPEG/PNG)
- Video URL must be publicly accessible via HTTPS

## Rate Limits

- ~100 posts per 24-hour rolling window
- The tool checks `/content_publishing_limit` before publishing
- Container creation and publishing are separate calls

## Troubleshooting

| Error | Fix |
|-------|-----|
| `OAuthException` | Token expired — refresh it (see Step 3) |
| `INVALID_MEDIA` | Video URL not accessible or wrong format |
| `EXPIRED` container | Took too long to publish — retry faster |
| Rate limit exceeded | Wait 24h or check `content_publishing_limit` |
| `190` error code | Invalid/expired access token |
