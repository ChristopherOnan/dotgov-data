#!/usr/bin/env python3
"""
Instagram Claude Automation — CLI entry point.

Usage examples:
  # Post a Reel with Claude-generated caption
  python main.py --type reel --video-url https://example.com/video.mp4 --topic "morning routine"

  # Post a Reel from a local file
  python main.py --type reel --file ./my_video.mp4 --topic "day in my life"

  # Post a Story
  python main.py --type story --image-url https://example.com/photo.jpg

  # Generate content only (no posting)
  python main.py --generate-only --topic "fitness tips" --audience "gym beginners"

  # Interactive Claude prompt
  python main.py --interactive

  # Dry run (mock mode, no real API calls)
  python main.py --type reel --video-url https://example.com/v.mp4 --topic "test" --mock

  # Sync from Google Photos (Google One backup) and auto-post
  python main.py sync --hours 24 --auto-post --topic "my day"

  # Browse your Google Photos library
  python main.py sync --browse --count 20

  # Start the upload server (receive files from iPhone)
  python main.py server --port 5555 --auto-post --topic "lifestyle"

  # Watch a folder for new media (iCloud sync, Dropbox, etc.)
  python main.py watch --watch-dir ~/icloud_photos --auto-post --topic "travel"
"""

import argparse
import logging
import sys

import config
import claude_helper
import instagram_poster
from utils import InstagramAPIError


def setup_logging(verbose: bool = False) -> None:
    """Configure logging based on config and verbose flag."""
    level = logging.DEBUG if verbose else getattr(logging, config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def build_caption(args: argparse.Namespace) -> str:
    """Generate caption + hashtags using Claude, or use a custom caption."""
    if args.caption:
        caption = args.caption
        print(f"Using custom caption ({len(caption)} chars).")
    else:
        topic = args.topic or "general lifestyle content"
        audience = args.audience or "general"
        tone = args.tone or "engaging and authentic"

        print(f"Generating caption with Claude for topic: '{topic}'...")
        caption = claude_helper.generate_caption(
            topic=topic, audience=audience, tone=tone
        )
        print(f"Caption generated ({len(caption)} chars):\n{caption}\n")

    # Generate and append hashtags
    if not args.no_hashtags:
        topic = args.topic or "lifestyle"
        count = args.hashtag_count or 10
        print(f"Generating {count} hashtags...")
        hashtags = claude_helper.generate_hashtags(topic=topic, count=count)
        print(f"Hashtags: {hashtags}\n")
        caption = f"{caption}\n\n{hashtags}"

    return caption


def handle_reel(args: argparse.Namespace) -> None:
    """Handle Reel posting flow."""
    caption = build_caption(args)

    if args.file:
        print(f"Uploading local file: {args.file}")
        media_id = instagram_poster.post_reel_local(
            file_path=args.file,
            caption=caption,
            share_to_feed=not args.no_feed,
        )
    elif args.video_url:
        print(f"Using video URL: {args.video_url}")
        media_id = instagram_poster.post_reel(
            video_url=args.video_url,
            caption=caption,
            share_to_feed=not args.no_feed,
        )
    else:
        print("Error: --video-url or --file is required for Reels.", file=sys.stderr)
        sys.exit(1)

    print(f"Reel published successfully! Media ID: {media_id}")


def handle_story(args: argparse.Namespace) -> None:
    """Handle Story posting flow."""
    media_url = args.image_url or args.video_url
    if not media_url:
        print("Error: --image-url or --video-url required for Stories.", file=sys.stderr)
        sys.exit(1)

    media_type = "video" if args.video_url else "image"

    # Optionally generate story text
    if args.topic:
        print("Generating story text overlay...")
        story_text = claude_helper.generate_story_text(topic=args.topic)
        print(f"Story text: {story_text}\n")

    media_id = instagram_poster.post_story(
        media_url=media_url,
        media_type_hint=media_type,
    )
    print(f"Story published successfully! Media ID: {media_id}")


def handle_generate_only(args: argparse.Namespace) -> None:
    """Generate content with Claude without posting."""
    topic = args.topic or "general lifestyle"
    audience = args.audience or "general"
    tone = args.tone or "engaging and authentic"

    print("=" * 60)
    print("CONTENT GENERATION (no posting)")
    print("=" * 60)

    print("\n--- Caption ---")
    caption = claude_helper.generate_caption(topic=topic, audience=audience, tone=tone)
    print(caption)

    print("\n--- Hashtags ---")
    hashtags = claude_helper.generate_hashtags(topic=topic)
    print(hashtags)

    print("\n--- Reel Script (30s) ---")
    script = claude_helper.generate_reel_script(topic=topic)
    print(script)

    print("\n--- Story Text ---")
    story = claude_helper.generate_story_text(topic=topic)
    print(story)

    print("\n--- Alt Text ---")
    alt = claude_helper.generate_alt_text(topic=topic)
    print(alt)

    print("\n" + "=" * 60)


def handle_interactive() -> None:
    """Interactive Claude prompt loop."""
    print("Instagram Claude Assistant — Interactive Mode")
    print("Type your prompt and press Enter. Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        response = claude_helper.interactive_prompt(user_input)
        print(f"\nClaude: {response}\n")


def handle_server(args: argparse.Namespace) -> None:
    """Start the Flask upload server for iPhone integration."""
    import upload_server
    upload_server.AUTO_POST = args.auto_post
    upload_server.DEFAULT_TOPIC = args.topic or "lifestyle"
    if args.no_auth:
        upload_server.UPLOAD_API_KEY = ""
    elif not upload_server.UPLOAD_API_KEY:
        key = upload_server._generate_api_key()
        upload_server.UPLOAD_API_KEY = key
        print(f"\nUPLOAD API KEY: {key}\n")

    print(f"Starting upload server on http://{args.host}:{args.port}")
    upload_server.app.run(host=args.host, port=args.port, debug=False)


def handle_sync(args: argparse.Namespace) -> None:
    """Sync media from Google Photos (Google One backup)."""
    import google_photos

    if args.list_albums:
        google_photos.browse_albums()
        return

    if args.browse:
        google_photos.browse_library(page_size=args.count)
        return

    # Default: sync recent media
    print(f"Syncing last {args.hours}h of media from Google Photos...")
    google_photos.sync_and_report(hours=args.hours)

    if args.auto_post:
        from pathlib import Path
        inbox = config.UPLOAD_DIR
        for f in sorted(inbox.iterdir()):
            if f.suffix.lower() in {".mp4", ".mov", ".m4v"}:
                topic = args.topic or "lifestyle"
                print(f"\nAuto-posting {f.name}...")
                caption = claude_helper.generate_caption(topic=topic)
                hashtags = claude_helper.generate_hashtags(topic=topic, count=8)
                full_caption = f"{caption}\n\n{hashtags}"
                try:
                    media_id = instagram_poster.post_reel_local(str(f), full_caption)
                    print(f"  Posted! Media ID: {media_id}")
                except InstagramAPIError as e:
                    print(f"  Failed: {e}")


def handle_watch(args: argparse.Namespace) -> None:
    """Start the media folder watcher."""
    import media_watcher
    # Re-use media_watcher's main with sys.argv override
    watch_args = ["--watch-dir", args.watch_dir, "--topic", args.topic or "lifestyle"]
    if args.auto_post:
        watch_args.append("--auto-post")
    if config.MOCK_MODE:
        watch_args.append("--mock")

    sys.argv = ["media_watcher"] + watch_args
    media_watcher.main()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instagram Claude Automation — post Reels & Stories with AI-generated content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- Direct post mode (default / no subcommand) ---
    # Post type
    parser.add_argument(
        "--type", "-t",
        choices=["reel", "story"],
        help="Type of Instagram post to create.",
    )

    # Media sources
    parser.add_argument("--video-url", help="Public URL of the video file.")
    parser.add_argument("--image-url", help="Public URL of the image file (Stories).")
    parser.add_argument("--file", "-f", help="Path to a local video file for upload.")

    # Content generation
    parser.add_argument("--topic", help="Topic for Claude to generate content about.")
    parser.add_argument("--audience", help="Target audience (e.g., 'fitness enthusiasts').")
    parser.add_argument("--tone", help="Desired tone (e.g., 'fun', 'professional').")
    parser.add_argument("--caption", help="Use a custom caption instead of generating one.")
    parser.add_argument("--no-hashtags", action="store_true", help="Skip hashtag generation.")
    parser.add_argument("--hashtag-count", type=int, default=10, help="Number of hashtags (default: 10).")

    # Posting options
    parser.add_argument("--no-feed", action="store_true", help="Don't share Reel to main feed.")

    # Modes
    parser.add_argument("--generate-only", action="store_true", help="Only generate content, don't post.")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive Claude prompt mode.")
    parser.add_argument("--mock", action="store_true", help="Enable mock/dry-run mode (no real API calls).")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")

    # --- Server subcommand ---
    server_parser = subparsers.add_parser("server", help="Start upload server for iPhone")
    server_parser.add_argument("--port", type=int, default=5555)
    server_parser.add_argument("--host", default="0.0.0.0")
    server_parser.add_argument("--auto-post", action="store_true")
    server_parser.add_argument("--topic", default="lifestyle")
    server_parser.add_argument("--no-auth", action="store_true")
    server_parser.add_argument("--mock", action="store_true")
    server_parser.add_argument("--verbose", "-v", action="store_true")

    # --- Google Photos sync subcommand ---
    sync_parser = subparsers.add_parser("sync", help="Sync from Google Photos (Google One)")
    sync_parser.add_argument("--hours", type=int, default=24, help="Sync media from last N hours (default: 24)")
    sync_parser.add_argument("--count", type=int, default=25, help="Max items to sync")
    sync_parser.add_argument("--browse", action="store_true", help="Browse recent media items")
    sync_parser.add_argument("--list-albums", action="store_true", help="List your Google Photos albums")
    sync_parser.add_argument("--auto-post", action="store_true", help="Auto-post synced videos as Reels")
    sync_parser.add_argument("--topic", default="lifestyle", help="Topic for auto-generated captions")
    sync_parser.add_argument("--mock", action="store_true")
    sync_parser.add_argument("--verbose", "-v", action="store_true")

    # --- Watch subcommand ---
    watch_parser = subparsers.add_parser("watch", help="Watch folder for new media")
    watch_parser.add_argument("--watch-dir", "-w", required=True)
    watch_parser.add_argument("--topic", default="lifestyle")
    watch_parser.add_argument("--auto-post", action="store_true")
    watch_parser.add_argument("--mock", action="store_true")
    watch_parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    # Override mock mode from CLI
    if getattr(args, "mock", False):
        config.MOCK_MODE = True

    setup_logging(getattr(args, "verbose", False))

    try:
        if args.command == "server":
            handle_server(args)
        elif args.command == "sync":
            handle_sync(args)
        elif args.command == "watch":
            handle_watch(args)
        elif getattr(args, "interactive", False):
            handle_interactive()
        elif getattr(args, "generate_only", False):
            handle_generate_only(args)
        elif getattr(args, "type", None) == "reel":
            handle_reel(args)
        elif getattr(args, "type", None) == "story":
            handle_story(args)
        else:
            parser.print_help()
            sys.exit(1)
    except InstagramAPIError as e:
        logging.error("Instagram API error: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
