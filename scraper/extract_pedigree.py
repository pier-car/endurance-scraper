"""FASE 2 — Anagrafica & Ricorsione Genealogica.

Per ogni ID in stato ``PENDING`` nella coda:

1. Esegue una GET a ``db_horse_new.php?{FISE,FEI}_Cavallo={ID}&info=1``.
2. Estrae anagrafica (Nome, Data di Nascita, Razza, Sesso) e i link/ID
   di Padre (sire) e Madre (dam).
3. Inserisce i genitori in ``coda_cavalli`` come ``PENDING`` se non già
   visitati, abilitando la scoperta genealogica ricorsiva.
4. Salva la riga in ``cavalli`` e marca la coda come ``COMPLETED``
   (o ``FAILED`` in caso di errore) all'interno di una singola
   transazione SQLite.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from .common import ScraperClient
from .db import (
    DEFAULT_DB_PATH,
    connect,
    enqueue_horse,
    fetch_pending,
    init_db,
    mark_status,
    transaction,
)
from .endpoints import HORSE_DETAIL_TEMPLATE_FEI, HORSE_DETAIL_TEMPLATE_FISE

log = logging.getLogger("endurance.pedigree")

# Etichette presenti nella pagina di dettaglio (italiano/inglese).
_LABEL_PATTERNS = {
    "nome":         re.compile(r"^\s*(nome|name)\s*[:：]?\s*$", re.I),
    "data_nascita": re.compile(r"^\s*(data\s*(di\s*)?nascita|date\s*of\s*birth|born)\s*[:：]?\s*$", re.I),
    "razza":        re.compile(r"^\s*(razza|breed)\s*[:：]?\s*$", re.I),
    "sesso":        re.compile(r"^\s*(sesso|sex|gender)\s*[:：]?\s*$", re.I),
    "sire":         re.compile(r"^\s*(padre|sire)\s*[:：]?\s*$", re.I),
    "dam":          re.compile(r"^\s*(madre|dam)\s*[:：]?\s*$", re.I),
}


def detail_url(horse_id: str, id_type: str) -> str:
    if id_type == "FEI":
        return HORSE_DETAIL_TEMPLATE_FEI.format(id=horse_id)
    return HORSE_DETAIL_TEMPLATE_FISE.format(id=horse_id)


def _extract_parent_from_link(link: Tag) -> tuple[str | None, str | None, str]:
    """Da un <a href=...db_horse_new.php?...>NAME</a> ritorna (id, id_type, name)."""
    href = link.get("href", "")
    name = link.get_text(strip=True)
    if "db_horse_new.php" not in href:
        return None, None, name
    try:
        qs = parse_qs(urlparse(href).query)
    except ValueError:
        return None, None, name
    for key, id_type in (("FISE_Cavallo", "FISE"), ("FEI_Cavallo", "FEI")):
        values = qs.get(key)
        if values and values[0].strip():
            return values[0].strip(), id_type, name
    return None, None, name


def parse_pedigree(html: str) -> dict:
    """Estrae i campi anagrafici e i riferimenti ai genitori dalla pagina.

    Ritorna un dict con chiavi: ``nome``, ``data_nascita``, ``razza``,
    ``sesso``, ``sire_id``, ``sire_id_type``, ``sire_name``, ``dam_id``,
    ``dam_id_type``, ``dam_name``. I valori non trovati sono ``None``.
    """
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, str | None] = {
        "nome": None, "data_nascita": None, "razza": None, "sesso": None,
        "sire_id": None, "sire_id_type": None, "sire_name": None,
        "dam_id": None, "dam_id_type": None, "dam_name": None,
    }

    # Strategia: scorri tutte le celle di tabella; quando incontri una cella
    # che matcha una label, prendi il valore dalla cella adiacente (next td).
    for cell in soup.find_all(["td", "th"]):
        text = cell.get_text(" ", strip=True)
        if not text:
            continue
        for field, pattern in _LABEL_PATTERNS.items():
            if not pattern.match(text):
                continue
            value_cell = cell.find_next_sibling(["td", "th"])
            if value_cell is None:
                continue

            if field in ("sire", "dam"):
                link = value_cell.find("a", href=True)
                if link is not None:
                    pid, pid_type, pname = _extract_parent_from_link(link)
                    data[f"{field}_id"] = pid
                    data[f"{field}_id_type"] = pid_type
                    data[f"{field}_name"] = pname or value_cell.get_text(" ", strip=True) or None
                else:
                    data[f"{field}_name"] = value_cell.get_text(" ", strip=True) or None
            else:
                value = value_cell.get_text(" ", strip=True)
                if value and data[field] is None:
                    data[field] = value
            break

    # Fallback per il nome: il titolo della pagina spesso lo contiene.
    if data["nome"] is None:
        title = soup.find("title")
        if title:
            data["nome"] = title.get_text(strip=True) or None

    return data


def process_one(
    client: ScraperClient,
    conn,
    horse_id: str,
    id_type: str,
) -> str:
    """Elabora un singolo ID. Ritorna lo stato finale assegnato in coda."""
    url = detail_url(horse_id, id_type)
    log.info("Pedigree: %s (%s)", horse_id, id_type)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        pedigree = parse_pedigree(resp.text)
    except Exception as exc:  # rete o parsing
        log.error("Failed pedigree for %s/%s: %s", id_type, horse_id, exc)
        with transaction(conn):
            mark_status(conn, horse_id, id_type, "FAILED", error=str(exc)[:500])
        return "FAILED"

    # Una sola transazione per: insert anagrafica + enqueue genitori + mark COMPLETED.
    with transaction(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO cavalli (
                horse_id, id_type, nome, data_nascita, razza, sesso,
                sire_id, sire_id_type, sire_name,
                dam_id, dam_id_type, dam_name,
                source_url, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                horse_id, id_type,
                pedigree["nome"], pedigree["data_nascita"], pedigree["razza"], pedigree["sesso"],
                pedigree["sire_id"], pedigree["sire_id_type"], pedigree["sire_name"],
                pedigree["dam_id"], pedigree["dam_id_type"], pedigree["dam_name"],
                url,
            ),
        )

        for parent_id, parent_type in (
            (pedigree["sire_id"], pedigree["sire_id_type"]),
            (pedigree["dam_id"], pedigree["dam_id_type"]),
        ):
            if parent_id and parent_type:
                enqueue_horse(conn, parent_id, parent_type, source=url)

        mark_status(conn, horse_id, id_type, "COMPLETED")

    return "COMPLETED"


def run(
    db_path: str | Path = DEFAULT_DB_PATH,
    max_iterations: int = 50,
    batch_size: int = 200,
) -> dict[str, int]:
    """Elabora la coda finché ci sono PENDING (cap di sicurezza ``max_iterations``).

    La ricorsione genealogica può continuare ad aggiungere nuovi PENDING man mano
    che i genitori vengono scoperti; ad ogni iterazione si rilegge la coda.
    """
    init_db(db_path)
    client = ScraperClient()
    stats = {"completed": 0, "failed": 0, "iterations": 0}

    conn = connect(db_path)
    try:
        for _ in range(max_iterations):
            pending = fetch_pending(conn, limit=batch_size)
            if not pending:
                break
            stats["iterations"] += 1
            for row in pending:
                status = process_one(client, conn, row["horse_id"], row["id_type"])
                if status == "COMPLETED":
                    stats["completed"] += 1
                else:
                    stats["failed"] += 1
    finally:
        conn.close()

    log.info(
        "Pedigree done — iterations=%d completed=%d failed=%d",
        stats["iterations"], stats["completed"], stats["failed"],
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 — extract pedigree (recursive)")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run(args.db, args.max_iterations, args.batch_size)


if __name__ == "__main__":
    main()
