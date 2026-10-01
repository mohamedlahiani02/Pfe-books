"""HTTP client with robots.txt compliance, per-domain rate limiting and bounded retries."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class RobotsDisallowed(Exception):
    """The target URL is disallowed by robots.txt."""


class RobotsUnreachable(Exception):
    """robots.txt could not be retrieved reliably (network error or 5xx)."""


class PoliteClient:
    def __init__(self, http_cfg: dict[str, Any]) -> None:
        self._ua: str = http_cfg["user_agent"]
        self._timeout: float = http_cfg["timeout_seconds"]
        self._interval: float = http_cfg["min_interval_seconds"]
        self._last_request: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()
        self._robots: dict[str, RobotFileParser | None] = {}
        self._local = threading.local()
        self._retry = Retry(
            total=http_cfg["max_retries"],
            backoff_factor=http_cfg["backoff_factor"],
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )

    @property
    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = self._ua
            session.mount("http://", HTTPAdapter(max_retries=self._retry))
            session.mount("https://", HTTPAdapter(max_retries=self._retry))
            self._local.session = session
        return session

    def _throttle(self, host: str) -> None:
        """Serialise requests per host so each domain receives at most one request per interval."""
        with self._registry_lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._interval - (time.monotonic() - self._last_request.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    def _raw_get(self, url: str) -> requests.Response:
        self._throttle(urlparse(url).netloc)
        return self._session.get(url, timeout=self._timeout, allow_redirects=True)

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        """Return a parser, or None when robots.txt is absent (everything allowed)."""
        if origin in self._robots:
            return self._robots[origin]
        parser: RobotFileParser | None
        try:
            response = self._raw_get(f"{origin}/robots.txt")
        except requests.RequestException as exc:
            raise RobotsUnreachable(f"{origin}: {exc}") from exc
        if response.status_code in (401, 403):
            parser = RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /"])
        elif response.status_code >= 500:
            raise RobotsUnreachable(f"{origin}: HTTP {response.status_code}")
        elif response.status_code >= 400:
            parser = None
        else:
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
        self._robots[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        parser = self._load_robots(f"{parsed.scheme}://{parsed.netloc}")
        return True if parser is None else parser.can_fetch(self._ua, url)

    def get(self, url: str) -> requests.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        logger.debug("GET %s", url)
        response = self._raw_get(url)
        response.raise_for_status()
        return response
