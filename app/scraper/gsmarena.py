"""Polite HTTP fetcher for GSMArena with on-disk caching and 429 back-off."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from app.config import settings
from app.scraper.parser import parse_phone_page
from app.scraper.targets import page_url

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


MAX_BACKOFF_SECONDS = 120


class BlockedError(RuntimeError):
    """GSMArena returned a bot-check page instead of content."""


class RateLimitedError(RuntimeError):
    """GSMArena asked us to wait longer than we are willing to sleep."""


class GSMArenaScraper:
    def __init__(self, delay: float | None = None, cache_dir: Path | None = None, use_cache: bool = True):
        self.delay = settings.scrape_delay_seconds if delay is None else delay
        self.cache_dir = cache_dir or settings.scrape_cache_dir
        self.use_cache = use_cache
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def fetch(self, slug: str, retries: int = 4) -> str:
        cache_file = self.cache_dir / f"{slug}.html"
        if self.use_cache and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        url = page_url(slug)
        for attempt in range(1, retries + 1):
            self._throttle()
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "0") or 0)
                if retry_after > MAX_BACKOFF_SECONDS:
                    raise RateLimitedError(
                        f"GSMArena rate limit: Retry-After {retry_after}s (~{retry_after / 3600:.1f}h). "
                        "Re-run later – already downloaded pages are cached."
                    )
                backoff = max(retry_after, 15 * attempt)
                log.warning("429 from GSMArena for %s; backing off %ss", slug, backoff)
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            html = resp.text
            if "Turnstile check" in html or "specs-phone-name-title" not in html:
                raise BlockedError(f"Bot-check page returned for {url}")
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(html, encoding="utf-8")
            return html
        raise RuntimeError(f"Giving up on {url} after {retries} attempts")

    def scrape(self, slug: str) -> dict:
        return parse_phone_page(self.fetch(slug), slug, page_url(slug))
