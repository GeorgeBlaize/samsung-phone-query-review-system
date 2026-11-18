"""Scrape GSMArena and store the results in the database.

Usage:
    python -m app.scraper.run                 # scrape all targets (uses HTML cache)
    python -m app.scraper.run --no-cache      # force fresh downloads
    python -m app.scraper.run --from-json data/phones.json   # load DB from export, no network
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.config import settings
from app.db.repository import export_json, load_json, save_phone
from app.db.session import get_session, init_db
from app.scraper.gsmarena import GSMArenaScraper, RateLimitedError
from app.scraper.targets import TARGET_PHONES

log = logging.getLogger("scraper")


def scrape_all(slugs: list[str] | None = None, use_cache: bool = True) -> dict:
    init_db()
    scraper = GSMArenaScraper(use_cache=use_cache)
    ok, failed = [], []
    for slug in slugs or TARGET_PHONES:
        try:
            record = scraper.scrape(slug)
            with get_session() as session:
                save_phone(session, record)
            ok.append(record["name"])
            log.info("saved %-28s %3d spec rows, %d benchmarks", record["name"],
                     len(record["specifications"]), len(record["benchmarks"]))
        except RateLimitedError as exc:  # no point hammering the site – stop here
            failed.append({"slug": slug, "error": str(exc)})
            log.error("%s", exc)
            break
        except Exception as exc:  # keep going; report at the end
            failed.append({"slug": slug, "error": str(exc)})
            log.error("failed %s: %s", slug, exc)
    with get_session() as session:
        count = export_json(session, settings.export_json_path)
    log.info("exported %d phones to %s", count, settings.export_json_path)
    return {"scraped": ok, "failed": failed}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-cache", action="store_true", help="ignore cached HTML and re-download")
    parser.add_argument("--from-json", type=Path, help="load phones from a JSON export instead of scraping")
    args = parser.parse_args()

    if args.from_json:
        init_db()
        with get_session() as session:
            n = load_json(session, args.from_json)
        log.info("loaded %d phones from %s", n, args.from_json)
        return

    result = scrape_all(use_cache=not args.no_cache)
    print(f"\nScraped {len(result['scraped'])} phones; {len(result['failed'])} failed.")
    for f in result["failed"]:
        print("  -", f["slug"], f["error"])


if __name__ == "__main__":
    main()
