"""HTTP client e utility comuni per la pipeline.

Caratteristiche:
    * Rotazione di User-Agent realistici via ``fake-useragent`` (con fallback
      su una lista statica nel caso il servizio remoto non sia raggiungibile).
    * Delay casuale fra le richieste (1.5 - 3.5 s) per ridurre il rischio di
      ban da parte del server PHP legacy di Endurance Online.
    * Exponential backoff con jitter sugli errori 429/503/5xx e sulle
      eccezioni di rete.
    * ``requests.Session`` riusabile con header coerenti.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Iterable

import requests

try:
    from fake_useragent import FakeUserAgent  # type: ignore

    _UA_POOL = FakeUserAgent(browsers=["Chrome", "Firefox", "Edge", "Safari"])
except Exception:  # pragma: no cover - offline fallback
    _UA_POOL = None

# Fallback statico (browser desktop recenti, marzo/aprile 2025) usato se
# ``fake-useragent`` non è disponibile o non riesce a scaricare la lista.
_FALLBACK_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
)

# Codici HTTP che indicano rate-limit o problemi temporanei del server.
RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

DEFAULT_DELAY_RANGE: tuple[float, float] = (1.5, 3.5)
DEFAULT_MAX_RETRIES: int = 5
DEFAULT_BASE_BACKOFF: float = 2.0  # seconds
DEFAULT_MAX_BACKOFF: float = 60.0  # seconds
DEFAULT_TIMEOUT: float = 30.0  # seconds

log = logging.getLogger("endurance.scraper")


def random_user_agent() -> str:
    """Ritorna uno User-Agent random fra quelli disponibili."""
    if _UA_POOL is not None:
        try:
            return _UA_POOL.random
        except Exception:
            pass
    return random.choice(_FALLBACK_USER_AGENTS)


def polite_sleep(delay_range: tuple[float, float] = DEFAULT_DELAY_RANGE) -> None:
    """Dorme un tempo random nell'intervallo indicato (default 1.5-3.5s)."""
    low, high = delay_range
    time.sleep(random.uniform(low, high))


class ScraperClient:
    """Client HTTP resiliente per il dominio enduranceonline.it."""

    def __init__(
        self,
        delay_range: tuple[float, float] = DEFAULT_DELAY_RANGE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_backoff: float = DEFAULT_BASE_BACKOFF,
        max_backoff: float = DEFAULT_MAX_BACKOFF,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.session = requests.Session()
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": random_user_agent(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        """Exponential backoff con jitter; rispetta ``Retry-After`` se presente."""
        if retry_after is not None and retry_after > 0:
            base = retry_after
        else:
            base = self.base_backoff * (2 ** attempt)
        base = min(base, self.max_backoff)
        # Full jitter: random fra base/2 e base*1.5 per evitare thundering herd.
        return random.uniform(base / 2.0, base * 1.5)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get(self, url: str, *, polite: bool = True) -> requests.Response:
        """GET con retry/backoff. Solleva l'ultima eccezione se fallisce."""
        if polite:
            polite_sleep(self.delay_range)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(
                    url,
                    headers=self._headers(),
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                last_exc = exc
                wait = self._backoff_delay(attempt, None)
                log.warning(
                    "Network error on %s (attempt %d/%d): %s — sleep %.1fs",
                    url, attempt + 1, self.max_retries, exc, wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code in RETRY_STATUS_CODES:
                retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                wait = self._backoff_delay(attempt, retry_after)
                log.warning(
                    "HTTP %d on %s (attempt %d/%d) — sleep %.1fs",
                    resp.status_code, url, attempt + 1, self.max_retries, wait,
                )
                time.sleep(wait)
                continue

            # Forza UTF-8: il server dichiara talvolta Latin-1 anche su HTML UTF-8.
            if resp.encoding is None or resp.encoding.lower() in {"iso-8859-1", "latin-1"}:
                resp.encoding = "utf-8"
            return resp

        # Esaurito il numero di tentativi.
        if last_exc is not None:
            raise last_exc
        raise requests.HTTPError(f"Too many retries on {url}")


def chunked(iterable: Iterable, size: int) -> Iterable[list]:
    """Spezza un iterabile in chunk di lunghezza ``size``."""
    buf: list = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf
