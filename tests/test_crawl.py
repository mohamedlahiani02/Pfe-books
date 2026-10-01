from pathlib import Path

from prospection.config import load_config
from prospection.crawl import crawl_listing, parse_detail

CONFIG = Path(__file__).parent.parent / "config" / "config.yaml"

PAGES = {
    "https://pfebooks.com/catalogue/": (
        '<div class="post-item"><h3 class="title"><a href="/c/a/">A</a></h3>'
        '<a class="post-see-btn" href="/c/a/">Voir</a></div>'
        '<a class="next page-numbers" href="/catalogue/page/2/">Suivant</a>'
    ),
    "https://pfebooks.com/catalogue/page/2/": (
        '<div class="post-item"><h3 class="title"><a href="/c/b/">B</a></h3>'
        '<a class="post-see-btn" href="/c/b/">Voir</a></div>'
    ),
}


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeClient:
    def get(self, url: str) -> FakeResponse:
        return FakeResponse(PAGES[url])


def test_crawl_listing_follows_pagination(tmp_path):
    cfg = load_config(CONFIG)
    companies = crawl_listing(FakeClient(), cfg, tmp_path)
    assert [c.nom for c in companies] == ["A", "B"]
    assert len(list(tmp_path.glob("page_*.html"))) == 2


def test_parse_detail_with_empty_selectors_returns_blanks():
    cfg = load_config(CONFIG)["crawl"]["detail"]
    assert parse_detail("<html></html>", cfg, "https://x/")["site_web"] == ""
