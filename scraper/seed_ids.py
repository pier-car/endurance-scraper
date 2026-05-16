"""FASE 1 — Coda di Lavoro.

Scansiona gli indici delle classifiche d'élite (vedi
``scraper.endpoints.ELITE_SEED_INDICES``), estrae tutti i tag ``<a>`` che
puntano a ``db_horse_new.php`` ed inserisce gli identificativi univoci
(``FISE_Cavallo`` o ``FEI_Cavallo``) nella tabella SQLite ``coda_cavalli``
con stato iniziale ``PENDING``.

Esecuzione::

    python -m scraper.seed_ids [--db endurance_data.db]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .common import ScraperClient
from .db import DEFAULT_DB_PATH, connect, enqueue_horse, init_db, transaction
from .endpoints import elite_seed_urls

log = logging.getLogger("endurance.seed")


def extract_horse_ids(html: str) -> list[tuple[str, str]]:
    """Estrae (horse_id, id_type) da ogni link a ``db_horse_new.php`` nell'HTML.

    ``id_type`` è ``'FISE'`` o ``'FEI'`` a seconda del parametro effettivamente
    presente. Mantiene l'ordine e deduplica preservando la prima occorrenza.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []

    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "db_horse_new.php" not in href:
            continue
        try:
            qs = parse_qs(urlparse(href).query)
        except ValueError:
            continue

        for key, id_type in (("FISE_Cavallo", "FISE"), ("FEI_Cavallo", "FEI")):
            values = qs.get(key)
            if not values:
                continue
            horse_id = values[0].strip()
            if not horse_id:
                continue
            entry = (horse_id, id_type)
            if entry in seen:
                continue
            seen.add(entry)
            ordered.append(entry)

    return ordered


def seed(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """Esegue la FASE 1. Ritorna statistiche per logging."""
    init_db(db_path)
    client = ScraperClient()
    stats = {"urls": 0, "ids_found": 0, "ids_new": 0, "ids_skipped": 0}

    conn = connect(db_path)
    try:
        for url in elite_seed_urls():
            stats["urls"] += 1
            log.info("Seeding from %s", url)
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                log.error("Fetch failed for %s: %s", url, exc)
                continue

            ids = extract_horse_ids(resp.text)
            stats["ids_found"] += len(ids)
            log.info("Found %d horse links", len(ids))

            # Una transazione per URL: o l'intero batch entra in coda, o niente.
            with transaction(conn):
                for horse_id, id_type in ids:
                    if enqueue_horse(conn, horse_id, id_type, source=url):
                        stats["ids_new"] += 1
                    else:
                        stats["ids_skipped"] += 1
    finally:
        conn.close()

    log.info(
        "Seed done — urls=%d found=%d new=%d already=%d",
        stats["urls"], stats["ids_found"], stats["ids_new"], stats["ids_skipped"],
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 — seed horse IDs")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    seed(args.db)


if __name__ == "__main__":
    main()
