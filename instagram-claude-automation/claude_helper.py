"""
Claude (Anthropic API) integration for generating Instagram content.

Uses the Anthropic Python SDK to generate captions, hashtags, reel scripts,
and story text via Claude. Supports both interactive prompts and predefined
templates for common use cases.

Docs: https://docs.anthropic.com/en/docs/build-with-claude/overview
"""

import logging
from typing import Optional

import anthropic

import config

logger = logging.getLogger(__name__)

# Default model — update to latest available as needed
DEFAULT_MODEL = "claude-sonnet-4-20250514"


def _get_client() -> anthropic.Anthropic:
    """Create an Anthropic client using the configured API key."""
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _call_claude(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
) -> str:
    """
    Send a prompt to Claude and return the text response.

    Args:
        prompt: The user message to send.
        system: Optional system prompt to set context.
        model: Claude model ID.
        max_tokens: Maximum response tokens.

    Returns:
        The text content of Claude's response.
    """
    client = _get_client()

    if config.MOCK_MODE:
        logger.info("[MOCK] Claude call with prompt: %s...", prompt[:80])
        return "[MOCK] This is a mock Claude response for testing."

    logger.debug("Calling Claude model=%s, max_tokens=%d", model, max_tokens)

    messages = [{"role": "user", "content": prompt}]
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)

    text = response.content[0].text
    logger.debug("Claude response (%d chars): %s...", len(text), text[:100])
    return text


# ---------------------------------------------------------------------------
# Template-based content generators
# ---------------------------------------------------------------------------

SYSTEM_INSTAGRAM = (
    "You are an expert Instagram content creator and social media strategist. "
    "You write engaging, authentic captions optimized for reach and engagement. "
    "Always include relevant emojis naturally. Keep captions concise but impactful."
)


def generate_caption(
    topic: str,
    audience: str = "general",
    tone: str = "engaging and authentic",
    include_cta: bool = True,
) -> str:
    """
    Generate an Instagram caption for a given topic.

    Args:
        topic: What the post is about (e.g., "morning routine", "travel in Bali").
        audience: Target audience (e.g., "fitness enthusiasts", "entrepreneurs").
        tone: Desired tone (e.g., "fun and casual", "inspirational").
        include_cta: Whether to include a call-to-action.

    Returns:
        A ready-to-use Instagram caption string.
    """
    cta_line = "Include a clear call-to-action (e.g., save, share, comment)." if include_cta else ""

    prompt = (
        f"Write an Instagram caption about: {topic}\n"
        f"Target audience: {audience}\n"
        f"Tone: {tone}\n"
        f"{cta_line}\n"
        f"Keep it under 2000 characters. Use emojis naturally. "
        f"Do NOT include hashtags — those will be added separately.\n"
        f"Return ONLY the caption text, no extra commentary."
    )
    return _call_claude(prompt, system=SYSTEM_INSTAGRAM)


def generate_hashtags(
    topic: str,
    count: int = 10,
    mix: str = "5 niche + 3 mid-range + 2 broad",
) -> str:
    """
    Generate optimized hashtags for an Instagram post.

    Args:
        topic: Post topic for hashtag relevance.
        count: Total number of hashtags to generate (max 30).
        mix: Strategy for hashtag sizes (niche/mid/broad).

    Returns:
        A string of space-separated hashtags (e.g., "#fitness #gym ...").
    """
    count = min(count, config.MAX_HASHTAGS)
    prompt = (
        f"Generate exactly {count} Instagram hashtags for a post about: {topic}\n"
        f"Mix strategy: {mix}\n"
        f"Return ONLY the hashtags, each starting with #, separated by spaces.\n"
        f"No numbering, no explanations."
    )
    return _call_claude(prompt, system=SYSTEM_INSTAGRAM, max_tokens=256)


def generate_reel_script(
    topic: str,
    duration_seconds: int = 30,
    style: str = "educational with personality",
) -> str:
    """
    Generate a Reel script/voiceover with timing cues.

    Args:
        topic: Reel subject matter.
        duration_seconds: Target reel length.
        style: Content style (e.g., "funny", "educational", "storytelling").

    Returns:
        A formatted script with timing and visual cues.
    """
    prompt = (
        f"Write a {duration_seconds}-second Instagram Reel script about: {topic}\n"
        f"Style: {style}\n"
        f"Format:\n"
        f"- Include a hook in the first 3 seconds\n"
        f"- Add [VISUAL CUE] notes for what to show on screen\n"
        f"- End with a strong CTA\n"
        f"- Include approximate timestamps like [0:00-0:03]\n"
        f"Return ONLY the script, no meta-commentary."
    )
    return _call_claude(prompt, system=SYSTEM_INSTAGRAM, max_tokens=1500)


def generate_story_text(
    topic: str,
    style: str = "short and punchy",
) -> str:
    """
    Generate text overlay content for an Instagram Story.

    Args:
        topic: What the story is about.
        style: Text style (e.g., "question for engagement", "announcement").

    Returns:
        Short text suitable for a story overlay (< 100 chars ideally).
    """
    prompt = (
        f"Write a short text overlay for an Instagram Story about: {topic}\n"
        f"Style: {style}\n"
        f"Keep it under 100 characters — punchy and eye-catching.\n"
        f"Return ONLY the text, nothing else."
    )
    return _call_claude(prompt, system=SYSTEM_INSTAGRAM, max_tokens=128)


def generate_alt_text(topic: str, media_description: str = "") -> str:
    """
    Generate accessible alt text for an Instagram post image/video.

    Args:
        topic: Post topic for context.
        media_description: Brief description of the visual content.

    Returns:
        Alt text string (< 420 chars per IG limit).
    """
    prompt = (
        f"Write alt text for an Instagram post about: {topic}\n"
        f"Visual content: {media_description or 'not specified'}\n"
        f"Keep it descriptive and under 420 characters.\n"
        f"Return ONLY the alt text."
    )
    return _call_claude(prompt, system=SYSTEM_INSTAGRAM, max_tokens=256)


def interactive_prompt(user_prompt: str) -> str:
    """
    Send a freeform prompt to Claude for any Instagram content need.

    This is the escape hatch for custom requests that don't fit templates.

    Args:
        user_prompt: Any instruction for Claude.

    Returns:
        Claude's response text.
    """
    return _call_claude(user_prompt, system=SYSTEM_INSTAGRAM)
