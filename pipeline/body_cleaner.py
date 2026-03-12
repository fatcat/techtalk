"""Clean and split email bodies: extract own text vs quoted text."""

from __future__ import annotations

import re

# Outlook-style inline reply header block (From/Date or From/Sent variants)
# Matches the separator block that Outlook inserts before quoted content.
_OUTLOOK_REPLY_RE = re.compile(
    r"""
    (?:^|\n)                          # start of line
    \s*_{3,}\s*\n                     # optional ___ separator line
    |                                 # OR
    (?:^|\n)                          # start of line
    \s*-{3,}\s*Original\s+Message\s*-{3,}\s*\n  # --- Original Message ---
    |                                 # OR
    (?:^|\n)                          # start of line
    [ \t]*From:\s+.+\n               # From: line
    [ \t]*(?:Sent|Date):\s+.+\n      # Sent: or Date: line
    [ \t]*To:\s+.+\n                 # To: line
    (?:[ \t]*(?:Cc|CC):\s+.+\n)?     # optional Cc: line
    [ \t]*Subject:\s+.+              # Subject: line
    """,
    re.MULTILINE | re.VERBOSE,
)

# "On <date>, <person> wrote:" style quoting
_ON_WROTE_RE = re.compile(
    r"\n[ \t]*On .{10,80} wrote:\s*\n",
    re.MULTILINE,
)

# Sent from mobile signatures
_SENT_FROM_RE = re.compile(
    r"\n[ \t]*Sent from (?:my )?(?:iPhone|iPad|Outlook|Samsung|Galaxy).*$",
    re.MULTILINE | re.IGNORECASE,
)

# Juniper footer
_JUNIPER_FOOTER_RE = re.compile(
    r"\n?\s*Juniper Business Use Only\s*$",
    re.MULTILINE,
)

# Inline image references
_CID_RE = re.compile(r"\[cid:[^\]]+\]")

# Collapse multiple blank lines
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _strip_juniper_footer(text: str) -> str:
    """Remove all occurrences of 'Juniper Business Use Only' footer."""
    return _JUNIPER_FOOTER_RE.sub("", text)


def _strip_cid_refs(text: str) -> str:
    """Remove inline image [cid:...] references."""
    return _CID_RE.sub("", text)


def _strip_sent_from(text: str) -> str:
    """Remove 'Sent from my iPhone' style signatures."""
    return _SENT_FROM_RE.sub("", text)


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of blank lines and strip leading/trailing whitespace."""
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def split_body(text: str) -> tuple[str, str]:
    """Split email body into (own_text, quoted_text).

    Returns the author's own text and the quoted/replied-to text.
    If no quoting is detected, quoted_text is empty.
    """
    # First, clean the full text
    text = _strip_cid_refs(text)
    text = _strip_juniper_footer(text)

    # Try Outlook-style reply headers first (most common)
    match = _OUTLOOK_REPLY_RE.search(text)
    if match:
        own = text[: match.start()]
        quoted = text[match.end() :]
        own = _strip_sent_from(own)
        return _normalize_whitespace(own), _normalize_whitespace(quoted)

    # Try "On ... wrote:" style
    match = _ON_WROTE_RE.search(text)
    if match:
        own = text[: match.start()]
        quoted = text[match.end() :]
        own = _strip_sent_from(own)
        return _normalize_whitespace(own), _normalize_whitespace(quoted)

    # No quoting detected
    text = _strip_sent_from(text)
    return _normalize_whitespace(text), ""


def clean_body(text: str) -> str:
    """Clean a body without splitting — just remove noise."""
    text = _strip_cid_refs(text)
    text = _strip_juniper_footer(text)
    text = _strip_sent_from(text)
    return _normalize_whitespace(text)
