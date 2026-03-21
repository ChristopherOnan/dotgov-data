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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instagram Claude Automation — post Reels & Stories with AI-generated content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

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

    args = parser.parse_args()

    # Override mock mode from CLI
    if args.mock:
        config.MOCK_MODE = True

    setup_logging(args.verbose)

    try:
        if args.interactive:
            handle_interactive()
        elif args.generate_only:
            handle_generate_only(args)
        elif args.type == "reel":
            handle_reel(args)
        elif args.type == "story":
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
