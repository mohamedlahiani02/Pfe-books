"""Command line entry point: fetch, parse, enrich, export."""
from __future__ import annotations

import argparse
import logging
import sys
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

    rows: list[tuple[Company, Enrichment]] = []
    for position, company in enumerate(companies, start=1):
        enrichment = Enrichment() if args.no_enrich else enrich_company(company, client, cfg["enrichment"])
        if detail_status.get(company.source_url, "ok") != "ok":
            enrichment.status = detail_status[company.source_url]
        rows.append((company, enrichment))
        logger.info("%d/%d %s -> %s", position, len(companies), company.nom, enrichment.status)

    out = cfg["output"]
    frame = build_frame(rows, out["default_status"], date.today())
    write_outputs(frame, Path(out["csv"]), Path(out["xlsx"]))
    write_report(frame, rows, expected, warning, Path(out["report"]))
    logger.info("Wrote %d rows", len(frame))
    return 0


if __name__ == "__main__":
    sys.exit(main())
