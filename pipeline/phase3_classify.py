"""Phase 3: LLM-based topic/product classification and sender authority."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from .config import SENDER_AUTHORITY_JSON, THREADS_JSON, THREADS_CLASSIFIED_JSON
from .llm_client import call_claude, parse_json_response
from .schemas import SenderAuthority, SenderExpertise, Thread

logger = logging.getLogger(__name__)

CATEGORIES = [
    "ipsec_vpn",
    "nat_cgnat",
    "high_availability",
    "routing",
    "security_policy",
    "ssl_tls",
    "licensing",
    "performance_scale",
    "management",
    "upgrade_migration",
    "cloud_virtualization",
    "sdwan_appsecure",
    "threat_intelligence",
    "platform_hardware",
    "other",
]

PRODUCTS = [
    "SRX300-series",
    "SRX1500",
    "SRX1600",
    "SRX2300",
    "SRX4100/4200",
    "SRX4300",
    "SRX4600",
    "SRX4700",
    "SRX5400/5600/5800",
    "vSRX",
    "cSRX",
    "Security Director",
    "Junos",
    "Generic",
]

SYSTEM_PROMPT = f"""You are a network security expert classifying email threads from a Juniper Networks internal mailing list.

For each thread, assign:
1. **categories**: one or more from this list: {json.dumps(CATEGORIES)}
2. **products**: one or more from this list: {json.dumps(PRODUCTS)}

Respond ONLY with a JSON array. Each element must have:
- "thread_id": the thread_id from the input
- "categories": list of category strings
- "products": list of product strings

No explanation, no markdown fences, just the JSON array."""

BATCH_SIZE = 20


def _build_batch_prompt(threads: list[Thread]) -> str:
    """Build a prompt containing multiple threads for batch classification."""
    parts = []
    for t in threads:
        question = t.original_question[:1500]
        # Include first answer if available
        answer = ""
        for m in t.messages:
            if not m.is_thread_starter and m.body_own:
                answer = m.body_own[:500]
                break
        parts.append(
            f"---\nthread_id: {t.thread_id}\n"
            f"topic: {t.thread_topic}\n"
            f"question: {question}\n"
            f"answer_excerpt: {answer}\n"
        )
    return "\n".join(parts)


def _load_threads(source: Path | None = None) -> list[Thread]:
    """Load threads from JSON."""
    path = source or THREADS_JSON
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Thread.model_validate(t) for t in data]


def run(
    limit: int = 0,
    force: bool = False,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
) -> list[Thread]:
    """Classify threads by topic and product.

    Args:
        limit: Max threads to process (0 = all)
        force: Ignore cache, re-classify everything
        dry_run: Print prompts without calling API
        model: Claude model to use
    """
    threads = _load_threads()
    logger.info("Loaded %d threads from %s", len(threads), THREADS_JSON)

    if limit:
        threads = threads[:limit]
        logger.info("Limited to %d threads", limit)

    # Index threads by ID for quick lookup
    thread_map = {t.thread_id: t for t in threads}

    # Process in batches
    total_classified = 0
    for batch_start in range(0, len(threads), BATCH_SIZE):
        batch = threads[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(threads) + BATCH_SIZE - 1) // BATCH_SIZE

        prompt = _build_batch_prompt(batch)

        if dry_run:
            logger.info("Batch %d/%d — %d threads (dry run)", batch_num, total_batches, len(batch))
            logger.debug("Prompt length: %d chars", len(prompt))
            continue

        logger.info("Batch %d/%d — classifying %d threads...", batch_num, total_batches, len(batch))

        response_text = call_claude(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=model,
            cache_prefix="classify",
            force=force,
        )

        try:
            results = parse_json_response(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse batch %d response: %s", batch_num, e)
            logger.debug("Raw response: %s", response_text[:500])
            continue

        for item in results:
            tid = item.get("thread_id", "")
            if tid in thread_map:
                thread_map[tid].categories = item.get("categories", ["other"])
                thread_map[tid].products = item.get("products", ["Generic"])
                total_classified += 1

    if not dry_run:
        logger.info("Classified %d / %d threads", total_classified, len(threads))

        # Write output — if limit was used, merge with full thread list
        all_threads = _load_threads()
        all_map = {t.thread_id: t for t in all_threads}
        for tid, t in thread_map.items():
            if t.categories:
                all_map[tid].categories = t.categories
                all_map[tid].products = t.products

        output = list(all_map.values())
        THREADS_CLASSIFIED_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(THREADS_CLASSIFIED_JSON, "w", encoding="utf-8") as f:
            json.dump(
                [t.model_dump(mode="json") for t in output],
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        logger.info("Output: %s", THREADS_CLASSIFIED_JSON)

        # Category distribution
        from collections import Counter
        cat_counts = Counter()
        prod_counts = Counter()
        for t in output:
            for c in t.categories:
                cat_counts[c] += 1
            for p in t.products:
                prod_counts[p] += 1

        logger.info("Category distribution:")
        for cat, count in cat_counts.most_common():
            logger.info("  %s: %d", cat, count)

    return threads


# ---------------------------------------------------------------------------
# Sender authority assessment
# ---------------------------------------------------------------------------

AUTHORITY_SYSTEM_PROMPT = """You are evaluating the expertise of contributors to a Juniper Networks internal security mailing list.

For each sender, you will see their name, email, total response count, and sample responses grouped by topic category.

Rate each sender:
1. **overall_authority**: "expert" (deep, authoritative knowledge), "knowledgeable" (solid understanding, generally reliable), "contributor" (participates but not consistently authoritative), or "unknown" (not enough data)
2. **expertise**: for each category they responded in, rate confidence as "high", "medium", or "low"
3. **rationale**: one sentence explaining your assessment

Respond ONLY with a JSON array. Each element must have:
- "email": the sender's email
- "overall_authority": one of the four levels above
- "expertise": list of {"category": str, "confidence": "high"|"medium"|"low"}
- "rationale": string

No explanation, no markdown fences, just the JSON array."""

AUTHORITY_BATCH_SIZE = 10


def _gather_sender_responses(
    threads: list[Thread],
) -> dict[str, dict]:
    """Gather response samples per sender, grouped by category.

    Returns {email: {"name": str, "total": int, "by_category": {cat: [excerpts]}}}
    """
    senders: dict[str, dict] = {}

    for t in threads:
        cats = t.categories or ["uncategorized"]
        for m in t.messages:
            if not m.body_own.strip():
                continue
            email = m.from_email.lower()
            if email not in senders:
                senders[email] = {
                    "name": m.from_name,
                    "total": 0,
                    "by_category": defaultdict(list),
                }
            senders[email]["total"] += 1
            # Keep up to 3 excerpts per category per sender
            for cat in cats:
                excerpts = senders[email]["by_category"][cat]
                if len(excerpts) < 3:
                    excerpts.append(m.body_own[:300])

    return senders


def _build_authority_prompt(sender_batch: list[tuple[str, dict]]) -> str:
    """Build a prompt for authority assessment of a batch of senders."""
    parts = []
    for email, info in sender_batch:
        cat_samples = []
        for cat, excerpts in info["by_category"].items():
            samples_text = "\n    ".join(f"- {e[:200]}" for e in excerpts)
            cat_samples.append(f"  {cat} ({len(excerpts)} samples):\n    {samples_text}")
        cats_block = "\n".join(cat_samples)
        parts.append(
            f"---\nemail: {email}\n"
            f"name: {info['name']}\n"
            f"total_responses: {info['total']}\n"
            f"responses_by_category:\n{cats_block}\n"
        )
    return "\n".join(parts)


def run_authority(
    min_responses: int = 3,
    force: bool = False,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
) -> list[SenderAuthority]:
    """Assess sender authority based on classified threads.

    Args:
        min_responses: Minimum responses to consider a sender (skip low-activity)
        force: Ignore cache
        dry_run: Preview without API calls
        model: Claude model to use
    """
    # Load classified threads (need categories populated)
    path = THREADS_CLASSIFIED_JSON if THREADS_CLASSIFIED_JSON.exists() else THREADS_JSON
    threads = _load_threads(path)
    logger.info("Loaded %d threads from %s", len(threads), path)

    # Gather sender data
    sender_data = _gather_sender_responses(threads)
    # Filter to senders with enough responses
    qualified = {
        email: info
        for email, info in sender_data.items()
        if info["total"] >= min_responses
    }
    logger.info(
        "Found %d senders with >= %d responses (out of %d total)",
        len(qualified), min_responses, len(sender_data),
    )

    # Process in batches
    sender_list = sorted(qualified.items(), key=lambda x: -x[1]["total"])
    authorities: list[SenderAuthority] = []

    for batch_start in range(0, len(sender_list), AUTHORITY_BATCH_SIZE):
        batch = sender_list[batch_start : batch_start + AUTHORITY_BATCH_SIZE]
        batch_num = batch_start // AUTHORITY_BATCH_SIZE + 1
        total_batches = (len(sender_list) + AUTHORITY_BATCH_SIZE - 1) // AUTHORITY_BATCH_SIZE

        prompt = _build_authority_prompt(batch)

        if dry_run:
            logger.info(
                "Batch %d/%d — %d senders (dry run)", batch_num, total_batches, len(batch)
            )
            for email, info in batch:
                logger.info("  %s (%s) — %d responses", email, info["name"], info["total"])
            continue

        logger.info("Batch %d/%d — assessing %d senders...", batch_num, total_batches, len(batch))

        response_text = call_claude(
            prompt=prompt,
            system=AUTHORITY_SYSTEM_PROMPT,
            model=model,
            cache_prefix="authority",
            force=force,
        )

        try:
            results = parse_json_response(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse batch %d response: %s", batch_num, e)
            logger.debug("Raw response: %s", response_text[:500])
            continue

        for item in results:
            email = item.get("email", "")
            info = qualified.get(email, {})
            expertise_list = []
            for exp in item.get("expertise", []):
                cat = exp.get("category", "")
                conf = exp.get("confidence", "medium")
                sample_count = len(info.get("by_category", {}).get(cat, []))
                expertise_list.append(SenderExpertise(
                    category=cat,
                    confidence=conf,
                    sample_count=sample_count,
                ))
            authorities.append(SenderAuthority(
                email=email,
                name=info.get("name", ""),
                total_responses=info.get("total", 0),
                expertise=expertise_list,
                overall_authority=item.get("overall_authority", "unknown"),
                rationale=item.get("rationale", ""),
            ))

    if not dry_run:
        # Sort by authority level then response count
        authority_order = {"expert": 0, "knowledgeable": 1, "contributor": 2, "unknown": 3}
        authorities.sort(
            key=lambda a: (authority_order.get(a.overall_authority, 9), -a.total_responses)
        )

        SENDER_AUTHORITY_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(SENDER_AUTHORITY_JSON, "w", encoding="utf-8") as f:
            json.dump(
                [a.model_dump(mode="json") for a in authorities],
                f,
                indent=2,
                ensure_ascii=False,
            )
        logger.info("Output: %s (%d senders)", SENDER_AUTHORITY_JSON, len(authorities))

        # Summary
        from collections import Counter
        level_counts = Counter(a.overall_authority for a in authorities)
        for level in ["expert", "knowledgeable", "contributor", "unknown"]:
            logger.info("  %s: %d", level, level_counts.get(level, 0))

    return authorities
