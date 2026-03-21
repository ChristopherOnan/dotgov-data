"""
Utility helpers for Instagram Graph API interactions.

Handles HTTP requests, token refresh, rate-limit checks, resumable uploads,
and common error handling with retries.

Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

import requests

import config

logger = logging.getLogger(__name__)


class InstagramAPIError(Exception):
    """Raised when the Instagram Graph API returns an error."""

    def __init__(self, message: str, code: int | None = None, subcode: int | None = None):
        self.code = code
        self.subcode = subcode
        super().__init__(message)


# ---------------------------------------------------------------------------
# Core HTTP helpers
# ---------------------------------------------------------------------------

def _params_with_token(params: dict | None = None) -> dict:
    """Inject the access token into request params."""
    p = {"access_token": config.ACCESS_TOKEN}
    if params:
        p.update(params)
    return p


def graph_get(endpoint: str, params: dict | None = None) -> dict:
    """GET request to the Graph API with automatic error handling."""
    url = f"{config.BASE_URL}/{endpoint}"
    logger.debug("GET %s  params=%s", url, params)

    if config.MOCK_MODE:
        logger.info("[MOCK] GET %s", url)
        return {"id": "mock_id", "status_code": "FINISHED"}

    resp = requests.get(url, params=_params_with_token(params), timeout=30)
    return _handle_response(resp)


def graph_post(endpoint: str, data: dict | None = None) -> dict:
    """POST request to the Graph API with automatic error handling."""
    url = f"{config.BASE_URL}/{endpoint}"
    logger.debug("POST %s  data=%s", url, data)

    if config.MOCK_MODE:
        logger.info("[MOCK] POST %s", url)
        return {"id": "mock_container_123"}

    resp = requests.post(url, data=_params_with_token(data), timeout=30)
    return _handle_response(resp)


def _handle_response(resp: requests.Response) -> dict:
    """Parse JSON response and raise on API errors."""
    try:
        body = resp.json()
    except ValueError:
        resp.raise_for_status()
        return {}

    if "error" in body:
        err = body["error"]
        msg = err.get("message", "Unknown error")
        code = err.get("code")
        subcode = err.get("error_subcode")
        logger.error("API error %s (subcode %s): %s", code, subcode, msg)
        raise InstagramAPIError(msg, code=code, subcode=subcode)

    resp.raise_for_status()
    return body


# ---------------------------------------------------------------------------
# Rate-limit check
# ---------------------------------------------------------------------------

def check_publishing_limit() -> dict[str, Any]:
    """
    Check current content-publishing rate limit.

    GET /{ig-user-id}/content_publishing_limit
    Returns quota_usage and related fields.
    Docs: https://developers.facebook.com/docs/instagram-api/reference/ig-user/content_publishing_limit
    """
    data = graph_get(
        f"{config.IG_USER_ID}/content_publishing_limit",
        params={"fields": "quota_usage,config"},
    )
    logger.info("Publishing limit info: %s", data)
    return data


def is_within_rate_limit() -> bool:
    """Return True if we can still publish (< 100 posts in 24h window)."""
    try:
        info = check_publishing_limit()
        usage = info.get("quota_usage", 0)
        return usage < config.PUBLISHING_LIMIT_PER_24H
    except InstagramAPIError:
        logger.warning("Could not check rate limit; proceeding cautiously.")
        return True


# ---------------------------------------------------------------------------
# Token refresh (long-lived token exchange)
# ---------------------------------------------------------------------------

def refresh_long_lived_token() -> str:
    """
    Exchange a valid long-lived token for a new one (extends by 60 days).

    Requires FB_APP_ID and FB_APP_SECRET in config.
    Docs: https://developers.facebook.com/docs/instagram-basic-display-api/guides/long-lived-tokens
    """
    if not config.FB_APP_ID or not config.FB_APP_SECRET:
        raise EnvironmentError(
            "FB_APP_ID and FB_APP_SECRET are required to refresh tokens."
        )

    url = f"https://graph.facebook.com/{config.IG_API_VERSION}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": config.FB_APP_ID,
        "client_secret": config.FB_APP_SECRET,
        "fb_exchange_token": config.ACCESS_TOKEN,
    }
    resp = requests.get(url, params=params, timeout=30)
    body = _handle_response(resp)
    new_token = body.get("access_token", "")
    logger.info("Token refreshed. Expires in %s seconds.", body.get("expires_in"))
    return new_token


# ---------------------------------------------------------------------------
# Container status polling
# ---------------------------------------------------------------------------

def poll_container_status(container_id: str) -> str:
    """
    Poll a media container until it reaches FINISHED, ERROR, or timeout.

    Returns the final status_code string.
    Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing#check-status
    """
    for attempt in range(1, config.STATUS_POLL_MAX_ATTEMPTS + 1):
        data = graph_get(container_id, params={"fields": "status_code,status"})
        status = data.get("status_code", "UNKNOWN")
        logger.info("Container %s status: %s (attempt %d)", container_id, status, attempt)

        if status == "FINISHED":
            return status
        if status == "ERROR":
            detail = data.get("status", "No details")
            raise InstagramAPIError(f"Container {container_id} failed: {detail}")
        if status == "EXPIRED":
            raise InstagramAPIError(f"Container {container_id} expired before publishing.")

        time.sleep(config.STATUS_POLL_INTERVAL)

    raise InstagramAPIError(
        f"Container {container_id} did not finish within "
        f"{config.STATUS_POLL_MAX_ATTEMPTS * config.STATUS_POLL_INTERVAL}s."
    )


# ---------------------------------------------------------------------------
# Resumable upload for local files
# ---------------------------------------------------------------------------

def resumable_upload(file_path: str, media_type: str = "video") -> str:
    """
    Upload a local video file via Facebook's resumable upload endpoint.

    Steps:
      1. Initialize upload session → get upload URL + video_id.
      2. Upload file bytes in a single PUT request.
      3. Return the upload handle / URI to use as video_url.

    Docs: https://developers.facebook.com/docs/video-api/guides/publishing
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = path.stat().st_size
    file_name = path.name
    logger.info("Starting resumable upload for %s (%d bytes)", file_name, file_size)

    if config.MOCK_MODE:
        logger.info("[MOCK] Resumable upload: %s", file_name)
        return "https://mock-upload-url.example.com/video123"

    # Step 1: Initialize
    init_url = f"{config.BASE_URL}/{config.IG_USER_ID}/media"
    init_resp = requests.post(
        init_url,
        data={
            "access_token": config.ACCESS_TOKEN,
            "media_type": "REELS" if media_type == "video" else "STORIES",
            "upload_type": "resumable",
            "caption": "",  # caption set later at publish
        },
        timeout=30,
    )
    init_data = _handle_response(init_resp)
    upload_url = init_data.get("uri")
    container_id = init_data.get("id")

    if not upload_url:
        raise InstagramAPIError("No upload URI returned from init call.")

    logger.info("Upload URI obtained for container %s", container_id)

    # Step 2: Upload file
    headers = {
        "Authorization": f"OAuth {config.ACCESS_TOKEN}",
        "offset": "0",
        "file_size": str(file_size),
    }
    with open(path, "rb") as f:
        upload_resp = requests.post(upload_url, headers=headers, data=f, timeout=300)

    if upload_resp.status_code not in (200, 201):
        raise InstagramAPIError(
            f"Resumable upload failed with status {upload_resp.status_code}: "
            f"{upload_resp.text}"
        )

    logger.info("File uploaded successfully for container %s", container_id)
    return container_id


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_caption(caption: str) -> str:
    """Validate and truncate caption if needed."""
    if len(caption) > config.MAX_CAPTION_LENGTH:
        logger.warning(
            "Caption too long (%d chars), truncating to %d.",
            len(caption),
            config.MAX_CAPTION_LENGTH,
        )
        caption = caption[: config.MAX_CAPTION_LENGTH]
    return caption


def validate_url(url: str) -> bool:
    """Basic URL validation."""
    return url.startswith("https://") or url.startswith("http://")
