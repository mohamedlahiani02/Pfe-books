"""Command line entry point: fetch, parse, enrich, export."""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from pathlib import Path

from .config import ConfigError, load_config
from .crawl import crawl_details, crawl_listing
from .enrich import enrich_company
from .http import PoliteClient
from .models import Company, Enrichment
from .output import build_frame, write_outputs, write_report
from .parser import ParserError, check_count, parse_catalogue

logger = logging.getLogger("prospection")


def main(argv: list[str] | None = None) -> int:
    args_parser = argparse.ArgumentParser(description="Forum prospection pipeline")
    args_parser.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    args_parser.add_argument("--crawl", action="store_true",
                             help="Crawl all listing pages and detail pages (robots.txt respected)")
    args_parser.add_argument("--no-enrich", action="store_true", help="Skip website enrichment")
    args_parser.add_argument("--limit", type=int, default=0, help="Process only the first N companies")
    args_parser.add_argument("--verbose", action="store_true")
    args = args_parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    client = PoliteClient(cfg["http"])
    raw_dir = Path(cfg["crawl"]["raw_dir"])
    detail_status: dict[str, str] = {}
    try:
        if args.crawl:
            companies = crawl_listing(client, cfg, raw_dir / "listing")
        else:
            html_path = Path(cfg["catalogue"]["local_html"])
            companies = parse_catalogue(html_path.read_text(encoding="utf-8"),
                                        cfg["parser"], cfg["catalogue"]["url"])
    except (ParserError, OSError) as exc:
        logger.error("Catalogue loading failed: %s", exc)
        return 4
    except Exception as exc:  # noqa: BLE001 - network or robots failure is fatal here
        logger.error("Catalogue crawl failed: %s", exc)
        return 3

    expected = cfg["catalogue"]["expected_count"]
    warning = check_count(len(companies), expected, cfg["catalogue"]["count_tolerance"])
    if warning:
        logger.warning(warning)
    if args.limit:
        companies = companies[: args.limit]

    if args.crawl:
        detail_status = crawl_details(client, companies, cfg, raw_dir / "details")

    out = cfg["output"]
    today = date.today()

    def export(rows: list[tuple[Company, Enrichment]]) -> None:
        frame = build_frame(rows, out["default_status"], today)
        write_outputs(frame, Path(out["csv"]), Path(out["xlsx"]))
        write_report(frame, rows, expected, warning, Path(out["report"]))
        logger.info("Wrote %d rows", len(frame))

    def status_of(company: Company, enrichment: Enrichment) -> Enrichment:
        if detail_status.get(company.source_url, "ok") != "ok":
            enrichment.status = detail_status[company.source_url]
        return enrichment

    # Checkpoint: the catalogue data is exported before the slower website enrichment starts.
    export([(c, status_of(c, Enrichment())) for c in companies])
    if args.no_enrich:
        return 0

    def work(company: Company) -> Enrichment:
        try:
            return status_of(company, enrich_company(company, client, cfg["enrichment"]))
        except Exception as exc:  # noqa: BLE001 - one company must never abort the whole run
            logger.warning("Enrichment crashed for %s: %s", company.nom, exc)
            return Enrichment(status="enrichment_error")

    results: list[Enrichment] = [Enrichment(status="enrichment_timeout") for _ in companies]
    pool = ThreadPoolExecutor(max_workers=cfg["http"]["workers"])
    futures = {pool.submit(work, company): index for index, company in enumerate(companies)}
    try:
        for future in as_completed(futures, timeout=cfg["enrichment"]["deadline_seconds"]):
            results[futures[future]] = future.result()
    except FutureTimeout:
        logger.warning("Enrichment deadline reached; unfinished companies marked enrichment_timeout")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    rows = list(zip(companies, results))
    for position, (company, enrichment) in enumerate(rows, start=1):
        logger.info("%d/%d %s -> %s", position, len(rows), company.nom, enrichment.status)
    export(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
