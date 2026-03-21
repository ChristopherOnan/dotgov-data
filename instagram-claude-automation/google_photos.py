"""
Google Photos API integration — pulls photos/videos from your Google Photos
library (backed up via Google One) for posting to Instagram.

This module lets you:
  - List recent media items from your Google Photos library
  - Search by date range, album, or content category
  - Download media to the local inbox for posting
  - Auto-sync new uploads on a schedule

Prerequisites:
  1. Enable the Google Photos Library API in Google Cloud Console
  2. Create OAuth 2.0 credentials (Desktop app type)
  3. Download credentials.json to this project directory
  4. First run will open a browser for OAuth consent

Docs: https://developers.google.com/photos/library/guides/overview
"""

import json
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

# Google Photos API base URL
GPHOTOS_API = "https://photoslibrary.googleapis.com/v1"

# Token storage
TOKEN_FILE = Path(__file__).resolve().parent / ".google_token.json"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.json"

MEDIA_INBOX = config.UPLOAD_DIR
MEDIA_INBOX.mkdir(exist_ok=True)

# Scopes needed for read-only access to the photo library
SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]


# ---------------------------------------------------------------------------
# OAuth 2.0 token management
# ---------------------------------------------------------------------------

def _load_credentials() -> dict:
    """Load OAuth client credentials from credentials.json."""
    if not CREDENTIALS_FILE.is_file():
        raise FileNotFoundError(
            f"Missing {CREDENTIALS_FILE}. Download it from Google Cloud Console:\n"
            "  1. Go to https://console.cloud.google.com/apis/credentials\n"
            "  2. Create an OAuth 2.0 Client ID (Desktop app)\n"
            "  3. Download JSON and save as 'credentials.json' in the project root."
        )
    with open(CREDENTIALS_FILE) as f:
        data = json.load(f)
    # Handle both "installed" and "web" credential types
    return data.get("installed", data.get("web", data))


def _load_token() -> Optional[dict]:
    """Load saved OAuth token from disk."""
    if TOKEN_FILE.is_file():
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None


def _save_token(token: dict) -> None:
    """Save OAuth token to disk."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f, indent=2)
    logger.info("Token saved to %s", TOKEN_FILE)


def _token_expired(token: dict) -> bool:
    """Check if the access token has expired."""
    expires_at = token.get("expires_at", 0)
    return time.time() >= expires_at - 60  # 60s buffer


def _refresh_token(token: dict, creds: dict) -> dict:
    """Refresh an expired access token."""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    new_data = resp.json()
    token["access_token"] = new_data["access_token"]
    token["expires_at"] = time.time() + new_data.get("expires_in", 3600)
    _save_token(token)
    logger.info("Token refreshed.")
    return token


def authorize() -> dict:
    """
    Full OAuth 2.0 authorization flow.

    First run: opens a browser for consent → saves token.
    Subsequent runs: loads and refreshes the saved token.

    Returns a dict with 'access_token'.
    """
    creds = _load_credentials()
    token = _load_token()

    if token and not _token_expired(token):
        return token

    if token and token.get("refresh_token"):
        return _refresh_token(token, creds)

    # First-time authorization — manual flow for CLI
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={creds['client_id']}&"
        f"redirect_uri=urn:ietf:wg:oauth:2.0:oob&"
        f"response_type=code&"
        f"scope={'%20'.join(SCOPES)}&"
        f"access_type=offline&"
        f"prompt=consent"
    )

    print("\n" + "=" * 60)
    print("GOOGLE PHOTOS AUTHORIZATION")
    print("=" * 60)
    print(f"\n1. Open this URL in your browser:\n\n   {auth_url}\n")
    print("2. Sign in and grant access to your Google Photos.")
    print("3. Copy the authorization code and paste it below.\n")

    auth_code = input("Authorization code: ").strip()

    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": auth_code,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    token["expires_at"] = time.time() + token.get("expires_in", 3600)
    _save_token(token)
    print("Authorization successful! Token saved.\n")
    return token


def _headers(token: dict) -> dict:
    return {"Authorization": f"Bearer {token['access_token']}"}


# ---------------------------------------------------------------------------
# Google Photos API operations
# ---------------------------------------------------------------------------

def list_media(
    token: dict,
    page_size: int = 25,
    page_token: str = "",
) -> dict:
    """
    List recent media items from the Google Photos library.

    Returns dict with 'mediaItems' list and optional 'nextPageToken'.
    """
    if config.MOCK_MODE:
        return {"mediaItems": [
            {"id": "mock_1", "filename": "photo1.jpg", "mimeType": "image/jpeg",
             "mediaMetadata": {"creationTime": "2026-03-20T12:00:00Z"},
             "baseUrl": "https://mock.photos/1"},
            {"id": "mock_2", "filename": "video1.mp4", "mimeType": "video/mp4",
             "mediaMetadata": {"creationTime": "2026-03-20T13:00:00Z"},
             "baseUrl": "https://mock.photos/2"},
        ]}

    params = {"pageSize": page_size}
    if page_token:
        params["pageToken"] = page_token

    resp = requests.get(
        f"{GPHOTOS_API}/mediaItems",
        headers=_headers(token),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def search_media(
    token: dict,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    content_filter: Optional[list[str]] = None,
    page_size: int = 25,
) -> dict:
    """
    Search media items by date range and/or content category.

    Args:
        start_date: Start of date range.
        end_date: End of date range.
        content_filter: List of categories like "LANDSCAPES", "SELFIES", "PETS".
        page_size: Items per page (max 100).
    """
    if config.MOCK_MODE:
        return list_media(token)

    body: dict = {"pageSize": page_size}
    filters: dict = {}

    if start_date or end_date:
        date_filter = {}
        if start_date and end_date:
            date_filter["ranges"] = [{
                "startDate": {"year": start_date.year, "month": start_date.month, "day": start_date.day},
                "endDate": {"year": end_date.year, "month": end_date.month, "day": end_date.day},
            }]
        filters["dateFilter"] = date_filter

    if content_filter:
        filters["contentFilter"] = {
            "includedContentCategories": content_filter
        }

    if filters:
        body["filters"] = filters

    resp = requests.post(
        f"{GPHOTOS_API}/mediaItems:search",
        headers=_headers(token),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def list_albums(token: dict, page_size: int = 50) -> dict:
    """List all albums in the Google Photos library."""
    if config.MOCK_MODE:
        return {"albums": [
            {"id": "album_1", "title": "Camera Roll", "mediaItemsCount": "42"},
            {"id": "album_2", "title": "Instagram Queue", "mediaItemsCount": "10"},
        ]}

    resp = requests.get(
        f"{GPHOTOS_API}/albums",
        headers=_headers(token),
        params={"pageSize": page_size},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_album_media(token: dict, album_id: str, page_size: int = 25) -> dict:
    """Get media items from a specific album."""
    if config.MOCK_MODE:
        return list_media(token)

    resp = requests.post(
        f"{GPHOTOS_API}/mediaItems:search",
        headers=_headers(token),
        json={"albumId": album_id, "pageSize": page_size},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Download media to local inbox
# ---------------------------------------------------------------------------

def download_media_item(token: dict, item: dict, dest_dir: Path = MEDIA_INBOX) -> Path:
    """
    Download a single media item to the local inbox.

    Google Photos baseUrl requires appending =d for download, =dv for video.
    """
    dest_dir.mkdir(exist_ok=True)
    filename = item.get("filename", f"media_{item['id']}")
    dest = dest_dir / filename

    if dest.exists():
        logger.info("Already downloaded: %s", filename)
        return dest

    base_url = item["baseUrl"]
    mime = item.get("mimeType", "")

    # Append download parameters
    if "video" in mime:
        download_url = f"{base_url}=dv"  # download video
    else:
        download_url = f"{base_url}=d"  # download full resolution

    if config.MOCK_MODE:
        dest.write_bytes(b"mock media content")
        logger.info("[MOCK] Downloaded: %s", filename)
        return dest

    logger.info("Downloading: %s", filename)
    resp = requests.get(download_url, headers=_headers(token), stream=True, timeout=120)
    resp.raise_for_status()

    with open(dest, "wb") as f:
        shutil.copyfileobj(resp.raw, f)

    logger.info("Downloaded: %s (%d bytes)", filename, dest.stat().st_size)
    return dest


def sync_recent(
    token: dict,
    hours: int = 24,
    max_items: int = 50,
) -> list[Path]:
    """
    Download all media from the last N hours to the local inbox.

    This is the main function for daily Google One sync integration.
    Call it on a schedule (e.g., cron) to pull new photos/videos.

    Returns list of downloaded file paths.
    """
    end = datetime.now()
    start = end - timedelta(hours=hours)

    logger.info("Syncing media from %s to %s", start.isoformat(), end.isoformat())
    result = search_media(token, start_date=start, end_date=end, page_size=max_items)

    items = result.get("mediaItems", [])
    logger.info("Found %d media items in the last %d hours.", len(items), hours)

    downloaded = []
    for item in items:
        try:
            path = download_media_item(token, item)
            downloaded.append(path)
        except Exception as e:
            logger.error("Failed to download %s: %s", item.get("filename"), e)

    return downloaded


# ---------------------------------------------------------------------------
# CLI-friendly functions
# ---------------------------------------------------------------------------

def sync_and_report(hours: int = 24) -> None:
    """Sync recent media and print a summary."""
    token = authorize()
    files = sync_recent(token, hours=hours)
    print(f"\nSynced {len(files)} files to {MEDIA_INBOX}:")
    for f in files:
        print(f"  - {f.name} ({f.stat().st_size / 1024:.0f} KB)")


def browse_library(page_size: int = 10) -> list[dict]:
    """List recent media items interactively."""
    token = authorize()
    result = list_media(token, page_size=page_size)
    items = result.get("mediaItems", [])
    print(f"\nRecent {len(items)} media items:")
    for i, item in enumerate(items):
        created = item.get("mediaMetadata", {}).get("creationTime", "?")
        mime = item.get("mimeType", "?")
        print(f"  {i+1}. {item.get('filename', '?')} ({mime}) — {created}")
    return items


def browse_albums() -> list[dict]:
    """List all albums."""
    token = authorize()
    result = list_albums(token)
    albums = result.get("albums", [])
    print(f"\nYour albums ({len(albums)}):")
    for a in albums:
        count = a.get("mediaItemsCount", "?")
        print(f"  - {a.get('title', '?')} ({count} items) [ID: {a['id']}]")
    return albums
