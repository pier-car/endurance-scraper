"""Schema SQLite e helper di accesso per la pipeline.

Tabelle:
    * ``coda_cavalli``    — coda di lavoro degli ID cavallo da elaborare.
    * ``cavalli``         — anagrafica estratta (FASE 2).
    * ``performance_gare`` — risultati storici per cavallo (FASE 3).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path("endurance_data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS coda_cavalli (
    horse_id    TEXT NOT NULL,
    id_type     TEXT NOT NULL CHECK (id_type IN ('FISE', 'FEI')),
    status      TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED')),
    source      TEXT,
    error       TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (horse_id, id_type)
);

CREATE INDEX IF NOT EXISTS idx_coda_status ON coda_cavalli(status);

CREATE TABLE IF NOT EXISTS cavalli (
    horse_id      TEXT NOT NULL,
    id_type       TEXT NOT NULL CHECK (id_type IN ('FISE', 'FEI')),
    nome          TEXT,
    data_nascita  TEXT,
    razza         TEXT,
    sesso         TEXT,
    sire_id       TEXT,
    sire_id_type  TEXT,
    sire_name     TEXT,
    dam_id        TEXT,
    dam_id_type   TEXT,
    dam_name      TEXT,
    source_url    TEXT,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (horse_id, id_type)
);

CREATE TABLE IF NOT EXISTS performance_gare (
    horse_id      TEXT NOT NULL,
    id_type       TEXT NOT NULL CHECK (id_type IN ('FISE', 'FEI')),
    data_gara     TEXT,
    gara          TEXT,
    distanza_km   REAL,
    velocita_kmh  REAL,
    posizione     TEXT,
    stato_raw     TEXT,
    stato_norm    TEXT,    -- FINISHER / GAIT / METABOLIC / RETIRED / OTHER_ELIM / UNKNOWN
    source_url    TEXT,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (horse_id, id_type, data_gara, gara)
);

CREATE INDEX IF NOT EXISTS idx_perf_horse ON performance_gare(horse_id, id_type);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Apre una connessione SQLite con foreign keys e row factory dict-like."""
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Crea le tabelle se non esistono."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager per transazioni esplicite (isolation_level=None)."""
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --------------------------------------------------------------------------- #
# Coda helpers
# --------------------------------------------------------------------------- #
def enqueue_horse(
    conn: sqlite3.Connection,
    horse_id: str,
    id_type: str,
    source: str | None = None,
) -> bool:
    """Inserisce un horse_id in coda se non esiste già. Ritorna True se nuovo."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO coda_cavalli (horse_id, id_type, status, source)
        VALUES (?, ?, 'PENDING', ?)
        """,
        (horse_id, id_type, source),
    )
    return cur.rowcount > 0


def fetch_pending(
    conn: sqlite3.Connection,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Ritorna le righe in stato PENDING (opzionalmente limitate)."""
    sql = "SELECT horse_id, id_type FROM coda_cavalli WHERE status = 'PENDING'"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def mark_status(
    conn: sqlite3.Connection,
    horse_id: str,
    id_type: str,
    status: str,
    error: str | None = None,
) -> None:
    """Aggiorna lo stato in coda. Da chiamare DENTRO una transazione."""
    conn.execute(
        """
        UPDATE coda_cavalli
           SET status = ?,
               error = ?,
               attempts = attempts + 1,
               updated_at = datetime('now')
         WHERE horse_id = ? AND id_type = ?
        """,
        (status, error, horse_id, id_type),
    )
