"""Phase 1: Parse .eml files into structured messages."""

from __future__ import annotations

import email
import email.utils
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .body_cleaner import clean_body, split_body
from .config import EML_DIR, MESSAGES_JSON
from .schemas import Attachment, ParsedMessage

logger = logging.getLogger(__name__)


def _decode_payload(part: email.message.Message) -> str:
    """Decode a MIME part's payload to a string, handling charset diversity."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    # Normalize common aliases
    charset_map = {
        "ks_c_5601-1987": "euc-kr",
        "x-mac-korean": "euc-kr",
    }
    charset = charset_map.get(charset.lower(), charset)
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _parse_address(addr_str: str | None) -> tuple[str, str]:
    """Parse a single email address into (name, email)."""
    if not addr_str:
        return "", ""
    name, addr = email.utils.parseaddr(addr_str)
    return name, addr


def _parse_address_list(header: str | None) -> list[str]:
    """Parse a comma-separated address list into a list of email strings."""
    if not header:
        return []
    pairs = email.utils.getaddresses([header])
    return [addr for _, addr in pairs if addr]


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an email date header into a datetime."""
    if not date_str:
        return None
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return None


def _parse_references(ref_str: str | None) -> list[str]:
    """Parse a References header into a list of message IDs."""
    if not ref_str:
        return []
    # Message IDs are enclosed in angle brackets, separated by whitespace
    import re
    return re.findall(r"<[^>]+>", ref_str)


def parse_eml(filepath: Path) -> ParsedMessage:
    """Parse a single .eml file into a ParsedMessage."""
    warnings: list[str] = []

    with open(filepath, "rb") as f:
        msg = email.message_from_bytes(f.read())

    # Headers
    message_id = msg.get("Message-ID", "").strip()
    from_name, from_email = _parse_address(msg.get("From"))
    to = _parse_address_list(msg.get("To"))
    cc = _parse_address_list(msg.get("Cc"))
    subject = msg.get("Subject", "")
    thread_topic = msg.get("Thread-Topic", "")
    thread_index = msg.get("Thread-Index", "")
    in_reply_to = msg.get("In-Reply-To", "").strip() or None
    references = _parse_references(msg.get("References"))
    date = _parse_date(msg.get("Date"))

    # Body extraction
    body_plain = ""
    attachments: list[Attachment] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        # Skip multipart containers
        if part.get_content_maintype() == "multipart":
            continue

        # Attachment detection
        if "attachment" in disposition:
            filename = part.get_filename() or "unnamed"
            payload = part.get_payload(decode=True)
            size = len(payload) if payload else 0
            attachments.append(Attachment(
                filename=filename,
                content_type=content_type,
                size_bytes=size,
            ))
            continue

        # Extract plain text body (take the first one found)
        if content_type == "text/plain" and not body_plain:
            body_plain = _decode_payload(part)

    if not body_plain:
        warnings.append("no text/plain part found")

    # Clean and split body
    body_cleaned = clean_body(body_plain)
    body_own, body_quoted = split_body(body_plain)

    is_reply = bool(in_reply_to)

    return ParsedMessage(
        message_id=message_id,
        filename=filepath.name,
        date=date,
        from_name=from_name,
        from_email=from_email,
        to=to,
        cc=cc,
        subject=subject,
        thread_topic=thread_topic,
        thread_index=thread_index,
        in_reply_to=in_reply_to,
        references=references,
        is_reply=is_reply,
        body_plain=body_cleaned,
        body_own=body_own,
        body_quoted=body_quoted,
        attachments=attachments,
        parse_warnings=warnings,
    )


def run() -> list[ParsedMessage]:
    """Parse all .eml files and write messages.json."""
    eml_files = sorted(
        f for f in EML_DIR.iterdir()
        if f.suffix == ".eml" and not f.name.startswith("._")
    )

    # Skip __MACOSX directory
    eml_files = [f for f in eml_files if "__MACOSX" not in str(f)]

    logger.info("Parsing %d .eml files...", len(eml_files))

    messages: list[ParsedMessage] = []
    errors = 0

    for filepath in eml_files:
        try:
            msg = parse_eml(filepath)
            messages.append(msg)
        except Exception as e:
            logger.error("Failed to parse %s: %s", filepath.name, e)
            errors += 1

    # Sort by date
    messages.sort(key=lambda m: m.date or datetime.min.replace(tzinfo=timezone.utc))

    # Write output
    MESSAGES_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(MESSAGES_JSON, "w", encoding="utf-8") as f:
        json.dump(
            [m.model_dump(mode="json") for m in messages],
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    logger.info(
        "Parsed %d messages (%d errors). Output: %s",
        len(messages), errors, MESSAGES_JSON,
    )

    # Summary stats
    replies = sum(1 for m in messages if m.is_reply)
    with_warnings = sum(1 for m in messages if m.parse_warnings)
    logger.info(
        "  Replies: %d | Thread starters: %d | Parse warnings: %d",
        replies, len(messages) - replies, with_warnings,
    )

    return messages
