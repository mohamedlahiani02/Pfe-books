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


def _section_text(soup: BeautifulSoup, heading_prefixes: list[str]) -> str:
    """Text following the first heading whose label starts with one of the prefixes."""
    for heading in soup.select("h1, h2, h3"):
        label = heading.get_text(" ", strip=True).lower().replace("\u2019", "'")
        if any(label.startswith(prefix) for prefix in heading_prefixes):
            parts: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h1", "h2", "h3"):
                    break
                parts.append(sibling.get_text(" ", strip=True))
            return " ".join(" ".join(parts).split())
    return ""


def _external_website(soup: BeautifulSoup, excluded_domains: list[str]) -> str:
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not href.startswith(("http://", "https://")):
            continue
        host = urlparse(href).netloc.lower()
        if any(domain in host for domain in excluded_domains):
            continue
        return href
    return ""


def _generic_mailto(soup: BeautifulSoup, keywords: list[str]) -> str:
    """Return a published mailbox only when its local part is functional, never a personal one."""
    for link in soup.find_all("a", href=True):
        if not link["href"].lower().startswith("mailto:"):
            continue
        address = link["href"][7:].split("?")[0].strip().lower()
        local = address.split("@")[0]
        if "@" in address and any(keyword in local for keyword in keywords):
            return address
    return ""


def _first_city(text: str, cities: list[str]) -> str:
    best: tuple[int, str] | None = None
    for city in cities:
        match = re.search(rf"\b{re.escape(city)}\b", text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), city)
    return best[1] if best else ""


def parse_detail(html: str, detail_cfg: dict[str, Any], base_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    about = _section_text(soup, detail_cfg["company_heading_prefixes"])
    return {
        "description": about[: detail_cfg["max_description_chars"]],
        "ville": _first_city(about, detail_cfg["cities"]),
        "site_web": _external_website(soup, detail_cfg["excluded_domains"]),
        "email_contact_generique": _generic_mailto(soup, detail_cfg["generic_email_keywords"]),
    }


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
