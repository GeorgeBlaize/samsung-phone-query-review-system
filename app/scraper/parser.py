"""Parse a GSMArena phone spec page into a structured record.

The record format (a plain dict) is shared by the scraper, the JSON export and
the database loader, so the DB can be rebuilt from `data/phones.json` without
re-scraping.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

NUM = r"(\d+(?:\.\d+)?)"

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}


def _clean(text: str) -> str:
    text = text.replace(" ", " ").replace("\xa0", " ").replace("​", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _cell_text(td: Tag) -> str:
    # <br> separates sub-values (e.g. camera modules); keep them on separate lines.
    for br in td.find_all("br"):
        br.replace_with("\n")
    lines = [_clean(line) for line in td.get_text().split("\n")]
    return "\n".join(line for line in lines if line)


def _first_float(pattern: str, text: str | None, flags: int = re.I) -> float | None:
    if not text:
        return None
    m = re.search(pattern, text, flags)
    return float(m.group(1)) if m else None


def _to_int(value: float | None) -> int | None:
    return int(round(value)) if value is not None else None


# ---------------------------------------------------------------------------
# Field-level parsers (pure functions, unit-tested)
# ---------------------------------------------------------------------------

def parse_prices(text: str | None) -> list[dict[str, Any]]:
    """'$ 230.61 / € 276.98 / £ 215.00'  or  'About 800 EUR'  ->  [{currency, amount}]"""
    if not text:
        return []
    prices: list[dict[str, Any]] = []
    for symbol, code in CURRENCY_SYMBOLS.items():
        m = re.search(re.escape(symbol) + r"\s*([\d,]+(?:\.\d+)?)", text)
        if m:
            prices.append({"currency": code, "amount": float(m.group(1).replace(",", ""))})
    m = re.search(r"About\s+([\d,]+(?:\.\d+)?)\s+([A-Z]{3})", text)
    if m and not any(p["currency"] == m.group(2) for p in prices):
        prices.append({"currency": m.group(2), "amount": float(m.group(1).replace(",", ""))})
    return prices


def _version_key(version: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", version or "")) or (0,)


def parse_benchmarks(test_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse GSMArena "Our Tests" rows.

    'AnTuTu: 745496 (v8), 881428 (v9)' yields two AnTuTu rows (one per version).
    """
    out: list[dict[str, Any]] = []
    for row in test_rows:
        for line in row["value"].split("\n"):
            line = line.strip()
            m = re.match(r"([A-Za-z][\w .]*?):\s*(.+)", line)
            if m and row["name"] == "Performance":
                for score, unit, version in re.findall(NUM + r"\s*(fps)?\s*(?:\(([^)]+)\))?", m.group(2)):
                    out.append({"name": m.group(1).strip(), "score": float(score), "unit": unit or "points",
                                "version": version or None, "raw": line})
            elif "Endurance rating" in line:
                out.append({"name": "Battery endurance rating", "unit": "hours", "version": "old test",
                            "score": _first_float(r"Endurance rating\s*" + NUM, line), "raw": line})
            elif "Active use score" in line:
                t = re.search(r"(\d+):(\d+)\s*h", line)
                out.append({"name": "Battery active use score", "unit": "hours", "version": "new test",
                            "score": round(int(t.group(1)) + int(t.group(2)) / 60, 2) if t else None, "raw": line})
            elif "nits" in line and row["name"] == "Display":
                out.append({"name": "Measured max brightness", "unit": "nits", "version": None,
                            "score": _first_float(NUM + r"\s*nits", line), "raw": line})
            elif "LUFS" in line:
                out.append({"name": "Loudspeaker loudness", "unit": "LUFS", "version": None,
                            "score": _first_float(r"(-?\d+(?:\.\d+)?)\s*LUFS", line), "raw": line})
    return out


def latest_benchmark(benchmarks: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    matches = [b for b in benchmarks if b["name"].lower().startswith(prefix)]
    return max(matches, key=lambda b: _version_key(b["version"])) if matches else None


def parse_memory(text: str | None) -> tuple[float | None, str | None, int | None]:
    """'128GB 8GB RAM, 256GB 8GB RAM, 1TB 12GB RAM' -> (max RAM, '128GB/256GB/1TB', max storage GB)"""
    if not text:
        return None, None, None
    rams = [float(x) for x in re.findall(NUM + r"\s*GB RAM", text)]
    storages: list[str] = []
    for amount, unit in re.findall(r"(\d+)\s*(GB|TB)(?!\s*RAM)", text):
        label = f"{amount}{unit}"
        if label not in storages:
            storages.append(label)
    gb = [int(a) * (1024 if u == "TB" else 1) for a, u in (re.match(r"(\d+)(GB|TB)", s).groups() for s in storages)]
    return (max(rams) if rams else None, "/".join(storages) or None, max(gb) if gb else None)


def parse_camera(modules: str | None) -> tuple[float | None, int | None, float | None]:
    """Return (highest MP, number of modules, best optical zoom)."""
    if not modules:
        return None, None, None
    lines = [line for line in modules.split("\n") if re.search(r"\d+\s*MP", line)]
    mps = [float(x) for x in re.findall(NUM + r"\s*MP", modules)]
    zooms = [float(x) for x in re.findall(NUM + r"x optical zoom", modules)]
    return (max(mps) if mps else None, len(lines) or None, max(zooms) if zooms else None)


def parse_charging(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    wired = _first_float(NUM + r"\s*W wired", text)
    wireless = _first_float(NUM + r"\s*W wireless", text)
    return wired, wireless


# ---------------------------------------------------------------------------
# Page parser
# ---------------------------------------------------------------------------

def parse_phone_page(html: str, slug: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one("h1.specs-phone-name-title")
    if title is None:
        raise ValueError(f"{url}: not a GSMArena spec page (no title found)")
    name = _clean(title.get_text())
    img = soup.select_one(".specs-photo-main img")

    specs: list[dict[str, Any]] = []
    by_key: dict[str, str] = {}  # data-spec attribute -> text
    for table in soup.select("#specs-list table"):
        th = table.find("th")
        if th is None:
            continue
        category = _clean(th.get_text())
        last_name = ""
        for tr in table.find_all("tr"):
            ttl, nfo = tr.find("td", class_="ttl"), tr.find("td", class_="nfo")
            if nfo is None:
                continue
            spec_name = _clean(ttl.get_text()) if ttl else ""
            value = _cell_text(nfo)
            if not value:
                continue
            if not spec_name:  # continuation row of the previous spec
                spec_name = last_name or category
                if specs and specs[-1]["category"] == category and specs[-1]["name"] == spec_name:
                    specs[-1]["value"] += "\n" + value
                    if nfo.get("data-spec"):
                        by_key[nfo["data-spec"]] = value
                    continue
            last_name = spec_name
            specs.append({"category": category, "name": spec_name, "value": value})
            if nfo.get("data-spec"):
                by_key[nfo["data-spec"]] = value

    def spec(category: str, spec_name: str) -> str | None:
        for s in specs:
            if s["category"] == category and s["name"].lower() == spec_name.lower():
                return s["value"]
        return None

    display_size = _first_float(NUM + r"\s*inches", by_key.get("displaysize"))
    display_type = by_key.get("displaytype")
    resolution = by_key.get("displayresolution")
    ram, storage_opts, max_storage = parse_memory(by_key.get("internalmemory"))
    main_mp, cam_count, zoom = parse_camera(by_key.get("cam1modules"))
    selfie_mp, _, _ = parse_camera(by_key.get("cam2modules"))
    wired, wireless = parse_charging(spec("Battery", "Charging"))
    benchmarks = parse_benchmarks([s for s in specs if s["category"] in ("Our Tests", "Tests")])
    prices = parse_prices(by_key.get("price"))

    antutu, geekbench = latest_benchmark(benchmarks, "antutu"), latest_benchmark(benchmarks, "geekbench")
    active, endurance = latest_benchmark(benchmarks, "battery active"), latest_benchmark(benchmarks, "battery endurance")
    usd = next((p["amount"] for p in prices if p["currency"] == "USD"), None)
    body_other = " ".join(filter(None, [spec("Body", "Build"), by_key.get("bodyother"), spec("Body", "SIM")]))
    ip = re.search(r"\bIP\d{2}\w?\b", body_other)
    year = _first_float(r"(\d{4})", by_key.get("year"))

    return {
        "slug": slug,
        "name": name,
        "brand": "Samsung",
        "url": url,
        "image_url": img["src"] if img and img.get("src") else None,
        "announced": by_key.get("year"),
        "release_status": by_key.get("status"),
        "release_year": _to_int(year),
        "dimensions": by_key.get("dimensions"),
        "weight_g": _first_float(NUM + r"\s*g\b", by_key.get("weight")),
        "build": by_key.get("build"),
        "ip_rating": ip.group(0) if ip else None,
        "display_size_in": display_size,
        "display_type": display_type,
        "display_resolution": resolution,
        "refresh_rate_hz": _to_int(_first_float(r"(\d+)\s*Hz", display_type)),
        "ppi": _to_int(_first_float(r"~?(\d+)\s*ppi", resolution)),
        "peak_brightness_nits": _to_int(_first_float(r"(\d+)\s*nits\s*\(peak\)", display_type)),
        "os": by_key.get("os"),
        "chipset": by_key.get("chipset"),
        "cpu": by_key.get("cpu"),
        "gpu": by_key.get("gpu"),
        "ram_gb": ram,
        "storage_options": storage_opts,
        "max_storage_gb": max_storage,
        "main_camera_mp": main_mp,
        "main_camera_count": cam_count,
        "main_camera_summary": by_key.get("cam1modules"),
        "main_camera_video": by_key.get("cam1video"),
        "selfie_camera_mp": selfie_mp,
        "optical_zoom_x": zoom,
        "battery_mah": _to_int(_first_float(r"(\d+)\s*mAh", by_key.get("batdescription1"))),
        "charging_wired_w": wired,
        "charging_wireless_w": wireless,
        "battery_active_use_h": active["score"] if active else None,
        "battery_endurance_h": endurance["score"] if endurance else None,
        "antutu_score": _to_int(antutu["score"]) if antutu else None,
        "antutu_version": antutu["version"] if antutu else None,
        "geekbench_score": _to_int(geekbench["score"]) if geekbench else None,
        "geekbench_version": geekbench["version"] if geekbench else None,
        "price_usd": usd,
        "price_text": by_key.get("price"),
        "colors": by_key.get("colors"),
        "specifications": specs,
        "prices": prices,
        "benchmarks": benchmarks,
    }
