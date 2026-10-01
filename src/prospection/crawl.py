"""Catalogue crawling: listing pagination and company detail pages."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .http import PoliteClient, RobotsDisallowed, RobotsUnreachable
from .models import Company
from .parser import parse_catalogue

logger = logging.getLogger(__name__)


def _slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.lower()).strip("-") or "index"


def crawl_listing(client: PoliteClient, cfg: dict[str, Any], raw_dir: Path) -> list[Company]:
    """Follow pagination links from the catalogue URL and parse every page."""
    crawl_cfg = cfg["crawl"]
    url: str | None = cfg["catalogue"]["url"]
    visited: set[str] = set()
    companies: list[Company] = []
    seen: set[str] = set()
    raw_dir.mkdir(parents=True, exist_ok=True)
    while url and url not in visited and len(visited) < crawl_cfg["max_pages"]:
        visited.add(url)
        html = client.get(url).text
        (raw_dir / f"page_{len(visited):03d}.html").write_text(html, encoding="utf-8")
        for company in parse_catalogue(html, cfg["parser"], url):
            if company.source_url not in seen:
                seen.add(company.source_url)
                companies.append(company)
        nxt = BeautifulSoup(html, "lxml").select_one(crawl_cfg["next_page_selector"])
        url = urljoin(url, nxt["href"]) if nxt and nxt.get("href") else None
    logger.info("Crawled %d listing pages, %d companies", len(visited), len(companies))
    return companies


def _first_text(soup: BeautifulSoup, selector: str) -> str:
    node = soup.select_one(selector) if selector else None
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def parse_detail(html: str, detail_cfg: dict[str, Any], base_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    fields = {
        "secteur": _first_text(soup, detail_cfg["sector"]),
        "ville": _first_text(soup, detail_cfg["city"]),
        "description": _first_text(soup, detail_cfg["description"]),
        "site_web": "",
    }
    website_sel = detail_cfg["website"]["selector"]
    link = soup.select_one(website_sel) if website_sel else None
    if link and link.get(detail_cfg["website"]["attribute"]):
        fields["site_web"] = urljoin(base_url, link[detail_cfg["website"]["attribute"]].strip())
    return fields


def crawl_details(
    client: PoliteClient, companies: list[Company], cfg: dict[str, Any], raw_dir: Path
) -> dict[str, str]:
    """Fetch each detail page once; returns a status per company source URL."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    statuses: dict[str, str] = {}
    for position, company in enumerate(companies, start=1):
        try:
            html = client.get(company.source_url).text
        except RobotsDisallowed:
            statuses[company.source_url] = "detail_robots_disallowed"
            continue
        except RobotsUnreachable:
            statuses[company.source_url] = "detail_robots_unreachable"
            continue
        except requests.RequestException as exc:
            logger.warning("Detail fetch failed for %s: %s", company.nom, exc)
            statuses[company.source_url] = "detail_fetch_error"
            continue
        (raw_dir / f"{_slug(company.source_url)}.html").write_text(html, encoding="utf-8")
        for key, value in parse_detail(html, cfg["crawl"]["detail"], company.source_url).items():
            if value and not getattr(company, key):
                setattr(company, key, value)
        statuses[company.source_url] = "ok"
        logger.info("Detail %d/%d %s", position, len(companies), company.nom)
    return statuses
