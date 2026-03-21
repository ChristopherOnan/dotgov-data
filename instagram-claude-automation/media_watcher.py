"""
Media folder watcher — monitors a directory for new photos/videos and
optionally auto-posts them to Instagram.

Works with:
  - iCloud Photos sync folder (~/Library/Mobile Documents/com~apple~CloudDocs/Photos)
  - Any folder synced from your iPhone (Dropbox, Google Drive, OneDrive)
  - Manual file drops

Usage:
  python media_watcher.py --watch-dir ~/icloud_photos --topic "travel"
  python media_watcher.py --watch-dir ./media_inbox --auto-post --mock
"""

import argparse
import logging
import time
from pathlib import Path
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

import config
import claude_helper
import instagram_poster
from utils import InstagramAPIError

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".webp",  # images
    ".mp4", ".mov", ".m4v",                       # videos
}


def _is_media(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".m4v"}


class MediaHandler(FileSystemEventHandler):
    """Handles new media files appearing in the watched directory."""

    def __init__(self, topic: str, auto_post: bool, post_type: str):
        self.topic = topic
        self.auto_post = auto_post
        self.post_type = post_type
        self.processed: set[str] = set()

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        if not _is_media(path):
            return

        # Skip duplicates (watchdog can fire multiple events)
        if str(path) in self.processed:
            return
        self.processed.add(str(path))

        # Wait for file to finish writing
        self._wait_for_stable(path)

        media_type = "video" if _is_video(path) else "image"
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info("New %s detected: %s (%.1f MB)", media_type, path.name, size_mb)
        print(f"\n[NEW] {media_type.upper()}: {path.name} ({size_mb:.1f} MB)")

        if self.auto_post:
            self._handle_auto_post(path, media_type)
        else:
            print(f"  Queued in: {path}")
            print(f"  To post manually: python main.py --type reel --file '{path}' --topic '{self.topic}'")

    def _wait_for_stable(self, path: Path, checks: int = 3, interval: float = 1.0) -> None:
        """Wait until the file size stops changing (finished copying)."""
        prev_size = -1
        stable_count = 0
        for _ in range(30):  # max 30 seconds
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return
            if size == prev_size and size > 0:
                stable_count += 1
                if stable_count >= checks:
                    return
            else:
                stable_count = 0
            prev_size = size
            time.sleep(interval)

    def _handle_auto_post(self, path: Path, media_type: str) -> None:
        """Generate content and post to Instagram."""
        try:
            print(f"  Generating caption for topic: '{self.topic}'...")
            caption = claude_helper.generate_caption(topic=self.topic)
            hashtags = claude_helper.generate_hashtags(topic=self.topic, count=8)
            full_caption = f"{caption}\n\n{hashtags}"
            print(f"  Caption: {caption[:80]}...")

            if media_type == "video" or self.post_type == "reel":
                media_id = instagram_poster.post_reel_local(
                    file_path=str(path), caption=full_caption
                )
                print(f"  POSTED as Reel! Media ID: {media_id}")
            else:
                print(f"  Image queued (stories from local files need URL hosting).")
                print(f"  Use the upload server for direct story posting.")

        except InstagramAPIError as e:
            logger.error("Auto-post failed for %s: %s", path.name, e)
            print(f"  ERROR posting: {e}")
        except Exception as e:
            logger.error("Unexpected error for %s: %s", path.name, e)
            print(f"  ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Watch a folder for new media and optionally auto-post to Instagram."
    )
    parser.add_argument(
        "--watch-dir", "-w",
        required=True,
        help="Directory to watch for new media files.",
    )
    parser.add_argument("--topic", default="lifestyle", help="Default topic for captions.")
    parser.add_argument("--post-type", choices=["reel", "story", "auto"], default="auto")
    parser.add_argument("--auto-post", action="store_true", help="Auto-post new files.")
    parser.add_argument("--mock", action="store_true", help="Enable mock mode.")
    args = parser.parse_args()

    if args.mock:
        config.MOCK_MODE = True

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    watch_dir = Path(args.watch_dir).resolve()
    if not watch_dir.is_dir():
        watch_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created watch directory: {watch_dir}")

    handler = MediaHandler(
        topic=args.topic,
        auto_post=args.auto_post,
        post_type=args.post_type,
    )
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()

    print(f"Watching: {watch_dir}")
    print(f"Auto-post: {'ON' if args.auto_post else 'OFF (queue only)'}")
    print(f"Mock mode: {'ON' if config.MOCK_MODE else 'OFF'}")
    print(f"Topic: {args.topic}")
    print("Press Ctrl+C to stop.\n")

    # Show existing files
    existing = [f for f in watch_dir.iterdir() if _is_media(f)]
    if existing:
        print(f"Existing media in folder: {len(existing)} files")
        for f in existing[:10]:
            print(f"  - {f.name} ({f.stat().st_size / (1024*1024):.1f} MB)")
        if len(existing) > 10:
            print(f"  ... and {len(existing) - 10} more")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nStopped watching.")
    observer.join()


if __name__ == "__main__":
    main()
