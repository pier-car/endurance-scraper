"""FASE 3 — Tratti Atletici.

Per ogni cavallo presente in ``cavalli``, interroga
``db_horse_new.php?{FISE,FEI}_Cavallo={ID}&results=1`` e popola la tabella
``performance_gare``:

* Data, Gara, Distanza, Velocità Media
* Posizione/Stato grezzo + classificazione normalizzata in
  ``FINISHER``, ``GAIT`` (zoppia), ``METABOLIC``, ``RETIRED``,
  ``OTHER_ELIM``, ``UNKNOWN``.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .common import ScraperClient
from .db import DEFAULT_DB_PATH, connect, init_db, transaction
from .endpoints import HORSE_RESULTS_TEMPLATE_FEI, HORSE_RESULTS_TEMPLATE_FISE

log = logging.getLogger("endurance.performance")

# Pattern di classificazione dello stato. Ordine = priorità (match more specific first).
_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GAIT",       re.compile(r"\b(gait|lame(ness)?|zoppia|claudic)", re.I)),
    ("METABOLIC",  re.compile(r"\b(metab(olic)?|met\b|gme\b)", re.I)),
    ("RETIRED",    re.compile(r"\b(retired|ritirat[oi]|withdrawn|rt\b|wd\b)", re.I)),
    ("FINISHER",   re.compile(r"\b(finisher|completed|qualificat[oi]|fin\b|cp\b)", re.I)),
    ("OTHER_ELIM", re.compile(r"\b(elim(inated)?|eliminat[oi]|disq|squalificat[oi]|fts\b|ovt\b)", re.I)),
)


def classify_status(text: str | None) -> str:
    if not text:
        return "UNKNOWN"
    for label, pattern in _STATUS_PATTERNS:
        if pattern.search(text):
            return label
    # Se è un numero puro = posizione → finisher.
    if re.fullmatch(r"\s*\d+\s*", text):
        return "FINISHER"
    return "UNKNOWN"


_HEADER_MAP = {
    "data": "data_gara",
    "date": "data_gara",
    "gara": "gara",
    "evento": "gara",
    "event": "gara",
    "race": "gara",
    "competition": "gara",
    "distanza": "distanza_km",
    "km": "distanza_km",
    "distance": "distanza_km",
    "velocita": "velocita_kmh",
    "velocità": "velocita_kmh",
    "speed": "velocita_kmh",
    "media": "velocita_kmh",
    "posizione": "posizione",
    "pos": "posizione",
    "position": "posizione",
    "stato": "stato_raw",
    "status": "stato_raw",
    "risultato": "stato_raw",
    "result": "stato_raw",
}


def _normalize_header(text: str) -> str:
    return re.sub(r"[^a-zà-ÿ]+", "", text.lower())


def _map_headers(headers: list[str]) -> dict[int, str]:
    """Mappa indice colonna → nome campo logico, basato sui pattern noti."""
    mapping: dict[int, str] = {}
    for idx, raw in enumerate(headers):
        key = _normalize_header(raw)
        for token, field in _HEADER_MAP.items():
            if token in key:
                # Non sovrascrivere: la prima occorrenza vince.
                mapping.setdefault(idx, field)
                break
    return mapping


def _to_float(text: str | None) -> float | None:
    if not text:
        return None
    # Estrai il primo numero (anche con virgola decimale).
    m = re.search(r"(-?\d+[.,]?\d*)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_results(html: str) -> list[dict]:
    """Estrae le righe della tabella risultati. Robusto a tabelle multiple."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []

    for table in soup.find_all("table"):
        header_cells = table.find("tr")
        if header_cells is None:
            continue
        headers = [c.get_text(" ", strip=True) for c in header_cells.find_all(["th", "td"])]
        if not headers:
            continue
        mapping = _map_headers(headers)
        # Considera "tabella risultati" solo se mappa almeno data o gara.
        if not any(v in mapping.values() for v in ("data_gara", "gara")):
            continue

        for tr in header_cells.find_next_siblings("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            row: dict[str, str | None] = {
                "data_gara": None, "gara": None, "distanza_km": None,
                "velocita_kmh": None, "posizione": None, "stato_raw": None,
            }
            for idx, cell in enumerate(cells):
                field = mapping.get(idx)
                if field is None:
                    continue
                value = cell.get_text(" ", strip=True)
                if not value:
                    continue
                if field in ("distanza_km", "velocita_kmh"):
                    row[field] = _to_float(value)
                else:
                    row[field] = value
            # Salta righe vuote.
            if not row["data_gara"] and not row["gara"]:
                continue
            row["stato_norm"] = classify_status(row["stato_raw"] or row["posizione"])
            rows.append(row)

    return rows


def results_url(horse_id: str, id_type: str) -> str:
    if id_type == "FEI":
        return HORSE_RESULTS_TEMPLATE_FEI.format(id=horse_id)
    return HORSE_RESULTS_TEMPLATE_FISE.format(id=horse_id)


def process_one(client: ScraperClient, conn, horse_id: str, id_type: str) -> int:
    """Estrae le performance per un cavallo. Ritorna il numero di righe salvate."""
    url = results_url(horse_id, id_type)
    log.info("Performance: %s (%s)", horse_id, id_type)
    resp = client.get(url)
    resp.raise_for_status()
    rows = parse_results(resp.text)

    with transaction(conn):
        for row in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO performance_gare (
                    horse_id, id_type, data_gara, gara, distanza_km,
                    velocita_kmh, posizione, stato_raw, stato_norm,
                    source_url, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    horse_id, id_type,
                    row["data_gara"], row["gara"], row["distanza_km"],
                    row["velocita_kmh"], row["posizione"], row["stato_raw"],
                    row["stato_norm"], url,
                ),
            )
    return len(rows)


def run(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """Itera su tutti i cavalli anagrafati e ne estrae i risultati storici."""
    init_db(db_path)
    client = ScraperClient()
    stats = {"horses": 0, "rows": 0, "failed": 0}

    conn = connect(db_path)
    try:
        horses = conn.execute(
            "SELECT horse_id, id_type FROM cavalli ORDER BY fetched_at"
        ).fetchall()
        for row in horses:
            stats["horses"] += 1
            try:
                stats["rows"] += process_one(client, conn, row["horse_id"], row["id_type"])
            except Exception as exc:
                log.error("Performance failed for %s/%s: %s",
                          row["id_type"], row["horse_id"], exc)
                stats["failed"] += 1
    finally:
        conn.close()

    log.info(
        "Performance done — horses=%d rows=%d failed=%d",
        stats["horses"], stats["rows"], stats["failed"],
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 — extract race performance")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run(args.db)


if __name__ == "__main__":
    main()
