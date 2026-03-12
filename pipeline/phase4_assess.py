"""Phase 4: LLM-based quality assessment of threads."""

from __future__ import annotations

import json
import logging

from .config import (
    SENDER_AUTHORITY_JSON,
    THREADS_ASSESSED_JSON,
    THREADS_CLASSIFIED_JSON,
    THREADS_JSON,
)
from .llm_client import call_claude, parse_json_response
from .schemas import SenderAuthority, Thread

logger = logging.getLogger(__name__)

QUALITY_LABELS = [
    "authoritative_answer",
    "workaround",
    "unresolved",
    "discussion",
    "incorrect_info",
    "unanswerable",
]

SYSTEM_PROMPT = """You are a senior network security engineer assessing the quality of Q&A threads from a Juniper Networks internal mailing list.

For each thread you will see:
- The topic and original question
- One or more responses
- The responder's authority level (expert / knowledgeable / contributor / unknown)

Rate each thread:
1. **quality**: one of: "authoritative_answer" (clear, definitive, correct answer), "workaround" (functional but non-ideal solution), "unresolved" (question asked but no satisfactory answer), "discussion" (informational exchange, no clear Q&A), "incorrect_info" (contains wrong or misleading information)
2. **quality_rationale**: one sentence explaining your rating
3. **kb_worthiness**: 1-5 score for how valuable this would be as a knowledge base article (5 = extremely useful, broadly applicable; 1 = trivial or too niche)

Weight the responder's authority level when assessing quality:
- "expert" responses should be trusted more highly
- "knowledgeable" responses are generally reliable
- "contributor" and "unknown" responses need stronger evidence in the text itself

Respond ONLY with a JSON array. Each element must have:
- "thread_id": string
- "quality": one of the labels above
- "quality_rationale": string
- "kb_worthiness": integer 1-5

No explanation, no markdown fences, just the JSON array."""

BATCH_SIZE = 10


def _load_authority() -> dict[str, SenderAuthority]:
    """Load sender authority data into a lookup by email."""
    if not SENDER_AUTHORITY_JSON.exists():
        logger.warning("sender_authority.json not found — proceeding without authority data")
        return {}
    with open(SENDER_AUTHORITY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {a["email"].lower(): SenderAuthority.model_validate(a) for a in data}


def _load_threads() -> list[Thread]:
    """Load the best available thread data (classified > plain)."""
    path = THREADS_CLASSIFIED_JSON if THREADS_CLASSIFIED_JSON.exists() else THREADS_JSON
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Thread.model_validate(t) for t in data]


def _build_batch_prompt(
    threads: list[Thread],
    authority_map: dict[str, SenderAuthority],
) -> str:
    """Build a prompt for quality assessment of a batch of threads."""
    parts = []
    for t in threads:
        # Gather responses with authority info
        responses = []
        for m in t.messages:
            if m.body_own.strip():
                auth = authority_map.get(m.from_email.lower())
                auth_level = auth.overall_authority if auth else "unknown"
                responses.append(
                    f"  [{auth_level}] {m.from_name}: {m.body_own[:600]}"
                )

        responses_block = "\n".join(responses) if responses else "  (no responses)"

        parts.append(
            f"---\nthread_id: {t.thread_id}\n"
            f"topic: {t.thread_topic}\n"
            f"categories: {', '.join(t.categories) if t.categories else 'uncategorized'}\n"
            f"question: {t.original_question[:1000]}\n"
            f"responses:\n{responses_block}\n"
        )
    return "\n".join(parts)


def run(
    limit: int = 0,
    force: bool = False,
    dry_run: bool = False,
    model: str = "claude-sonnet-4-20250514",
) -> list[Thread]:
    """Assess thread quality with sender authority weighting.

    Args:
        limit: Max threads to process (0 = all)
        force: Ignore cache
        dry_run: Preview without API calls
        model: Claude model to use
    """
    threads = _load_threads()
    authority_map = _load_authority()
    logger.info("Loaded %d threads, %d sender authority profiles", len(threads), len(authority_map))

    # Separate unanswerable (auto-label) from those needing LLM
    to_assess: list[Thread] = []
    auto_labeled = 0
    for t in threads:
        if not t.has_answer:
            t.quality = "unanswerable"
            t.quality_rationale = "No reply in corpus"
            t.kb_worthiness = 0
            auto_labeled += 1
        else:
            to_assess.append(t)

    logger.info("Auto-labeled %d unanswerable threads", auto_labeled)

    if limit:
        to_assess = to_assess[:limit]
        logger.info("Limited to %d threads for LLM assessment", limit)

    # Index for updating
    thread_map = {t.thread_id: t for t in to_assess}

    total_assessed = 0
    for batch_start in range(0, len(to_assess), BATCH_SIZE):
        batch = to_assess[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(to_assess) + BATCH_SIZE - 1) // BATCH_SIZE

        prompt = _build_batch_prompt(batch, authority_map)

        if dry_run:
            logger.info("Batch %d/%d — %d threads (dry run)", batch_num, total_batches, len(batch))
            continue

        logger.info("Batch %d/%d — assessing %d threads...", batch_num, total_batches, len(batch))

        response_text = call_claude(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=model,
            cache_prefix="assess",
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
                thread_map[tid].quality = item.get("quality", "discussion")
                thread_map[tid].quality_rationale = item.get("quality_rationale", "")
                thread_map[tid].kb_worthiness = item.get("kb_worthiness", 1)
                total_assessed += 1

    if not dry_run:
        logger.info("LLM-assessed %d / %d threads", total_assessed, len(to_assess))

        # Merge into full thread list
        all_threads = _load_threads()
        all_map = {t.thread_id: t for t in all_threads}
        # Apply auto-labels
        for t in all_threads:
            if not t.has_answer:
                t.quality = "unanswerable"
                t.quality_rationale = "No reply in corpus"
                t.kb_worthiness = 0
        # Apply LLM labels
        for tid, t in thread_map.items():
            if t.quality:
                all_map[tid].quality = t.quality
                all_map[tid].quality_rationale = t.quality_rationale
                all_map[tid].kb_worthiness = t.kb_worthiness

        output = list(all_map.values())
        THREADS_ASSESSED_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(THREADS_ASSESSED_JSON, "w", encoding="utf-8") as f:
            json.dump(
                [t.model_dump(mode="json") for t in output],
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        logger.info("Output: %s", THREADS_ASSESSED_JSON)

        # Quality distribution
        from collections import Counter
        quality_counts = Counter(t.quality for t in output if t.quality)
        worthiness_counts = Counter(t.kb_worthiness for t in output if t.kb_worthiness)

        logger.info("Quality distribution:")
        for label in QUALITY_LABELS:
            logger.info("  %s: %d", label, quality_counts.get(label, 0))

        kb_candidates = sum(
            1 for t in output
            if t.quality in ("authoritative_answer", "workaround") and t.kb_worthiness >= 3
        )
        logger.info("KB candidates (quality + worthiness >= 3): %d", kb_candidates)

    return to_assess
