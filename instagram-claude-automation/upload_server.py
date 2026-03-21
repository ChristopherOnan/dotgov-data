"""
Flask upload server — receives photos/videos from iPhone via HTTP POST.

Provides two modes:
  1. Upload + auto-post: iPhone sends media → server posts to Instagram immediately
  2. Upload + queue: iPhone sends media → saved to inbox folder for later batch posting

Designed to work with iOS Shortcuts for one-tap posting from your camera roll.

Usage:
  python upload_server.py                    # Start on port 5555
  python upload_server.py --port 8080        # Custom port
  python upload_server.py --auto-post        # Auto-post uploads to Instagram
"""

import argparse
import hashlib
import logging
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, request, jsonify, abort

import config
import claude_helper
import instagram_poster
from utils import InstagramAPIError

logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Configuration ---
UPLOAD_DIR = Path(__file__).resolve().parent / "media_inbox"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".heic", ".webp"},
    "video": {".mp4", ".mov", ".m4v", ".avi"},
}
ALL_EXTENSIONS = ALLOWED_EXTENSIONS["image"] | ALLOWED_EXTENSIONS["video"]

MAX_FILE_SIZE = 1024 * 1024 * 500  # 500 MB

# Simple API key for securing the upload endpoint
# Set UPLOAD_API_KEY in .env, or one is generated on startup
UPLOAD_API_KEY = os.getenv("UPLOAD_API_KEY", "")

# Runtime flags (set via CLI args)
AUTO_POST = False
DEFAULT_TOPIC = "lifestyle"


def _generate_api_key() -> str:
    """Generate a random API key for securing uploads."""
    return secrets.token_urlsafe(32)


def _get_media_type(filename: str) -> Optional[str]:
    """Determine if a file is an image or video based on extension."""
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_EXTENSIONS["image"]:
        return "image"
    if ext in ALLOWED_EXTENSIONS["video"]:
        return "video"
    return None


def _save_file(file_storage) -> tuple[Path, str]:
    """
    Save an uploaded file to the inbox directory.

    Returns (file_path, media_type).
    """
    filename = file_storage.filename or "upload"
    media_type = _get_media_type(filename)
    if not media_type:
        raise ValueError(f"Unsupported file type: {Path(filename).suffix}")

    # Generate unique filename to avoid collisions
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(filename).suffix.lower()
    unique = hashlib.md5(f"{filename}{time.time()}".encode()).hexdigest()[:8]
    safe_name = f"{timestamp}_{unique}{ext}"

    dest = UPLOAD_DIR / safe_name
    file_storage.save(str(dest))
    logger.info("Saved upload: %s (%s, %d bytes)", dest.name, media_type, dest.stat().st_size)
    return dest, media_type


def _auto_post_file(file_path: Path, media_type: str, topic: str, post_type: str) -> dict:
    """Generate content with Claude and post to Instagram."""
    caption = claude_helper.generate_caption(topic=topic)
    hashtags = claude_helper.generate_hashtags(topic=topic, count=8)
    full_caption = f"{caption}\n\n{hashtags}"

    if post_type == "reel" or (post_type == "auto" and media_type == "video"):
        container_id = instagram_poster.create_reel_container_local(
            file_path=str(file_path),
            caption=full_caption,
        )
        media_id = instagram_poster.publish_container(container_id)
        return {"media_id": media_id, "type": "reel", "caption": full_caption}

    elif post_type == "story" or (post_type == "auto" and media_type == "image"):
        # Stories from local files need to go through resumable upload first
        # For now, queue it
        return {"queued": True, "file": str(file_path), "type": "story"}

    return {"queued": True, "file": str(file_path)}


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.before_request
def check_auth():
    """Verify API key on all POST endpoints."""
    if request.method == "POST" and UPLOAD_API_KEY:
        provided = request.headers.get("X-API-Key", "") or request.form.get("api_key", "")
        if not secrets.compare_digest(provided, UPLOAD_API_KEY):
            abort(401, description="Invalid or missing API key.")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "inbox_count": len(list(UPLOAD_DIR.iterdir()))})


@app.route("/upload", methods=["POST"])
def upload():
    """
    Upload a photo or video from iPhone.

    Form fields:
      - file: The media file (required)
      - topic: Content topic for Claude caption generation (optional)
      - post_type: "reel", "story", or "auto" (optional, default: "auto")
      - auto_post: "true" to post immediately (optional, overrides server default)

    Headers:
      - X-API-Key: Your upload API key

    Returns JSON with file info and posting result.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided. Send as multipart form with key 'file'."}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Empty filename."}), 400

    # Validate extension
    if _get_media_type(uploaded.filename) is None:
        return jsonify({
            "error": f"Unsupported file type. Allowed: {', '.join(sorted(ALL_EXTENSIONS))}"
        }), 400

    try:
        file_path, media_type = _save_file(uploaded)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Check file size
    if file_path.stat().st_size > MAX_FILE_SIZE:
        file_path.unlink()
        return jsonify({"error": f"File too large. Max: {MAX_FILE_SIZE // (1024*1024)} MB."}), 413

    result = {
        "filename": file_path.name,
        "media_type": media_type,
        "size_bytes": file_path.stat().st_size,
        "path": str(file_path),
        "saved": True,
    }

    # Auto-post if enabled
    topic = request.form.get("topic", DEFAULT_TOPIC)
    post_type = request.form.get("post_type", "auto")
    should_post = (
        AUTO_POST
        or request.form.get("auto_post", "").lower() == "true"
    )

    if should_post and not config.MOCK_MODE:
        try:
            post_result = _auto_post_file(file_path, media_type, topic, post_type)
            result["posted"] = post_result
        except InstagramAPIError as e:
            result["post_error"] = str(e)
            logger.error("Auto-post failed: %s", e)
    elif should_post and config.MOCK_MODE:
        result["posted"] = {"mock": True, "would_post_as": post_type}

    return jsonify(result), 201


@app.route("/upload/batch", methods=["POST"])
def upload_batch():
    """
    Upload multiple files at once.

    Form fields:
      - files: Multiple media files
      - topic: Shared topic for all (optional)

    Returns JSON array of results.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided."}), 400

    results = []
    for f in files:
        if not f.filename or _get_media_type(f.filename) is None:
            results.append({"filename": f.filename, "error": "Skipped — unsupported type."})
            continue
        try:
            file_path, media_type = _save_file(f)
            results.append({
                "filename": file_path.name,
                "media_type": media_type,
                "size_bytes": file_path.stat().st_size,
                "saved": True,
            })
        except Exception as e:
            results.append({"filename": f.filename, "error": str(e)})

    return jsonify({"uploaded": len([r for r in results if r.get("saved")]), "results": results}), 201


@app.route("/inbox", methods=["GET"])
def list_inbox():
    """List all files in the media inbox."""
    files = []
    for p in sorted(UPLOAD_DIR.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            files.append({
                "filename": p.name,
                "media_type": _get_media_type(p.name),
                "size_bytes": p.stat().st_size,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            })
    return jsonify({"count": len(files), "files": files})


@app.route("/inbox/post/<filename>", methods=["POST"])
def post_from_inbox(filename: str):
    """
    Post a specific file from the inbox to Instagram.

    URL param: filename
    Form fields:
      - topic: Content topic (optional)
      - post_type: "reel" or "story" (optional, default: "auto")
    """
    file_path = UPLOAD_DIR / filename
    if not file_path.is_file():
        return jsonify({"error": f"File not found: {filename}"}), 404

    media_type = _get_media_type(filename)
    if not media_type:
        return jsonify({"error": "Unsupported file type."}), 400

    topic = request.form.get("topic", DEFAULT_TOPIC)
    post_type = request.form.get("post_type", "auto")

    try:
        result = _auto_post_file(file_path, media_type, topic, post_type)
        return jsonify({"posted": result})
    except InstagramAPIError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/inbox/generate-caption", methods=["POST"])
def generate_caption_endpoint():
    """
    Generate a caption + hashtags without posting.

    Form fields:
      - topic: Content topic (required)
      - audience: Target audience (optional)
      - tone: Caption tone (optional)
    """
    topic = request.form.get("topic", "")
    if not topic:
        return jsonify({"error": "Topic is required."}), 400

    audience = request.form.get("audience", "general")
    tone = request.form.get("tone", "engaging")

    caption = claude_helper.generate_caption(topic=topic, audience=audience, tone=tone)
    hashtags = claude_helper.generate_hashtags(topic=topic, count=10)

    return jsonify({"caption": caption, "hashtags": hashtags, "full": f"{caption}\n\n{hashtags}"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global UPLOAD_API_KEY, AUTO_POST, DEFAULT_TOPIC

    parser = argparse.ArgumentParser(description="iPhone media upload server for Instagram automation.")
    parser.add_argument("--port", type=int, default=5555, help="Port to listen on (default: 5555)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--auto-post", action="store_true", help="Auto-post uploads to Instagram")
    parser.add_argument("--topic", default="lifestyle", help="Default topic for caption generation")
    parser.add_argument("--mock", action="store_true", help="Enable mock mode")
    parser.add_argument("--no-auth", action="store_true", help="Disable API key auth (dev only)")
    args = parser.parse_args()

    if args.mock:
        config.MOCK_MODE = True

    AUTO_POST = args.auto_post
    DEFAULT_TOPIC = args.topic

    # Setup API key
    if args.no_auth:
        UPLOAD_API_KEY = ""
        print("WARNING: API key authentication disabled.")
    elif not UPLOAD_API_KEY:
        UPLOAD_API_KEY = _generate_api_key()
        print(f"\n{'='*60}")
        print("UPLOAD SERVER API KEY (save this!):")
        print(f"  {UPLOAD_API_KEY}")
        print(f"{'='*60}\n")

    logging.basicConfig(
        level=logging.DEBUG if os.getenv("LOG_LEVEL") == "DEBUG" else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print(f"Upload server starting on http://{args.host}:{args.port}")
    print(f"Media inbox: {UPLOAD_DIR}")
    print(f"Auto-post: {'ON' if AUTO_POST else 'OFF'}")
    print(f"Mock mode: {'ON' if config.MOCK_MODE else 'OFF'}")
    print(f"\nEndpoints:")
    print(f"  POST /upload         — Upload single file")
    print(f"  POST /upload/batch   — Upload multiple files")
    print(f"  GET  /inbox          — List queued files")
    print(f"  POST /inbox/post/<f> — Post a queued file")
    print(f"  GET  /health         — Health check\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
