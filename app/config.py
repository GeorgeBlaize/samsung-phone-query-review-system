"""Central configuration, read from environment variables / a .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # --- Database -------------------------------------------------------
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/samsung_phones",
        )
    )

    # --- Scraper --------------------------------------------------------
    scrape_delay_seconds: float = field(default_factory=lambda: float(_env("SCRAPE_DELAY_SECONDS", "3")))
    scrape_cache_dir: Path = field(default_factory=lambda: Path(_env("SCRAPE_CACHE_DIR", str(DATA_DIR / "raw"))))
    export_json_path: Path = field(default_factory=lambda: Path(_env("EXPORT_JSON_PATH", str(DATA_DIR / "phones.json"))))

    # --- LLM ------------------------------------------------------------
    # auto | ollama | huggingface | openai | none
    llm_provider: str = field(default_factory=lambda: (_env("LLM_PROVIDER", "auto") or "auto").lower())
    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "120")))

    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.1:8b"))

    hf_token: str | None = field(default_factory=lambda: _env("HF_TOKEN"))
    hf_base_url: str = field(default_factory=lambda: _env("HF_BASE_URL", "https://router.huggingface.co/v1"))
    hf_model: str = field(default_factory=lambda: _env("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct"))

    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))

    # --- RAG ------------------------------------------------------------
    # tfidf (no extra deps) | sentence-transformers (needs `pip install sentence-transformers`)
    embedding_backend: str = field(default_factory=lambda: (_env("EMBEDDING_BACKEND", "tfidf") or "tfidf").lower())
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
    retrieval_top_k: int = field(default_factory=lambda: int(_env("RETRIEVAL_TOP_K", "6")))
    chat_history_turns: int = field(default_factory=lambda: int(_env("CHAT_HISTORY_TURNS", "4")))

    # --- Agents ---------------------------------------------------------
    review_max_revisions: int = field(default_factory=lambda: int(_env("REVIEW_MAX_REVISIONS", "1")))


settings = Settings()
