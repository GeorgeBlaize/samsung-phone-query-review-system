"""Turn database rows into text chunks for retrieval (one chunk per phone x spec category)."""
from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Phone
from app.db.repository import METRICS, specs_by_category

# Spec categories that are mostly noise for Q&A (band lists etc.) are kept but de-prioritised.
LOW_VALUE_CATEGORIES = {"Network"}


@dataclass
class Chunk:
    id: str
    phone_id: int
    phone_name: str
    category: str
    text: str


def overview_text(phone: Phone) -> str:
    rows = [f"{phone.name} – key facts (source: GSMArena)"]
    for col, metric in METRICS.items():
        value = getattr(phone, col)
        if value is not None:
            extra = ""
            if col == "antutu_score" and phone.antutu_version:
                extra = f" ({phone.antutu_version})"
            if col == "geekbench_score" and phone.geekbench_version:
                extra = f" ({phone.geekbench_version})"
            rows.append(f"- {metric.label}: {metric.fmt(value)}{extra}")
    for label, value in [("Chipset", phone.chipset), ("Display", phone.display_type), ("OS", phone.os),
                         ("Storage options", phone.storage_options), ("Water resistance", phone.ip_rating),
                         ("Price text", phone.price_text)]:
        if value:
            rows.append(f"- {label}: {value}")
    return "\n".join(rows)


def build_chunks(phones: list[Phone]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for phone in phones:
        chunks.append(Chunk(f"{phone.slug}#overview", phone.id, phone.name, "Overview", overview_text(phone)))
        for category, rows in specs_by_category(phone).items():
            body = "\n".join(f"- {name}: {value.replace(chr(10), '; ')}" for name, value in rows)
            chunks.append(Chunk(
                id=f"{phone.slug}#{category.lower().replace(' ', '-')}",
                phone_id=phone.id,
                phone_name=phone.name,
                category=category,
                text=f"{phone.name} – {category}\n{body}",
            ))
    return chunks
