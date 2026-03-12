"""Phase 2: Reconstruct threads from parsed messages."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

from .config import MESSAGES_JSON, THREADS_JSON
from .schemas import ParsedMessage, Thread, ThreadMessage

logger = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 80) -> str:
    """Create a URL-safe slug from text."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len]


def _normalize_topic(subject: str) -> str:
    """Normalize a subject line to a canonical thread topic.

    Strips Re:/RE:/Fwd:/FW:/VS: prefixes and extra whitespace.
    """
    cleaned = re.sub(
        r"^(?:re|fw|fwd|vs)\s*:\s*",
        "",
        subject.strip(),
        flags=re.IGNORECASE,
    )
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _load_messages() -> list[ParsedMessage]:
    """Load messages.json into ParsedMessage objects."""
    with open(MESSAGES_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [ParsedMessage.model_validate(m) for m in data]


def _group_by_topic(messages: list[ParsedMessage]) -> dict[str, list[ParsedMessage]]:
    """Group messages by their thread topic.

    Uses Thread-Topic header when available, falls back to normalized Subject.
    """
    groups: dict[str, list[ParsedMessage]] = defaultdict(list)

    for msg in messages:
        topic = msg.thread_topic.strip()
        if not topic:
            topic = _normalize_topic(msg.subject)
        if not topic:
            topic = f"_untitled_{msg.message_id}"
        groups[topic].append(msg)

    return dict(groups)


def _build_thread(topic: str, messages: list[ParsedMessage]) -> Thread:
    """Build a Thread from a group of messages sharing the same topic."""
    # Sort by date (None dates go to end)
    messages.sort(
        key=lambda m: m.date or datetime.max.replace(tzinfo=timezone.utc)
    )

    thread_id = _slugify(topic)
    if not thread_id:
        thread_id = f"thread-{hash(topic) % 100000:05d}"

    thread_messages: list[ThreadMessage] = []
    participants: set[str] = set()

    for msg in messages:
        is_starter = not msg.is_reply
        thread_messages.append(ThreadMessage(
            message_id=msg.message_id,
            date=msg.date,
            from_name=msg.from_name,
            from_email=msg.from_email,
            body_own=msg.body_own,
            is_thread_starter=is_starter,
        ))
        if msg.from_email:
            participants.add(msg.from_email.lower())

    # Determine original question
    original_question = _extract_original_question(messages)

    # Determine if thread has an answer
    has_answer = _has_answer(messages)

    dates = [m.date for m in messages if m.date]

    return Thread(
        thread_id=thread_id,
        thread_topic=topic,
        messages=thread_messages,
        original_question=original_question,
        participant_count=len(participants),
        message_count=len(messages),
        date_first=min(dates) if dates else None,
        date_last=max(dates) if dates else None,
        has_answer=has_answer,
    )


def _extract_original_question(messages: list[ParsedMessage]) -> str:
    """Extract the original question for a thread.

    Strategy:
    - Multi-message: use the earliest non-reply message's body_own
    - Single reply: use body_quoted (the quoted original)
    - Single non-reply: use body_own (it's the question itself)
    """
    if len(messages) == 1:
        msg = messages[0]
        if msg.is_reply and msg.body_quoted:
            return msg.body_quoted
        return msg.body_own

    # Multi-message: find the earliest thread starter
    starters = [m for m in messages if not m.is_reply]
    if starters:
        return starters[0].body_own

    # All are replies — use the quoted text from the earliest reply
    for msg in messages:
        if msg.body_quoted:
            return msg.body_quoted

    # Fallback: earliest message body
    return messages[0].body_own if messages else ""


def _has_answer(messages: list[ParsedMessage]) -> bool:
    """Determine if a thread contains at least one answer.

    A thread has an answer if:
    - There are multiple messages (at least one reply exists as a separate .eml)
    - OR a single reply .eml exists (it IS the answer, quoted text is the question)
    """
    if len(messages) > 1:
        return True
    if len(messages) == 1 and messages[0].is_reply:
        return True
    return False


def run() -> list[Thread]:
    """Reconstruct threads from messages.json and write threads.json."""
    messages = _load_messages()
    logger.info("Loaded %d messages from %s", len(messages), MESSAGES_JSON)

    groups = _group_by_topic(messages)
    logger.info("Grouped into %d unique thread topics", len(groups))

    threads: list[Thread] = []
    for topic, msgs in groups.items():
        thread = _build_thread(topic, msgs)
        threads.append(thread)

    # Sort threads by date_first
    threads.sort(
        key=lambda t: t.date_first or datetime.min.replace(tzinfo=timezone.utc)
    )

    # Write output
    THREADS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(THREADS_JSON, "w", encoding="utf-8") as f:
        json.dump(
            [t.model_dump(mode="json") for t in threads],
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    # Stats
    multi = sum(1 for t in threads if t.message_count > 1)
    single_answered = sum(1 for t in threads if t.message_count == 1 and t.has_answer)
    unanswered = sum(1 for t in threads if not t.has_answer)

    logger.info(
        "Built %d threads. Output: %s", len(threads), THREADS_JSON,
    )
    logger.info(
        "  Multi-message: %d | Single-reply (answered): %d | Unanswered: %d",
        multi, single_answered, unanswered,
    )

    return threads
