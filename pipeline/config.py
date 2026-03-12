from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EML_DIR = PROJECT_ROOT / "eml"
OUTPUT_DIR = PROJECT_ROOT / "output"
LLM_CACHE_DIR = OUTPUT_DIR / "llm_cache"

MESSAGES_JSON = OUTPUT_DIR / "messages.json"
THREADS_JSON = OUTPUT_DIR / "threads.json"
SENDER_AUTHORITY_JSON = OUTPUT_DIR / "sender_authority.json"
THREADS_CLASSIFIED_JSON = OUTPUT_DIR / "threads_classified.json"
THREADS_ASSESSED_JSON = OUTPUT_DIR / "threads_assessed.json"
KB_ARTICLES_JSON = OUTPUT_DIR / "kb_articles.json"
KB_INDEX_JSON = OUTPUT_DIR / "kb_index.json"

# Ensure output dirs exist
OUTPUT_DIR.mkdir(exist_ok=True)
LLM_CACHE_DIR.mkdir(exist_ok=True)
