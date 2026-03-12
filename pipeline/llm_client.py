"""Claude API wrapper with content-hash caching and retry."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import anthropic

from .config import LLM_CACHE_DIR

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds


def _cache_path(prefix: str, content_hash: str) -> Path:
    return LLM_CACHE_DIR / f"{prefix}_{content_hash}.json"


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def call_claude(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    cache_prefix: str = "llm",
    max_tokens: int = 4096,
    force: bool = False,
) -> str:
    """Call Claude API with caching and retry.

    Returns the text response. Caches based on content hash of prompt+system.
    """
    cache_key = _hash_content(f"{system}|||{prompt}")
    cache_file = _cache_path(cache_prefix, cache_key)

    # Check cache
    if not force and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        logger.debug("Cache hit: %s", cache_file.name)
        return cached["response"]

    # API call with retry
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system

            response = client.messages.create(**kwargs)
            text = response.content[0].text

            # Cache the result
            cache_file.write_text(
                json.dumps({
                    "model": model,
                    "cache_key": cache_key,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "response": text,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            logger.debug(
                "API call: %d in / %d out tokens",
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            return text

        except anthropic.RateLimitError:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning("Rate limited, retrying in %.1fs (attempt %d/%d)", delay, attempt, MAX_RETRIES)
            time.sleep(delay)
        except anthropic.APIError as e:
            if attempt == MAX_RETRIES:
                raise
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning("API error: %s. Retrying in %.1fs (attempt %d/%d)", e, delay, attempt, MAX_RETRIES)
            time.sleep(delay)

    raise RuntimeError("Exhausted retries")


def parse_json_response(text: str) -> dict | list:
    """Extract JSON from a Claude response, handling markdown code fences."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)
