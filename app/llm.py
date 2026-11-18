"""LLM factory.

All supported providers expose an OpenAI-compatible chat API, so a single
LangChain `ChatOpenAI` client is pointed at whichever backend is configured:

  ollama       local open-source models (llama3.1, qwen2.5, mistral ...)  http://localhost:11434/v1
  huggingface  open-source models on the Hugging Face Inference router     https://router.huggingface.co/v1
  openai       optional, OpenAI hosted models
  none         no LLM: the chatbot/agents fall back to deterministic, data-grounded templates

LLM_PROVIDER=auto picks huggingface if HF_TOKEN is set, else a reachable Ollama, else OpenAI, else none.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import requests
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings

log = logging.getLogger(__name__)


@dataclass
class LLMInfo:
    provider: str
    model: str | None


def _ollama_available() -> bool:
    try:
        return requests.get(f"{settings.ollama_base_url}/api/tags", timeout=1.5).ok
    except requests.RequestException:
        return False


def _resolve_provider() -> str:
    p = settings.llm_provider
    if p != "auto":
        return p
    if settings.hf_token:
        return "huggingface"
    if _ollama_available():
        return "ollama"
    if settings.openai_api_key:
        return "openai"
    return "none"


@lru_cache(maxsize=1)
def get_llm() -> tuple[BaseChatModel | None, LLMInfo]:
    provider = _resolve_provider()
    if provider == "none":
        log.info("No LLM configured – using template-based answers")
        return None, LLMInfo("none", None)

    from langchain_openai import ChatOpenAI

    common = {"temperature": settings.llm_temperature, "timeout": settings.llm_timeout, "max_retries": 1}
    if provider == "ollama":
        model = settings.ollama_model
        llm = ChatOpenAI(model=model, base_url=f"{settings.ollama_base_url}/v1", api_key="ollama", **common)
    elif provider == "huggingface":
        if not settings.hf_token:
            raise RuntimeError("LLM_PROVIDER=huggingface requires HF_TOKEN")
        model = settings.hf_model
        llm = ChatOpenAI(model=model, base_url=settings.hf_base_url, api_key=settings.hf_token, **common)
    elif provider == "openai":
        model = settings.openai_model
        llm = ChatOpenAI(model=model, api_key=settings.openai_api_key, **common)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
    log.info("Using LLM provider=%s model=%s", provider, model)
    return llm, LLMInfo(provider, model)
