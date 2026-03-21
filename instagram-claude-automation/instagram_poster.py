"""
Instagram content publishing module.

Handles creating media containers (Reels, Stories), uploading local files,
polling for readiness, and publishing to Instagram via the Graph API.

Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""

import logging
from typing import Optional

import config
from utils import (
    InstagramAPIError,
    graph_get,
    graph_post,
    is_within_rate_limit,
    poll_container_status,
    resumable_upload,
    validate_caption,
    validate_url,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reel publishing
# ---------------------------------------------------------------------------

def create_reel_container(
    video_url: str,
    caption: str,
    share_to_feed: bool = True,
    thumb_offset: Optional[int] = None,
) -> str:
    """
    Create a Reel media container.

    POST /{ig-user-id}/media
      media_type=REELS
      video_url=...
      caption=...
      share_to_feed=true

    Args:
        video_url: Public HTTPS URL of the video file.
        caption: Full caption text (including hashtags).
        share_to_feed: Also show in the main feed grid.
        thumb_offset: Thumbnail offset in milliseconds.

    Returns:
        The container/creation ID string.

    Raises:
        InstagramAPIError: On API failure.
        ValueError: On invalid inputs.
    """
    caption = validate_caption(caption)
    if not validate_url(video_url):
        raise ValueError(f"Invalid video URL: {video_url}")

    data = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": str(share_to_feed).lower(),
    }
    if thumb_offset is not None:
        data["thumb_offset"] = str(thumb_offset)

    logger.info("Creating Reel container...")
    result = graph_post(f"{config.IG_USER_ID}/media", data=data)
    container_id = result.get("id")
    if not container_id:
        raise InstagramAPIError("No container ID returned from Reel creation.")

    logger.info("Reel container created: %s", container_id)
    return container_id


def create_reel_container_local(
    file_path: str,
    caption: str,
    share_to_feed: bool = True,
) -> str:
    """
    Create a Reel container from a local video file via resumable upload.

    Args:
        file_path: Path to local video file.
        caption: Full caption text.
        share_to_feed: Also show in the main feed grid.

    Returns:
        The container/creation ID string.
    """
    caption = validate_caption(caption)
    container_id = resumable_upload(file_path, media_type="video")

    # Update the container with caption after upload
    graph_post(
        f"{container_id}",
        data={
            "caption": caption,
            "share_to_feed": str(share_to_feed).lower(),
        },
    )

    logger.info("Reel container (local upload) created: %s", container_id)
    return container_id


# ---------------------------------------------------------------------------
# Story publishing
# ---------------------------------------------------------------------------

def create_story_container(
    media_url: str,
    media_type_hint: str = "image",
) -> str:
    """
    Create a Story media container.

    POST /{ig-user-id}/media
      media_type=STORIES
      image_url=... OR video_url=...

    Args:
        media_url: Public HTTPS URL of the image or video.
        media_type_hint: "image" or "video" to pick the right parameter.

    Returns:
        The container/creation ID string.
    """
    if not validate_url(media_url):
        raise ValueError(f"Invalid media URL: {media_url}")

    url_key = "image_url" if media_type_hint == "image" else "video_url"
    data = {
        "media_type": "STORIES",
        url_key: media_url,
    }

    logger.info("Creating Story container (%s)...", media_type_hint)
    result = graph_post(f"{config.IG_USER_ID}/media", data=data)
    container_id = result.get("id")
    if not container_id:
        raise InstagramAPIError("No container ID returned from Story creation.")

    logger.info("Story container created: %s", container_id)
    return container_id


# ---------------------------------------------------------------------------
# Publish (shared for Reels and Stories)
# ---------------------------------------------------------------------------

def publish_container(container_id: str) -> str:
    """
    Publish a media container after it reaches FINISHED status.

    POST /{ig-user-id}/media_publish?creation_id={container_id}

    Args:
        container_id: The creation ID from a media container call.

    Returns:
        The published media ID.

    Raises:
        InstagramAPIError: If rate-limited, container not ready, or publish fails.
    """
    # Check rate limit before publishing
    if not is_within_rate_limit():
        raise InstagramAPIError(
            "Publishing rate limit reached (~100 posts/24h). Try again later."
        )

    # Poll until the container is ready
    logger.info("Waiting for container %s to be ready...", container_id)
    status = poll_container_status(container_id)
    logger.info("Container %s status: %s — publishing.", container_id, status)

    # Publish
    result = graph_post(
        f"{config.IG_USER_ID}/media_publish",
        data={"creation_id": container_id},
    )
    media_id = result.get("id")
    if not media_id:
        raise InstagramAPIError("No media ID returned from publish call.")

    logger.info("Published! Media ID: %s", media_id)
    return media_id


# ---------------------------------------------------------------------------
# Convenience: end-to-end flows
# ---------------------------------------------------------------------------

def post_reel(
    video_url: str,
    caption: str,
    share_to_feed: bool = True,
) -> str:
    """
    Full flow: create Reel container → wait → publish.

    Returns the published media ID.
    """
    container_id = create_reel_container(video_url, caption, share_to_feed)
    return publish_container(container_id)


def post_reel_local(
    file_path: str,
    caption: str,
    share_to_feed: bool = True,
) -> str:
    """
    Full flow: upload local file → create Reel container → wait → publish.

    Returns the published media ID.
    """
    container_id = create_reel_container_local(file_path, caption, share_to_feed)
    return publish_container(container_id)


def post_story(
    media_url: str,
    media_type_hint: str = "image",
) -> str:
    """
    Full flow: create Story container → wait → publish.

    Returns the published media ID.
    """
    container_id = create_story_container(media_url, media_type_hint)
    return publish_container(container_id)
