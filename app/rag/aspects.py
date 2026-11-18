"""Query understanding: which spec aspects a question is about and whether it asks for a ranking."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Aspect:
    name: str
    keywords: tuple[str, ...]
    categories: tuple[str, ...]
    # ranking metrics in priority order; (column, ascending?) – None means use metric default
    metrics: tuple[str, ...] = field(default_factory=tuple)


ASPECTS: dict[str, Aspect] = {a.name: a for a in [
    Aspect("battery", ("battery", "charging", "charge", "endurance", "mah", "battery life", "last", "lasts"),
           ("Battery", "Our Tests"), ("battery_active_use_h", "battery_endurance_h", "battery_mah")),
    Aspect("charging", ("charging", "charger", "fast charge", "wireless charging", "watt"),
           ("Battery",), ("charging_wired_w", "charging_wireless_w")),
    Aspect("camera", ("camera", "cameras", "photo", "photos", "picture", "selfie", "video", "zoom", "lens",
                      "megapixel", "mp", "telephoto", "ultrawide", "photography"),
           ("Main Camera", "Selfie camera"), ("main_camera_mp", "optical_zoom_x", "selfie_camera_mp")),
    Aspect("display", ("display", "screen", "refresh", "resolution", "brightness", "ppi", "inch", "inches",
                       "amoled", "size", "bright"),
           ("Display",), ("display_size_in", "ppi", "refresh_rate_hz", "peak_brightness_nits")),
    Aspect("performance", ("performance", "processor", "chipset", "chip", "cpu", "gpu", "fast", "fastest", "speed",
                           "benchmark", "antutu", "geekbench", "gaming", "snapdragon", "exynos", "powerful"),
           # GeekBench 5 / 6 kept separate (different scales); AnTuTu versions differ (v8/v9/v10)
           ("Platform", "Memory", "Our Tests"), ("geekbench_score", "geekbench6_score", "antutu_score")),
    Aspect("memory", ("ram", "storage", "memory", "gb", "tb"), ("Memory",), ("ram_gb", "max_storage_gb")),
    Aspect("price", ("price", "prices", "cost", "costs", "cheap", "cheapest", "expensive", "afford", "affordable",
                     "budget", "value", "$", "usd", "money", "pricing"),
           ("Misc",), ("price_usd",)),
    Aspect("design", ("weight", "heavy", "heaviest", "light", "lightest", "dimensions", "build", "waterproof",
                      "water", "ip68", "body", "thin", "glass", "design", "colors", "colours", "color"),
           ("Body", "Misc"), ("weight_g",)),
    Aspect("software", ("android", "one ui", "os", "software", "update", "updates"), ("Platform",)),
    Aspect("connectivity", ("wifi", "wi-fi", "bluetooth", "nfc", "usb", "5g", "network", "sim", "esim", "gps"),
           ("Comms", "Network", "Body")),
    Aspect("audio", ("speaker", "speakers", "sound", "audio", "headphone", "jack", "loudspeaker"), ("Sound",)),
    Aspect("launch", ("release", "released", "announced", "launch", "launched", "when", "year", "new", "newest",
                      "latest", "oldest"),
           ("Launch",), ("release_year",)),
]}

ASC_WORDS = {"cheapest", "lowest", "smallest", "lightest", "least", "minimum", "cheaper", "lighter", "smaller",
             "oldest", "affordable", "budget", "compact"}
DESC_WORDS = {"best", "highest", "most", "largest", "biggest", "longest", "fastest", "top", "greatest", "maximum",
              "better", "bigger", "larger", "faster", "strongest", "brightest", "sharpest", "heaviest", "newest",
              "latest", "expensive", "powerful", "max"}
COMPARE_WORDS = {"compare", "comparison", "vs", "versus", "difference", "differences", "better", "between", "against"}
FOLLOW_UP_WORDS = {"it", "its", "it's", "they", "them", "their", "theirs", "these", "those", "both"}
FOLLOW_UP_OPENERS = ("and ", "what about", "how about", "also ")
LIST_PATTERNS = re.compile(r"\b(which|what) (phones|models|devices)\b.*\b(have|support|database|available|cover)\b|"
                           r"\blist (all|the)?\s*(phones|models)\b|\ball (phones|models)\b", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$+\-']+", text.lower())


def detect_aspects(text: str) -> list[Aspect]:
    lowered = text.lower()
    words = set(_words(text))
    found: list[Aspect] = []
    for aspect in ASPECTS.values():
        for kw in aspect.keywords:
            if (" " in kw and kw in lowered) or kw in words:
                found.append(aspect)
                break
    # "battery charging" -> keep battery; "fast charging" alone -> charging, not performance
    names = {a.name for a in found}
    if "charging" in names and "performance" in names and not ({"processor", "chipset", "cpu", "benchmark",
                                                                "performance", "gaming"} & words):
        found = [a for a in found if a.name != "performance"]
    return found


def detect_ranking(text: str) -> bool | None:
    """Return True for ascending ranking, False for descending, None if no superlative."""
    words = set(_words(text))
    if "most expensive" in text.lower():
        return False
    if words & ASC_WORDS:
        return True
    if words & DESC_WORDS:
        return False
    return None


def is_comparison(text: str) -> bool:
    return bool(set(_words(text)) & COMPARE_WORDS)


def is_follow_up(text: str) -> bool:
    lowered = text.lower().strip()
    return bool(set(_words(text)) & FOLLOW_UP_WORDS) or lowered.startswith(FOLLOW_UP_OPENERS)


def is_catalog_question(text: str) -> bool:
    return bool(LIST_PATTERNS.search(text))


def ranking_metric(aspect: Aspect, text: str) -> str | None:
    """Pick the most appropriate column to rank by for this aspect and wording."""
    w = set(_words(text))
    if aspect.name == "battery" and w & {"capacity", "mah", "biggest", "largest", "bigger", "larger"}:
        return "battery_mah"
    if aspect.name == "display":
        if w & {"sharpest", "resolution", "ppi", "density", "sharp"}:
            return "ppi"
        if w & {"refresh", "smoothest", "smooth", "hz"}:
            return "refresh_rate_hz"
        if w & {"brightest", "brightness", "bright", "nits"}:
            return "peak_brightness_nits"
    if aspect.name == "camera":
        if w & {"zoom", "telephoto"}:
            return "optical_zoom_x"
        if "selfie" in w or "front" in w:
            return "selfie_camera_mp"
    if aspect.name == "memory" and w & {"storage", "tb"}:
        return "max_storage_gb"
    if aspect.name == "charging" and "wireless" in w:
        return "charging_wireless_w"
    return aspect.metrics[0] if aspect.metrics else None
