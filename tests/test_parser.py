from pathlib import Path

import pytest

from prospection.config import load_config
from prospection.parser import ParserError, check_count, parse_catalogue

FIXTURE = Path(__file__).parent / "fixtures" / "catalogue_sample.html"
CONFIG = Path(__file__).parent.parent / "config" / "config.yaml"
BASE = "https://pfebooks.com/catalogue/"


@pytest.fixture
def parser_cfg() -> dict:
    return load_config(CONFIG)["parser"]


@pytest.fixture
def synthetic_cfg() -> dict:
    return {
        "card": "div.company-card", "name": ".company-name", "sector": ".company-sector",
        "description": ".company-description", "city": ".company-city",
        "website": {"selector": "a.company-website", "attribute": "href"},
        "detail_url": {"selector": "a.company-link", "attribute": "href"},
        "extra_fields": {},
    }


def test_parses_fields_and_normalizes_whitespace(synthetic_cfg):
    companies = parse_catalogue(FIXTURE.read_text(encoding="utf-8"), synthetic_cfg, BASE)
    first = companies[0]
    assert first.nom == "Acme SA"
    assert first.secteur == "Informatique"
    assert first.ville == "Tunis"
    assert first.site_web == "https://acme.example"
    assert first.source_url == "https://pfebooks.com/entreprise/acme/"


def test_skips_nameless_and_duplicate_cards(synthetic_cfg):
    companies = parse_catalogue(FIXTURE.read_text(encoding="utf-8"), synthetic_cfg, BASE)
    assert [c.nom for c in companies] == ["Acme SA", "Beta Conseil"]


def test_missing_optional_fields_are_empty(synthetic_cfg):
    beta = parse_catalogue(FIXTURE.read_text(encoding="utf-8"), synthetic_cfg, BASE)[1]
    assert beta.site_web == "" and beta.ville == "" and beta.source_url == BASE


def test_raises_when_selector_matches_nothing(parser_cfg):
    with pytest.raises(ParserError):
        parse_catalogue("<html><body></body></html>", parser_cfg, BASE)


def test_check_count_flags_deviation():
    assert check_count(380, 380, 0.05) is None
    assert check_count(300, 380, 0.05) is not None


def test_real_catalogue_cards(parser_cfg):
    html = (Path(__file__).parent / "fixtures" / "pfebooks_real_cards.html").read_text(encoding="utf-8")
    companies = parse_catalogue(html, parser_cfg, BASE)
    assert len(companies) == 3
    assert companies[0].nom == "YT SuccessLab"
    assert companies[0].source_url == "https://pfebooks.com/catalogue/2026/yt-successlab/"
