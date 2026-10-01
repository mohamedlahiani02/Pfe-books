from bs4 import BeautifulSoup

from prospection.enrich import _find_link, _generic_email

ALLOWED = {"contact", "rh"}


def test_generic_email_only_returns_whitelisted_local_parts():
    soup = BeautifulSoup('<a href="mailto:jean.dupont@x.com">x</a> contact@x.com', "lxml")
    assert _generic_email(soup, ALLOWED) == "contact@x.com"


def test_no_email_is_never_invented():
    assert _generic_email(BeautifulSoup("<p>nothing</p>", "lxml"), ALLOWED) == ""


def test_find_link_stays_on_same_site():
    html = '<a href="https://other.com/careers">c</a><a href="/carrieres">Carrieres</a>'
    link = _find_link(BeautifulSoup(html, "lxml"), "https://acme.example/", ["carrieres", "careers"])
    assert link == "https://acme.example/carrieres"
