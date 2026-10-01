"""Public-information enrichment of company websites."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .http import PoliteClient, RobotsDisallowed, RobotsUnreachable
from .models import Company, Enrichment

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _same_site(base: str, url: str) -> bool:
    def norm(host: str) -> str:
        return host.lower().removeprefix("www.")

    return norm(urlparse(base).netloc) == norm(urlparse(url).netloc)


def _find_link(soup: BeautifulSoup, base: str, keywords: list[str]) -> str:
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        haystack = f"{href} {anchor.get_text(' ', strip=True)}".lower()
        if any(k in haystack for k in keywords):
            absolute = urljoin(base, href)
            if _same_site(base, absolute):
                return absolute
    return ""


def _generic_email(soup: BeautifulSoup, allowed_locals: set[str]) -> str:
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        if anchor["href"].lower().startswith("mailto:"):
            candidates.extend(_EMAIL_RE.findall(anchor["href"][7:].split("?")[0]))
    candidates.extend(_EMAIL_RE.findall(soup.get_text(" ")))
    for email in candidates:
        if email.split("@")[0].lower() in allowed_locals:
            return email.lower()
    return ""


def _summary(soup: BeautifulSoup, limit: int) -> str:
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            return " ".join(tag["content"].split())[:limit]
    return ""


def enrich_company(company: Company, client: PoliteClient, cfg: dict[str, Any]) -> Enrichment:
    result = Enrichment()
    if not company.site_web:
        result.status = "no_website"
        return result

    allowed_locals = {p.lower() for p in cfg["generic_email_local_parts"]}
    size_re = re.compile(cfg["size_pattern"], re.IGNORECASE)
    try:
        home = client.get(company.site_web)
    except RobotsDisallowed:
        result.status = "robots_disallowed"
        return result
    except RobotsUnreachable as exc:
        logger.warning("robots.txt unreachable for %s: %s", company.nom, exc)
        result.status = "robots_unreachable"
        return result
    except requests.RequestException as exc:
        logger.warning("Fetch failed for %s: %s", company.nom, exc)
        result.status = "fetch_error"
        return result

    soup = BeautifulSoup(home.text, "lxml")
    base = home.url
    result.activite = _summary(soup, cfg["max_description_chars"])
    result.email_contact_generique = _generic_email(soup, allowed_locals)
    result.page_recrutement = _find_link(soup, base, cfg["careers_keywords"])
    match = size_re.search(soup.get_text(" "))
    if match:
        result.taille = " ".join(match.group(0).split())

    if not result.email_contact_generique:
        contact_url = _find_link(soup, base, cfg["contact_keywords"])
        if contact_url:
            try:
                page = BeautifulSoup(client.get(contact_url).text, "lxml")
                result.email_contact_generique = _generic_email(page, allowed_locals)
            except (RobotsDisallowed, RobotsUnreachable, requests.RequestException) as exc:
                logger.info("Contact page skipped for %s: %s", company.nom, exc)

    result.status = "ok"
    return result
