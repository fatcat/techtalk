from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Attachment(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class ParsedMessage(BaseModel):
    message_id: str
    filename: str
    date: Optional[datetime] = None
    from_name: str = ""
    from_email: str = ""
    to: list[str] = []
    cc: list[str] = []
    subject: str = ""
    thread_topic: str = ""
    thread_index: str = ""
    in_reply_to: Optional[str] = None
    references: list[str] = []
    is_reply: bool = False
    body_plain: str = ""
    body_own: str = ""
    body_quoted: str = ""
    attachments: list[Attachment] = []
    parse_warnings: list[str] = []


class ThreadMessage(BaseModel):
    message_id: str
    date: Optional[datetime] = None
    from_name: str = ""
    from_email: str = ""
    body_own: str = ""
    is_thread_starter: bool = False


class Thread(BaseModel):
    thread_id: str
    thread_topic: str
    messages: list[ThreadMessage] = []
    original_question: str = ""
    participant_count: int = 0
    message_count: int = 0
    date_first: Optional[datetime] = None
    date_last: Optional[datetime] = None
    has_answer: bool = False
    # Phase 3 additions
    categories: list[str] = []
    products: list[str] = []
    # Phase 4 additions
    quality: str = ""
    quality_rationale: str = ""
    kb_worthiness: int = 0


class SenderExpertise(BaseModel):
    """A sender's expertise in a specific category."""
    category: str
    confidence: str = "medium"  # "high", "medium", "low"
    sample_count: int = 0  # how many responses informed this rating


class SenderAuthority(BaseModel):
    """Authority profile for a single sender."""
    email: str
    name: str = ""
    total_responses: int = 0
    expertise: list[SenderExpertise] = []
    overall_authority: str = "unknown"  # "expert", "knowledgeable", "contributor", "unknown"
    rationale: str = ""


class DocLink(BaseModel):
    """A reference to Juniper TechLibrary or KB documentation."""
    url: str
    title: str
    description: str = ""
    validated: Optional[bool] = None  # set by Phase 6


class CLIExample(BaseModel):
    """A Junos CLI command example."""
    command: str
    description: str = ""
    context: str = ""  # "show", "set", "request", etc.


class KBArticle(BaseModel):
    article_id: str
    title: str
    source_thread_ids: list[str] = []
    products: list[str] = []
    categories: list[str] = []
    junos_versions: list[str] = []
    problem: str = ""
    cause: Optional[str] = None
    solution: str = ""
    additional_notes: Optional[str] = None
    confidence: str = "medium"
    original_date: Optional[datetime] = None
    tags: list[str] = []
    # Documentation enrichment
    doc_links: list[DocLink] = []
    cli_examples: list[CLIExample] = []
    related_kbs: list[DocLink] = []


class TagCloudEntry(BaseModel):
    """Pre-computed tag weight for the UI word cloud."""
    tag: str
    count: int = 0
    categories: list[str] = []


class KBIndex(BaseModel):
    generated_at: datetime
    total_articles: int = 0
    total_threads: int = 0
    total_messages: int = 0
    categories: list[str] = []
    products: list[str] = []
    articles: list[KBArticle] = []
    sender_authority: list[SenderAuthority] = []
    tag_cloud: list[TagCloudEntry] = []
