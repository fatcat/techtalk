"""Phase 5: LLM-based KB article curation with documentation enrichment."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .config import (
    KB_ARTICLES_JSON,
    KB_DATA_JS,
    KB_INDEX_JSON,
    SENDER_AUTHORITY_JSON,
    THREADS_ASSESSED_JSON,
    THREADS_CLASSIFIED_JSON,
    THREADS_JSON,
)
from .llm_client import call_claude, parse_json_response
from .schemas import (
    CLIExample,
    DocLink,
    KBArticle,
    KBIndex,
    SenderAuthority,
    TagCloudEntry,
    Thread,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior Juniper Networks engineer creating knowledge base articles from internal mailing list Q&A threads.

For each thread, produce a structured KB article with:
1. **title**: concise problem description (not a question — a statement)
2. **problem**: clear description of the issue or question
3. **cause**: root cause if identified (null if unknown)
4. **solution**: the answer, fix, or workaround
5. **additional_notes**: caveats, version-specific info, edge cases (null if none)
6. **confidence**: "high" (definitive answer), "medium" (likely correct), or "low" (partial/uncertain)
7. **junos_versions**: any Junos versions mentioned (e.g. ["23.4R2-S2", "24.2R1"])
8. **tags**: 3-8 searchable keywords (technical terms, features, symptoms)
9. **doc_links**: relevant Juniper TechLibrary documentation URLs. Use real documentation paths from juniper.net/documentation/. Only include links you are confident exist. Each entry: {"url": str, "title": str, "description": str}
10. **cli_examples**: relevant Junos CLI commands that relate to the problem/solution. Each entry: {"command": str, "description": str, "context": "show"|"set"|"request"|"other"}
11. **related_kbs**: known Juniper KB articles on this topic. Each entry: {"url": str, "title": str, "description": str}

IMPORTANT for doc_links and related_kbs:
- Only include URLs you are highly confident are real Juniper documentation pages
- Juniper TechLibrary URLs follow the pattern: https://www.juniper.net/documentation/us/en/software/junos/...
- Juniper KB articles follow: https://supportportal.juniper.net/s/article/...
- If unsure about a URL, omit it — a missing link is better than a broken one
- CLI examples do NOT need URLs, just the command syntax

Respond ONLY with a JSON object for the article. No explanation, no markdown fences."""

SELECTION_QUALITY = {"authoritative_answer", "workaround"}
SELECTION_MIN_WORTHINESS = 3


def _load_threads() -> list[Thread]:
    """Load the best available thread data."""
    for path in [THREADS_ASSESSED_JSON, THREADS_CLASSIFIED_JSON, THREADS_JSON]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [Thread.model_validate(t) for t in data]
    raise FileNotFoundError("No thread data found")


def _load_authority() -> list[SenderAuthority]:
    """Load sender authority data."""
    if not SENDER_AUTHORITY_JSON.exists():
        return []
    with open(SENDER_AUTHORITY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [SenderAuthority.model_validate(a) for a in data]


def _select_candidates(threads: list[Thread]) -> list[Thread]:
    """Select threads that qualify for KB article generation."""
    return [
        t for t in threads
        if t.quality in SELECTION_QUALITY and t.kb_worthiness >= SELECTION_MIN_WORTHINESS
    ]


def _build_article_prompt(thread: Thread, authority_map: dict[str, SenderAuthority]) -> str:
    """Build a prompt for generating a single KB article."""
    responses = []
    for m in thread.messages:
        if m.body_own.strip():
            auth = authority_map.get(m.from_email.lower())
            auth_level = auth.overall_authority if auth else "unknown"
            responses.append(
                f"[{auth_level}] {m.from_name}:\n{m.body_own[:1500]}"
            )

    responses_block = "\n\n".join(responses) if responses else "(no responses)"

    return (
        f"thread_id: {thread.thread_id}\n"
        f"topic: {thread.thread_topic}\n"
        f"categories: {', '.join(thread.categories)}\n"
        f"products: {', '.join(thread.products)}\n"
        f"quality: {thread.quality}\n"
        f"date: {thread.date_first}\n\n"
        f"ORIGINAL QUESTION:\n{thread.original_question[:2000]}\n\n"
        f"RESPONSES:\n{responses_block}"
    )


def _parse_article(thread: Thread, response_text: str) -> KBArticle | None:
    """Parse a Claude response into a KBArticle."""
    try:
        data = parse_json_response(response_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse article for %s: %s", thread.thread_id, e)
        return None

    doc_links = []
    for dl in data.get("doc_links") or []:
        if isinstance(dl, dict) and dl.get("url"):
            doc_links.append(DocLink(
                url=dl["url"],
                title=dl.get("title", ""),
                description=dl.get("description", ""),
            ))

    cli_examples = []
    for ce in data.get("cli_examples") or []:
        if isinstance(ce, dict) and ce.get("command"):
            cli_examples.append(CLIExample(
                command=ce["command"],
                description=ce.get("description", ""),
                context=ce.get("context", "other"),
            ))

    related_kbs = []
    for rk in data.get("related_kbs") or []:
        if isinstance(rk, dict) and rk.get("url"):
            related_kbs.append(DocLink(
                url=rk["url"],
                title=rk.get("title", ""),
                description=rk.get("description", ""),
            ))

    return KBArticle(
        article_id=thread.thread_id,
        title=data.get("title", thread.thread_topic),
        source_thread_ids=[thread.thread_id],
        products=thread.products,
        categories=thread.categories,
        junos_versions=data.get("junos_versions") or [],
        problem=data.get("problem", ""),
        cause=data.get("cause"),
        solution=data.get("solution", ""),
        additional_notes=data.get("additional_notes"),
        confidence=data.get("confidence", "medium"),
        original_date=thread.date_first,
        tags=data.get("tags", []),
        doc_links=doc_links,
        cli_examples=cli_examples,
        related_kbs=related_kbs,
    )


def _build_tag_cloud(articles: list[KBArticle]) -> list[TagCloudEntry]:
    """Build tag cloud data from all articles."""
    tag_counts: Counter = Counter()
    tag_categories: dict[str, set[str]] = defaultdict(set)

    for article in articles:
        for tag in article.tags:
            tag_lower = tag.lower()
            tag_counts[tag_lower] += 1
            for cat in article.categories:
                tag_categories[tag_lower].add(cat)

    entries = []
    for tag, count in tag_counts.most_common():
        entries.append(TagCloudEntry(
            tag=tag,
            count=count,
            categories=sorted(tag_categories[tag]),
        ))
    return entries


def _build_index(
    articles: list[KBArticle],
    threads: list[Thread],
    authority: list[SenderAuthority],
) -> KBIndex:
    """Build the final kb_index.json manifest."""
    all_categories = sorted({c for a in articles for c in a.categories})
    all_products = sorted({p for a in articles for p in a.products})
    tag_cloud = _build_tag_cloud(articles)

    return KBIndex(
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


def run(
    limit: int = 0,
    force: bool = False,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
) -> list[KBArticle]:
    """Generate KB articles from qualifying threads.

    Args:
        limit: Max articles to generate (0 = all candidates)
        force: Ignore cache
        dry_run: Preview without API calls
        model: Claude model to use
    """
    threads = _load_threads()
    authority_list = _load_authority()
    authority_map = {a.email.lower(): a for a in authority_list}

    candidates = _select_candidates(threads)
    logger.info(
        "Selected %d KB candidates from %d threads (quality in %s, worthiness >= %d)",
        len(candidates), len(threads), SELECTION_QUALITY, SELECTION_MIN_WORTHINESS,
    )

    if limit:
        candidates = candidates[:limit]
        logger.info("Limited to %d articles", limit)

    if dry_run:
        logger.info("Dry run — %d articles would be generated", len(candidates))
        for t in candidates[:20]:
            logger.info(
                "  %s — %s [%s] worthiness=%d",
                t.thread_id[:40], t.quality, ", ".join(t.categories), t.kb_worthiness,
            )
        return []

    articles: list[KBArticle] = []
    for i, thread in enumerate(candidates, 1):
        logger.info(
            "Article %d/%d — %s...",
            i, len(candidates), thread.thread_id[:50],
        )

        prompt = _build_article_prompt(thread, authority_map)
        response_text = call_claude(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=model,
            cache_prefix="curate",
            force=force,
        )

        article = _parse_article(thread, response_text)
        if article:
            articles.append(article)
        else:
            logger.warning("Skipped %s — parse failure", thread.thread_id)

    logger.info("Generated %d / %d articles", len(articles), len(candidates))

    # Write kb_articles.json
    KB_ARTICLES_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(KB_ARTICLES_JSON, "w", encoding="utf-8") as f:
        json.dump(
            [a.model_dump(mode="json") for a in articles],
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    logger.info("Output: %s", KB_ARTICLES_JSON)

    # Build and write kb_index.json
    index = _build_index(articles, threads, authority_list)
    with open(KB_INDEX_JSON, "w", encoding="utf-8") as f:
        json.dump(
            index.model_dump(mode="json"),
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    logger.info("Output: %s", KB_INDEX_JSON)

    # Write kb_data.js for UI (JSONP-style wrapper for file:// compatibility)
    KB_DATA_JS.parent.mkdir(parents=True, exist_ok=True)
    with open(KB_DATA_JS, "w", encoding="utf-8") as f:
        f.write("window.__KB_DATA__ = ")
        json.dump(
            index.model_dump(mode="json"),
            f,
            ensure_ascii=False,
            default=str,
        )
        f.write(";\n")
    logger.info("Output: %s", KB_DATA_JS)

    # Summary stats
    total_doc_links = sum(len(a.doc_links) for a in articles)
    total_cli_examples = sum(len(a.cli_examples) for a in articles)
    total_related_kbs = sum(len(a.related_kbs) for a in articles)
    logger.info(
        "Enrichment: %d doc links, %d CLI examples, %d related KBs",
        total_doc_links, total_cli_examples, total_related_kbs,
    )
    logger.info("Tag cloud: %d unique tags", len(index.tag_cloud))

    return articles
