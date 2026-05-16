# endurance-scraper

Pipeline di scraping del sito **[enduranceonline.it](https://www.enduranceonline.it/)** —
un sistema PHP legacy senza API REST/JSON pubbliche. I dati vengono estratti
dall'HTML degli endpoint reali, normalizzati e salvati in un database
**SQLite** (`endurance_data.db`).

> **Refactoring:** la precedente versione "a testo libero" basata su notebook
> (`endurance_scraper.ipynb`) generava errori di omonimia, crash e blocchi del
> server. La nuova architettura è basata su **ID univoci deterministici**
> (`FISE_Cavallo` / `FEI_Cavallo`) e su una pipeline modulare a 3 fasi
> idempotente.

## 🏗️ Architettura

```
┌────────────────────┐   ┌────────────────────────┐   ┌──────────────────────┐
│ FASE 1             │   │ FASE 2                 │   │ FASE 3               │
│ scraper.seed_ids   │ → │ scraper.extract_       │ → │ scraper.extract_     │
│ Classifiche élite  │   │ pedigree (ricorsivo)   │   │ performance          │
│ → coda_cavalli     │   │ → cavalli + nuovi      │   │ → performance_gare   │
│                    │   │   PENDING (genitori)   │   │                      │
└────────────────────┘   └────────────────────────┘   └──────────────────────┘
            │                       │                            │
            └───────────────────────┴────────────────────────────┘
                              SQLite (endurance_data.db)
```

### FASE 1 — `scraper/seed_ids.py` (Coda di Lavoro)

Scansiona gli **indici delle classifiche d'élite** mappati in
`scraper/endpoints.py` (`ELITE_SEED_INDICES = (14, 21, 34, 38, 39)`):

| # | URL |
|---|---|
| 14 | `db_champions.php?v_filtro=Open Horse World Ranking` |
| 21 | `db_champions.php?v_filtro=World Championships` |
| 34 | `db_horses_km.php?v_f=160` |
| 38 | `db_horses_top.php` |
| 39 | `db_horses_win.php` |

Estrae tutti i tag `<a>` che contengono `db_horse_new.php`, recupera con
`urllib.parse` il valore del parametro univoco (`FISE_Cavallo` o
`FEI_Cavallo`) e lo inserisce nella tabella `coda_cavalli` con stato
`PENDING`.

### FASE 2 — `scraper/extract_pedigree.py` (Anagrafica & Ricorsione)

Per ogni ID `PENDING` esegue una `GET` a
`https://www.enduranceonline.it/db/db_horse_new.php?FISE_Cavallo={ID}&info=1`
(o la variante `FEI_Cavallo` quando l'ID è FEI). Estrae **Nome, Data di
Nascita, Razza, Sesso** e i **link/ID di Padre e Madre**. Se i genitori
hanno un ID valido vengono a loro volta inseriti in `coda_cavalli` come
`PENDING`, abilitando la **scoperta genealogica ricorsiva**. Tutto avviene
in un'unica transazione SQLite (`INSERT` anagrafica + `enqueue` genitori +
`UPDATE` stato), garantendo idempotenza e niente coda corrotta.

### FASE 3 — `scraper/extract_performance.py` (Tratti Atletici)

Interroga
`https://www.enduranceonline.it/db/db_horse_new.php?FISE_Cavallo={ID}&results=1`
e popola `performance_gare` con: **Data, Gara, Distanza (km), Velocità
media (km/h), Posizione, Stato grezzo** e una **classificazione
normalizzata** dello stato:

| `stato_norm` | Significato |
|---|---|
| `FINISHER` | Cavallo completato/qualificato |
| `GAIT` | Eliminazione per zoppia (Lameness / Gait) |
| `METABOLIC` | Eliminazione metabolica |
| `RETIRED` | Ritiro volontario |
| `OTHER_ELIM` | Altra eliminazione (squalifica, FTQ, OVT, …) |
| `UNKNOWN` | Stato non interpretabile |

## 🛡️ Resilienza e misure anti-bot

Implementate in `scraper/common.py`:

- **Rotazione User-Agent realistici** via `fake-useragent` (con fallback su
  pool statico se il servizio è offline).
- **Delay polite casuale** fra le richieste, configurabile (default
  `1.5–3.5 s`).
- **Exponential backoff con jitter** su errori `429`, `5xx` e su tutte le
  eccezioni di rete; rispetta l'header `Retry-After` quando presente.
- **`requests.Session`** persistente e timeout di 30 s.
- Forzatura `encoding = utf-8` quando il server dichiara `Latin-1`.

## 🗄️ Schema SQLite (`endurance_data.db`)

Definito in `scraper/db.py` e creato automaticamente da ogni fase:

- `coda_cavalli (horse_id, id_type, status, source, error, attempts, …)`
  con `PRIMARY KEY (horse_id, id_type)` e check `status IN
  ('PENDING','IN_PROGRESS','COMPLETED','FAILED')`.
- `cavalli (horse_id, id_type, nome, data_nascita, razza, sesso,
  sire_id/type/name, dam_id/type/name, source_url, fetched_at)`.
- `performance_gare (horse_id, id_type, data_gara, gara, distanza_km,
  velocita_kmh, posizione, stato_raw, stato_norm, source_url,
  fetched_at)` con PK `(horse_id, id_type, data_gara, gara)`.

Modalità WAL + `synchronous=NORMAL` per buone performance senza rinunciare
alla durabilità.

## 🚀 Esecuzione locale

```bash
pip install -r requirements.txt

# Pipeline completa
python -m scraper.seed_ids            # FASE 1
python -m scraper.extract_pedigree    # FASE 2 (ricorsiva)
python -m scraper.extract_performance # FASE 3
```

Opzioni utili:

```bash
python -m scraper.seed_ids --db /tmp/test.db -v
python -m scraper.extract_pedigree --max-iterations 10 --batch-size 100 -v
```

Il database `endurance_data.db` è il singolo output condiviso.

## 🤖 Automazione CI/CD

`.github/workflows/scraper.yml` esegue la pipeline **una volta alla
settimana** (lunedì 04:17 UTC) o on-demand via `workflow_dispatch`. Al
termine carica `endurance_data.db` come **artefatto scaricabile** dal
pannello Actions (retention 90 giorni). La policy
`concurrency: { group: endurance-scraper, cancel-in-progress: false }`
evita esecuzioni sovrapposte.

## 📁 File del repository

- `scraper/seed_ids.py` — FASE 1
- `scraper/extract_pedigree.py` — FASE 2
- `scraper/extract_performance.py` — FASE 3
- `scraper/common.py` — HTTP client resiliente + utility
- `scraper/db.py` — schema SQLite + helper transazionali
- `scraper/endpoints.py` — mappa completa dei 55 endpoint reali
- `.github/workflows/scraper.yml` — automazione GitHub Actions
- `requirements.txt` — dipendenze Python
- `endurance_scraper.ipynb` — notebook legacy (mantenuto a scopo storico,
  superato dalla pipeline a ID)
