"""CLI for the Tech-Talk Knowledge Base pipeline."""

from __future__ import annotations

import json
import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """Tech-Talk Knowledge Base Pipeline."""
    _setup_logging(verbose)


@cli.command()
def parse() -> None:
    """Phase 1: Parse .eml files into messages.json."""
    from pipeline.phase1_parse import run
    messages = run()
    console.print(f"[green]Done.[/green] Parsed {len(messages)} messages.")


@cli.command()
def thread() -> None:
    """Phase 2: Reconstruct threads from messages.json."""
    from pipeline.config import MESSAGES_JSON
    if not MESSAGES_JSON.exists():
        console.print("[red]Error:[/red] messages.json not found. Run 'parse' first.")
        sys.exit(1)
    from pipeline.phase2_thread import run
    threads = run()
    console.print(f"[green]Done.[/green] Built {len(threads)} threads.")


@cli.command()
@click.option("--limit", default=0, type=int, help="Max threads to classify (0 = all)")
@click.option("--force", is_flag=True, help="Ignore cache, re-classify")
@click.option("--dry-run", is_flag=True, help="Preview without API calls")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
def classify(limit: int, force: bool, dry_run: bool, model: str) -> None:
    """Phase 3: Classify threads by topic and product (LLM)."""
    from pipeline.config import THREADS_JSON
    if not THREADS_JSON.exists():
        console.print("[red]Error:[/red] threads.json not found. Run 'thread' first.")
        sys.exit(1)
    from pipeline.phase3_classify import run
    threads = run(limit=limit, force=force, dry_run=dry_run, model=model)
    if not dry_run:
        classified = sum(1 for t in threads if t.categories)
        console.print(f"[green]Done.[/green] Classified {classified} threads.")


@cli.command()
@click.option("--min-responses", default=3, type=int, help="Min responses to evaluate a sender")
@click.option("--force", is_flag=True, help="Ignore cache")
@click.option("--dry-run", is_flag=True, help="Preview without API calls")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
def authority(min_responses: int, force: bool, dry_run: bool, model: str) -> None:
    """Phase 3b: Assess sender authority (LLM). Run after 'classify'."""
    from pipeline.config import THREADS_JSON
    if not THREADS_JSON.exists():
        console.print("[red]Error:[/red] threads.json not found. Run 'thread' first.")
        sys.exit(1)
    from pipeline.phase3_classify import run_authority
    senders = run_authority(min_responses=min_responses, force=force, dry_run=dry_run, model=model)
    if not dry_run:
        console.print(f"[green]Done.[/green] Assessed {len(senders)} senders.")


@cli.command()
@click.option("--limit", default=0, type=int, help="Max threads to assess (0 = all)")
@click.option("--force", is_flag=True, help="Ignore cache")
@click.option("--dry-run", is_flag=True, help="Preview without API calls")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
def assess(limit: int, force: bool, dry_run: bool, model: str) -> None:
    """Phase 4: Assess thread quality (LLM). Run after 'classify'."""
    from pipeline.config import THREADS_CLASSIFIED_JSON, THREADS_JSON
    if not THREADS_CLASSIFIED_JSON.exists() and not THREADS_JSON.exists():
        console.print("[red]Error:[/red] No thread data found. Run 'classify' first.")
        sys.exit(1)
    from pipeline.phase4_assess import run
    threads = run(limit=limit, force=force, dry_run=dry_run, model=model)
    if not dry_run:
        assessed = sum(1 for t in threads if t.quality)
        console.print(f"[green]Done.[/green] Assessed {assessed} threads.")


@cli.command()
@click.option("--limit", default=0, type=int, help="Max articles to generate (0 = all candidates)")
@click.option("--force", is_flag=True, help="Ignore cache")
@click.option("--dry-run", is_flag=True, help="Preview candidates without API calls")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
def curate(limit: int, force: bool, dry_run: bool, model: str) -> None:
    """Phase 5: Generate KB articles with doc enrichment (LLM). Run after 'assess'."""
    from pipeline.config import THREADS_ASSESSED_JSON, THREADS_CLASSIFIED_JSON, THREADS_JSON
    if not any(p.exists() for p in [THREADS_ASSESSED_JSON, THREADS_CLASSIFIED_JSON, THREADS_JSON]):
        console.print("[red]Error:[/red] No thread data found. Run 'assess' first.")
        sys.exit(1)
    from pipeline.phase5_curate import run
    articles = run(limit=limit, force=force, dry_run=dry_run, model=model)
    if not dry_run:
        console.print(f"[green]Done.[/green] Generated {len(articles)} KB articles.")


@cli.command()
@click.option("--keep-unvalidated", is_flag=True, help="Keep invalid links (flagged) instead of stripping")
@click.option("--dry-run", is_flag=True, help="List domains without making requests")
def validate(keep_unvalidated: bool, dry_run: bool) -> None:
    """Phase 6: Validate documentation links in KB articles."""
    from pipeline.config import KB_ARTICLES_JSON
    if not KB_ARTICLES_JSON.exists():
        console.print("[red]Error:[/red] kb_articles.json not found. Run 'curate' first.")
        sys.exit(1)
    from pipeline.phase6_validate import run
    articles = run(keep_unvalidated=keep_unvalidated, dry_run=dry_run)
    if not dry_run:
        total_links = sum(len(a.doc_links) + len(a.related_kbs) for a in articles)
        console.print(f"[green]Done.[/green] Validated links across {len(articles)} articles ({total_links} links remaining).")


@cli.command()
def stats() -> None:
    """Print corpus statistics."""
    from pipeline.config import MESSAGES_JSON, THREADS_JSON

    if MESSAGES_JSON.exists():
        with open(MESSAGES_JSON, "r") as f:
            messages = json.load(f)

        table = Table(title="Messages (Phase 1)")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        total = len(messages)
        replies = sum(1 for m in messages if m.get("is_reply"))
        with_warnings = sum(1 for m in messages if m.get("parse_warnings"))
        with_attachments = sum(1 for m in messages if m.get("attachments"))
        empty_body = sum(1 for m in messages if not m.get("body_own", "").strip())

        table.add_row("Total messages", str(total))
        table.add_row("Replies", str(replies))
        table.add_row("Thread starters", str(total - replies))
        table.add_row("With attachments", str(with_attachments))
        table.add_row("With parse warnings", str(with_warnings))
        table.add_row("Empty body_own", str(empty_body))

        # Top senders
        from collections import Counter
        senders = Counter(m.get("from_email", "") for m in messages)
        table.add_row("Unique senders", str(len(senders)))

        console.print(table)
        console.print()

        top_table = Table(title="Top 10 Senders")
        top_table.add_column("Email", style="bold")
        top_table.add_column("Count", justify="right")
        for email_addr, count in senders.most_common(10):
            top_table.add_row(email_addr, str(count))
        console.print(top_table)

    if THREADS_JSON.exists():
        with open(THREADS_JSON, "r") as f:
            threads = json.load(f)

        console.print()
        table = Table(title="Threads (Phase 2)")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        total = len(threads)
        multi = sum(1 for t in threads if t["message_count"] > 1)
        single_answered = sum(
            1 for t in threads if t["message_count"] == 1 and t["has_answer"]
        )
        unanswered = sum(1 for t in threads if not t["has_answer"])
        empty_question = sum(
            1 for t in threads if not t.get("original_question", "").strip()
        )

        table.add_row("Total threads", str(total))
        table.add_row("Multi-message threads", str(multi))
        table.add_row("Single-reply (answered)", str(single_answered))
        table.add_row("Unanswered", str(unanswered))
        table.add_row("Empty original_question", str(empty_question))

        # Size distribution of multi-message threads
        if multi:
            sizes = [t["message_count"] for t in threads if t["message_count"] > 1]
            table.add_row("Largest thread", f"{max(sizes)} messages")

        console.print(table)

    if not MESSAGES_JSON.exists() and not THREADS_JSON.exists():
        console.print("[yellow]No output files found. Run 'parse' and 'thread' first.[/yellow]")


if __name__ == "__main__":
    cli()
