"""Database tools used by the agents (LangChain tools, so they can also be bound to a tool-calling LLM)."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.db.repository import METRICS, get_phone, list_phones, phone_summary, specs_by_category
from app.db.session import SessionLocal


def _session_factory():
    return SessionLocal


@tool
def find_phone(name: str) -> dict[str, Any] | None:
    """Resolve a phone name such as 'Galaxy S23 Ultra' or 's22' to its database summary."""
    with _session_factory()() as db:
        phone = get_phone(db, name)
        return phone_summary(phone) if phone else None


@tool
def get_phone_specs(phone_id: int) -> dict[str, Any]:
    """Return the full GSMArena specification sheet for a phone, grouped by category."""
    with _session_factory()() as db:
        phone = get_phone(db, phone_id)
        if phone is None:
            return {}
        return {
            "name": phone.name,
            "url": phone.url,
            "key_metrics": {col: getattr(phone, col) for col in METRICS if getattr(phone, col) is not None},
            "antutu_version": phone.antutu_version,
            "chipset": phone.chipset,
            "display_type": phone.display_type,
            "os": phone.os,
            "ip_rating": phone.ip_rating,
            "storage_options": phone.storage_options,
            "specs": {cat: [f"{n}: {v}" for n, v in rows] for cat, rows in specs_by_category(phone).items()
                      if cat != "Network"},
        }


@tool
def get_benchmarks(phone_id: int) -> list[dict[str, Any]]:
    """Return GSMArena lab test results (AnTuTu, GeekBench, battery, brightness, loudspeaker) for a phone."""
    with _session_factory()() as db:
        phone = get_phone(db, phone_id)
        return [{"name": b.name, "score": b.score, "unit": b.unit, "version": b.version} for b in phone.benchmarks] if phone else []


@tool
def get_prices(phone_id: int) -> list[dict[str, Any]]:
    """Return the listed prices for a phone in every available currency."""
    with _session_factory()() as db:
        phone = get_phone(db, phone_id)
        return [{"currency": p.currency, "amount": p.amount} for p in phone.prices] if phone else []


@tool
def get_catalog_metrics() -> list[dict[str, Any]]:
    """Return the key numeric metrics for every phone in the database (used for market positioning)."""
    with _session_factory()() as db:
        return [
            {"id": p.id, "name": p.name, "antutu_version": p.antutu_version,
             **{col: getattr(p, col) for col in METRICS}}
            for p in list_phones(db)
        ]


SPEC_TOOLS = [find_phone, get_phone_specs, get_benchmarks, get_prices, get_catalog_metrics]
