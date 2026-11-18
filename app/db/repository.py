"""Data-access helpers shared by the scraper, chatbot, agents and API."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Benchmark, Phone, Price, Specification

# Columns copied 1:1 from a parsed record onto the Phone row.
PHONE_FIELDS = [
    c for c in Phone.__table__.columns.keys() if c not in {"id", "scraped_at"}
]


@dataclass(frozen=True)
class Metric:
    column: str
    label: str
    unit: str
    higher_is_better: bool = True

    def fmt(self, value: Any) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not self.unit:
            return str(value)
        if self.unit == "$":
            return f"${value:,.2f}" if isinstance(value, float) else f"${value:,}"
        return f"{value:,} {self.unit}".strip() if isinstance(value, int) else f"{value} {self.unit}".strip()


METRICS: dict[str, Metric] = {m.column: m for m in [
    Metric("battery_active_use_h", "Battery active-use score (GSMArena test)", "h"),
    Metric("battery_endurance_h", "Battery endurance rating (GSMArena test)", "h"),
    Metric("battery_mah", "Battery capacity", "mAh"),
    Metric("charging_wired_w", "Wired charging", "W"),
    Metric("charging_wireless_w", "Wireless charging", "W"),
    Metric("main_camera_mp", "Main camera resolution", "MP"),
    Metric("optical_zoom_x", "Optical zoom", "x"),
    Metric("selfie_camera_mp", "Selfie camera resolution", "MP"),
    Metric("display_size_in", "Display size", "inches"),
    Metric("ppi", "Pixel density", "ppi"),
    Metric("refresh_rate_hz", "Refresh rate", "Hz"),
    Metric("peak_brightness_nits", "Peak brightness", "nits"),
    Metric("antutu_score", "AnTuTu score", "points"),
    Metric("geekbench_score", "GeekBench score", "points"),
    Metric("ram_gb", "Max RAM", "GB"),
    Metric("max_storage_gb", "Max storage", "GB"),
    Metric("weight_g", "Weight", "g", higher_is_better=False),
    Metric("price_usd", "Price (GSMArena listing)", "$", higher_is_better=False),
    Metric("release_year", "Release year", ""),
]}


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def save_phone(session: Session, record: dict[str, Any]) -> Phone:
    """Insert or update a phone (keyed by slug) together with its child rows."""
    phone = session.scalar(select(Phone).where(Phone.slug == record["slug"]))
    if phone is None:
        phone = Phone(slug=record["slug"])
        session.add(phone)
    for field in PHONE_FIELDS:
        if field in record:
            setattr(phone, field, record[field])

    # Delete old child rows first so re-scrapes don't collide on (phone_id, position).
    phone.specifications.clear()
    phone.prices.clear()
    phone.benchmarks.clear()
    session.flush()

    phone.specifications.extend(
        Specification(category=s["category"], name=s["name"], value=s["value"], position=i)
        for i, s in enumerate(record.get("specifications", []))
    )
    phone.prices.extend(Price(currency=p["currency"], amount=p["amount"]) for p in record.get("prices", []))
    phone.benchmarks.extend(
        Benchmark(name=b["name"], score=b.get("score"), unit=b.get("unit"), version=b.get("version"), raw=b["raw"])
        for b in record.get("benchmarks", [])
    )
    session.flush()
    return phone


def load_json(session: Session, path: Path) -> int:
    records = json.loads(path.read_text(encoding="utf-8"))
    for record in records:
        save_phone(session, record)
    return len(records)


def export_json(session: Session, path: Path) -> int:
    records = [phone_record(p) for p in list_phones(session)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(records)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _with_children(stmt):
    return stmt.options(
        selectinload(Phone.specifications), selectinload(Phone.prices), selectinload(Phone.benchmarks)
    )


def list_phones(session: Session) -> list[Phone]:
    return list(session.scalars(_with_children(select(Phone)).order_by(Phone.release_year, Phone.name)))


def get_phone(session: Session, key: str | int) -> Phone | None:
    """Lookup by id, slug, exact name or fuzzy model name ("s23 ultra")."""
    if isinstance(key, int) or str(key).isdigit():
        return session.get(Phone, int(key))
    phone = session.scalar(_with_children(select(Phone)).where((Phone.slug == key) | (Phone.name.ilike(key))))
    if phone:
        return phone
    from app.rag.entities import PhoneMatcher  # local import avoids a cycle

    phones = list_phones(session)
    matches = PhoneMatcher(phones).find(str(key))
    return matches[0] if matches else None


def rank_phones(session: Session, metric: str, limit: int = 5, ascending: bool | None = None) -> list[Phone]:
    m = METRICS[metric]
    col = getattr(Phone, metric)
    asc = (not m.higher_is_better) if ascending is None else ascending
    stmt = select(Phone).where(col.is_not(None)).order_by(col.asc() if asc else col.desc(), Phone.name).limit(limit)
    return list(session.scalars(stmt))


def phone_summary(phone: Phone) -> dict[str, Any]:
    return {
        "id": phone.id,
        "slug": phone.slug,
        "name": phone.name,
        "url": phone.url,
        "image_url": phone.image_url,
        "release_year": phone.release_year,
        "display": f"{phone.display_size_in}\" {phone.display_type or ''}".strip() if phone.display_size_in else None,
        "chipset": phone.chipset,
        "ram_gb": phone.ram_gb,
        "storage_options": phone.storage_options,
        "main_camera_mp": phone.main_camera_mp,
        "selfie_camera_mp": phone.selfie_camera_mp,
        "battery_mah": phone.battery_mah,
        "charging_wired_w": phone.charging_wired_w,
        "weight_g": phone.weight_g,
        "price_usd": phone.price_usd,
    }


def phone_record(phone: Phone) -> dict[str, Any]:
    """Full record (same shape the parser produces)."""
    record = {f: getattr(phone, f) for f in PHONE_FIELDS}
    record["id"] = phone.id
    record["specifications"] = [{"category": s.category, "name": s.name, "value": s.value} for s in phone.specifications]
    record["prices"] = [{"currency": p.currency, "amount": p.amount} for p in phone.prices]
    record["benchmarks"] = [
        {"name": b.name, "score": b.score, "unit": b.unit, "version": b.version, "raw": b.raw} for b in phone.benchmarks
    ]
    return record


def specs_by_category(phone: Phone, categories: Iterable[str] | None = None) -> dict[str, list[tuple[str, str]]]:
    wanted = {c.lower() for c in categories} if categories else None
    grouped: dict[str, list[tuple[str, str]]] = {}
    for s in phone.specifications:
        if wanted is None or s.category.lower() in wanted:
            grouped.setdefault(s.category, []).append((s.name, s.value))
    return grouped
