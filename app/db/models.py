"""Relational schema for scraped phone data.

phones          one row per phone with normalised, query-friendly columns
specifications  every raw spec row from GSMArena (category / name / value)
prices          listed prices per currency
benchmarks      GSMArena "Our Tests" results (AnTuTu, GeekBench, battery tests ...)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Phone(Base):
    __tablename__ = "phones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    brand: Mapped[str] = mapped_column(String(60), default="Samsung")
    url: Mapped[str] = mapped_column(String(300))
    image_url: Mapped[str | None] = mapped_column(String(300))

    # Launch
    announced: Mapped[str | None] = mapped_column(String(120))
    release_status: Mapped[str | None] = mapped_column(String(200))
    release_year: Mapped[int | None] = mapped_column(Integer)

    # Body
    dimensions: Mapped[str | None] = mapped_column(String(200))
    weight_g: Mapped[float | None] = mapped_column(Float)
    build: Mapped[str | None] = mapped_column(Text)
    ip_rating: Mapped[str | None] = mapped_column(String(40))

    # Display
    display_size_in: Mapped[float | None] = mapped_column(Float)
    display_type: Mapped[str | None] = mapped_column(Text)
    display_resolution: Mapped[str | None] = mapped_column(String(200))
    refresh_rate_hz: Mapped[int | None] = mapped_column(Integer)
    ppi: Mapped[int | None] = mapped_column(Integer)
    peak_brightness_nits: Mapped[int | None] = mapped_column(Integer)

    # Platform
    os: Mapped[str | None] = mapped_column(String(200))
    chipset: Mapped[str | None] = mapped_column(String(200))
    cpu: Mapped[str | None] = mapped_column(Text)
    gpu: Mapped[str | None] = mapped_column(String(200))

    # Memory
    ram_gb: Mapped[float | None] = mapped_column(Float)
    storage_options: Mapped[str | None] = mapped_column(String(200))
    max_storage_gb: Mapped[int | None] = mapped_column(Integer)

    # Cameras
    main_camera_mp: Mapped[float | None] = mapped_column(Float)
    main_camera_count: Mapped[int | None] = mapped_column(Integer)
    main_camera_summary: Mapped[str | None] = mapped_column(Text)
    main_camera_video: Mapped[str | None] = mapped_column(Text)
    selfie_camera_mp: Mapped[float | None] = mapped_column(Float)
    optical_zoom_x: Mapped[float | None] = mapped_column(Float)

    # Battery
    battery_mah: Mapped[int | None] = mapped_column(Integer)
    charging_wired_w: Mapped[float | None] = mapped_column(Float)
    charging_wireless_w: Mapped[float | None] = mapped_column(Float)
    battery_active_use_h: Mapped[float | None] = mapped_column(Float)
    battery_endurance_h: Mapped[float | None] = mapped_column(Float)

    # Tests / price (denormalised copies of benchmarks/prices for fast ranking)
    antutu_score: Mapped[int | None] = mapped_column(Integer)
    antutu_version: Mapped[str | None] = mapped_column(String(20))
    geekbench_score: Mapped[int | None] = mapped_column(Integer)
    geekbench_version: Mapped[str | None] = mapped_column(String(20))
    price_usd: Mapped[float | None] = mapped_column(Float)
    price_text: Mapped[str | None] = mapped_column(String(200))

    colors: Mapped[str | None] = mapped_column(Text)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    specifications: Mapped[list["Specification"]] = relationship(
        back_populates="phone", cascade="all, delete-orphan", order_by="Specification.position"
    )
    prices: Mapped[list["Price"]] = relationship(back_populates="phone", cascade="all, delete-orphan")
    benchmarks: Mapped[list["Benchmark"]] = relationship(back_populates="phone", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Phone {self.name}>"


class Specification(Base):
    __tablename__ = "specifications"
    __table_args__ = (UniqueConstraint("phone_id", "position", name="uq_spec_phone_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_id: Mapped[int] = mapped_column(ForeignKey("phones.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)

    phone: Mapped[Phone] = relationship(back_populates="specifications")


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_id: Mapped[int] = mapped_column(ForeignKey("phones.id", ondelete="CASCADE"), index=True)
    currency: Mapped[str] = mapped_column(String(8))
    amount: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(60), default="GSMArena")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    phone: Mapped[Phone] = relationship(back_populates="prices")


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_id: Mapped[int] = mapped_column(ForeignKey("phones.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    score: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(30))
    version: Mapped[str | None] = mapped_column(String(60))
    raw: Mapped[str] = mapped_column(String(300))

    phone: Mapped[Phone] = relationship(back_populates="benchmarks")
