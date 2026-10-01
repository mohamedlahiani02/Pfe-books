"""Catalogue HTML parser driven by configurable CSS selectors."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import Company

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """Raised when the catalogue structure does not match the configuration."""


def _text(node: Tag, selector: str) -> str:
    if not selector:
        return ""
    found = node.select_one(selector)
    return " ".join(found.get_text(" ", strip=True).split()) if found else ""


def _attr(node: Tag, spec: dict[str, str] | None, base_url: str) -> str:
    if not spec or not spec.get("selector"):
        return ""
    found = node.select_one(spec["selector"])
    if found is None:
        return ""
    value = (found.get(spec.get("attribute", "href")) or "").strip()
    return urljoin(base_url, value) if value else ""


def parse_catalogue(html: str, parser_cfg: dict[str, Any], base_url: str) -> list[Company]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(parser_cfg["card"])
    if not cards:
        raise ParserError(f"No element matches card selector {parser_cfg['card']!r}")

    companies: list[Company] = []
    seen: set[tuple[str, str]] = set()
    for index, card in enumerate(cards):
        name = _text(card, parser_cfg["name"])
        if not name:
            logger.warning("Card %d skipped: empty name", index)
            continue
        website = _attr(card, parser_cfg.get("website"), base_url)
        key = (name.casefold(), website)
        if key in seen:
            logger.info("Duplicate card ignored: %s", name)
            continue
        seen.add(key)
        companies.append(
            Company(
                nom=name,
                secteur=_text(card, parser_cfg["sector"]),
                description=_text(card, parser_cfg["description"]),
                site_web=website,
                ville=_text(card, parser_cfg["city"]),
                source_url=_attr(card, parser_cfg.get("detail_url"), base_url) or base_url,
                extra={k: _text(card, sel) for k, sel in parser_cfg.get("extra_fields", {}).items()},
            )
        )
    logger.info("Parsed %d companies from %d cards", len(companies), len(cards))
    return companies


def check_count(actual: int, expected: int, tolerance: float) -> str | None:
    """Return a warning message when the count deviates beyond tolerance."""
    if expected <= 0:
        return None
    deviation = abs(actual - expected) / expected
    if deviation > tolerance:
        return f"Extracted {actual} companies, expected about {expected} (deviation {deviation:.1%})"
    return None
