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


def test_polite_client_enforces_interval_per_host_across_threads(monkeypatch):
    import threading
    import time

    from prospection.http import PoliteClient

    client = PoliteClient({"user_agent": "t", "connect_timeout_seconds": 1, "timeout_seconds": 1, "total_timeout_seconds": 5, "max_response_bytes": 1000, "max_retries": 0,
                           "backoff_factor": 0, "min_interval_seconds": 0.2})
    stamps: list[float] = []

    def hit() -> None:
        client._throttle("example.org")
        stamps.append(time.monotonic())

    threads = [threading.Thread(target=hit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stamps.sort()
    assert all(b - a >= 0.18 for a, b in zip(stamps, stamps[1:]))


def test_polite_client_aborts_slow_drip_download():
    import http.server
    import threading
    import time

    import pytest
    import requests

    from prospection.http import PoliteClient

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            for _ in range(1000):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.05)

        def log_message(self, *args) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = PoliteClient({"user_agent": "t", "connect_timeout_seconds": 1, "timeout_seconds": 2,
                           "total_timeout_seconds": 0.5, "max_response_bytes": 1000000,
                           "max_retries": 0, "backoff_factor": 0, "min_interval_seconds": 0})
    started = time.monotonic()
    with pytest.raises(requests.Timeout):
        client._raw_get(f"http://127.0.0.1:{server.server_port}/")
    server.shutdown()
    assert time.monotonic() - started < 3
