"""Phase 6: Validate documentation links in KB articles."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import urllib.request
import urllib.error
import ssl

from .config import (
    KB_ARTICLES_JSON,
    KB_INDEX_JSON,
    SENDER_AUTHORITY_JSON,
    THREADS_ASSESSED_JSON,
    THREADS_CLASSIFIED_JSON,
    THREADS_JSON,
)
from .schemas import (
    DocLink,
    KBArticle,
    KBIndex,
    SenderAuthority,
    TagCloudEntry,
    Thread,
)

logger = logging.getLogger(__name__)

# Rate limit: max requests per second to avoid hammering Juniper's site
REQUEST_DELAY = 0.5  # seconds between requests
REQUEST_TIMEOUT = 10  # seconds per request

# User-Agent to avoid being blocked
USER_AGENT = "TechTalk-KB-Validator/1.0"


def _is_valid_url(url: str) -> bool:
    """Basic URL format validation."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _check_url(url: str) -> tuple[bool, int | None]:
    """Check if a URL is reachable via HEAD request.

    Returns (is_valid, status_code).
    """
    if not _is_valid_url(url):
        return False, None

    # Create a lenient SSL context (some Juniper subdomains have cert issues)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
            return resp.status < 400, resp.status
    except urllib.error.HTTPError as e:
        return False, e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        # Try GET as fallback — some servers reject HEAD
        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                return resp.status < 400, resp.status
        except urllib.error.HTTPError as e:
            return False, e.code
        except (urllib.error.URLError, TimeoutError, OSError):
            return False, None


def _validate_links(links: list[DocLink], label: str) -> tuple[list[DocLink], int, int]:
    """Validate a list of DocLinks.

    Returns (validated_links, checked_count, valid_count).
    """
    checked = 0
    valid = 0
    for link in links:
        is_valid, status = _check_url(link.url)
        link.validated = is_valid
        checked += 1
        if is_valid:
            valid += 1
            logger.debug("  [OK]  %s — %s", label, link.url)
        else:
            logger.debug("  [FAIL] %s — %s (status=%s)", label, link.url, status)
        time.sleep(REQUEST_DELAY)
    return links, checked, valid


def _load_articles() -> list[KBArticle]:
    """Load KB articles."""
    if not KB_ARTICLES_JSON.exists():
        raise FileNotFoundError(f"{KB_ARTICLES_JSON} not found. Run 'curate' first.")
    with open(KB_ARTICLES_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [KBArticle.model_validate(a) for a in data]


def _load_threads() -> list[Thread]:
    """Load threads for index rebuild."""
    for path in [THREADS_ASSESSED_JSON, THREADS_CLASSIFIED_JSON, THREADS_JSON]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [Thread.model_validate(t) for t in data]
    return []


def _load_authority() -> list[SenderAuthority]:
    """Load sender authority for index rebuild."""
    if not SENDER_AUTHORITY_JSON.exists():
        return []
    with open(SENDER_AUTHORITY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [SenderAuthority.model_validate(a) for a in data]


def _rebuild_index(articles: list[KBArticle]) -> None:
    """Rebuild kb_index.json after validation."""
    threads = _load_threads()
    authority = _load_authority()

    # Rebuild tag cloud
    from collections import Counter, defaultdict
    tag_counts: Counter = Counter()
    tag_categories: dict[str, set[str]] = defaultdict(set)
    for article in articles:
        for tag in article.tags:
            tag_lower = tag.lower()
            tag_counts[tag_lower] += 1
            for cat in article.categories:
                tag_categories[tag_lower].add(cat)

    tag_cloud = [
        TagCloudEntry(tag=tag, count=count, categories=sorted(tag_categories[tag]))
        for tag, count in tag_counts.most_common()
    ]

    all_categories = sorted({c for a in articles for c in a.categories})
    all_products = sorted({p for a in articles for p in a.products})

    index = KBIndex(
        generated_at=datetime.now(timezone.utc),
        total_articles=len(articles),
        total_threads=len(threads),
        total_messages=sum(t.message_count for t in threads),
        categories=all_categories,
        products=all_products,
        articles=articles,
        sender_authority=authority,
        tag_cloud=tag_cloud,
    )

    with open(KB_INDEX_JSON, "w", encoding="utf-8") as f:
        json.dump(
            index.model_dump(mode="json"),
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    logger.info("Rebuilt: %s", KB_INDEX_JSON)


def run(
    keep_unvalidated: bool = False,
    dry_run: bool = False,
) -> list[KBArticle]:
    """Validate all doc_links and related_kbs URLs in KB articles.

    Args:
        keep_unvalidated: If True, keep failed links (flagged validated=false).
                          If False, strip failed links from output.
        dry_run: Show what would be checked without making requests.
    """
    articles = _load_articles()

    # Count total links to check
    total_doc_links = sum(len(a.doc_links) for a in articles)
    total_related_kbs = sum(len(a.related_kbs) for a in articles)
    total_links = total_doc_links + total_related_kbs

    logger.info(
        "Loaded %d articles with %d doc links + %d related KBs = %d URLs to check",
        len(articles), total_doc_links, total_related_kbs, total_links,
    )

    if dry_run:
        # List unique domains
        from collections import Counter
        domains = Counter()
        for a in articles:
            for link in a.doc_links + a.related_kbs:
                parsed = urlparse(link.url)
                domains[parsed.netloc] += 1
        logger.info("Unique domains:")
        for domain, count in domains.most_common():
            logger.info("  %s: %d links", domain, count)
        return articles

    total_checked = 0
    total_valid = 0
    total_stripped = 0

    for i, article in enumerate(articles, 1):
        links_in_article = len(article.doc_links) + len(article.related_kbs)
        if links_in_article == 0:
            continue

        logger.info(
            "Article %d/%d (%s) — %d links",
            i, len(articles), article.article_id[:40], links_in_article,
        )

        # Validate doc_links
        article.doc_links, checked, valid = _validate_links(article.doc_links, "doc")
        total_checked += checked
        total_valid += valid

        # Validate related_kbs
        article.related_kbs, checked, valid = _validate_links(article.related_kbs, "kb")
        total_checked += checked
        total_valid += valid

        # Strip or keep invalid links
        if not keep_unvalidated:
            before_doc = len(article.doc_links)
            before_kb = len(article.related_kbs)
            article.doc_links = [l for l in article.doc_links if l.validated]
            article.related_kbs = [l for l in article.related_kbs if l.validated]
            stripped = (before_doc - len(article.doc_links)) + (before_kb - len(article.related_kbs))
            total_stripped += stripped

    logger.info(
        "Validation complete: %d checked, %d valid, %d failed",
        total_checked, total_valid, total_checked - total_valid,
    )
    if not keep_unvalidated:
        logger.info("Stripped %d invalid links", total_stripped)
    else:
        logger.info("Kept all links (flagged invalid ones as validated=false)")

    # Write updated articles
    with open(KB_ARTICLES_JSON, "w", encoding="utf-8") as f:
        json.dump(
            [a.model_dump(mode="json") for a in articles],
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    logger.info("Updated: %s", KB_ARTICLES_JSON)

    # Rebuild index
    _rebuild_index(articles)

    return articles
