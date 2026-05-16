# endurance-scraper

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/pier-car/endurance-scraper/blob/main/endurance_scraper.ipynb)

Scraper completo del sito **[enduranceonline.it](https://www.enduranceonline.it/)** —
un sistema PHP legacy senza API REST/JSON pubbliche. Tutti i dati vengono estratti
dall'HTML delle pagine, normalizzati e salvati in CSV (UTF-8 con BOM) pronti per
analisi e modelli predittivi.

## 🚀 Avvio rapido su Google Colab

1. Clicca il badge **Open in Colab** qui sopra (oppure usa il link diretto al notebook
   [`endurance_scraper.ipynb`](./endurance_scraper.ipynb)).
2. Nella cella **Configurazione globale** lascia `TEST_MODE = True` per il primo giro
   (poche lettere/anni, ~1 minuto). Imposta `TEST_MODE = False` per il download
   completo (dal 2004 a oggi, può richiedere ore).
3. `Runtime → Run all`.
4. I CSV vengono scritti nella cartella `./data/`. Su Colab puoi scaricarli dal
   pannello **Files** o caricarli su Drive/GitHub.

## 🧰 Esecuzione locale

```bash
pip install -r requirements.txt
jupyter notebook endurance_scraper.ipynb
```

## 📑 Struttura del notebook

Il notebook è organizzato in moduli (sezioni numerate):

| # | Sezione | Cosa fa |
|---|---|---|
| 1 | **Installazione dipendenze** | `pip install` idempotente di `requests`, `beautifulsoup4`, `pandas`, `lxml`, `tqdm`. |
| 2 | **Configurazione globale** | Flag `TEST_MODE`, `BASE_URL`, intervallo anni (`2004 → oggi`), lettere A–Z, header HTTP realistici, `requests.Session()`. |
| 3 | **Helper HTTP** | `fetch()` con retry esponenziale (max 4 tentativi), delay polite di **0.8 s** + jitter, fix encoding UTF-8 anche su risposte Latin-1. |
| 4 | **Discovery** | Esplora ogni endpoint stampando `<form>`, parametri, numero tabelle e link interni. Esegue un *probe* automatico di varianti di parametri (`?ricerca_n=`, `?anno=`, `?year=`, `?page=`, `?pagina=`, `?v_filtro=`) confrontando le size delle risposte per identificare quelli "veri". |
| 5 | **Parser tabelle generico** | `parse_html_tables()` estrae qualsiasi `<table>` come liste di dict, conservando anche gli `href` interni (per il follow-up sui dettagli). |
| 6 | **Anagrafica cavalli** | Itera A–Z su `db_horses.php?ricerca_n=…`. Per ogni cavallo segue il link di dettaglio ed estrae genealogia (sire, dam), microchip, passaporto, razza, sesso, anno di nascita. |
| 7 | **Risultati storici gare** | Per ogni anno (`2004 → oggi`) interroga `db_results.php?anno=…&page=…`, individua i link alle pagine gara, estrae meta (data, categoria CEI*, km) e le righe di classifica (posizione, rider, cavallo, tempo totale, velocità, stato, tempi per loop, recupero cardiaco). |
| 8 | **Rankings mondiali** | Scarica `db_champions.php?v_filtro=…` per i filtri noti (Open / Young / Junior Riders & Horses, Italian rankings). |
| 9 | **Live tracking** | Snapshot informativo di `live/live.php` (eventi attualmente attivi). |
| 10 | **Esportazione CSV** | Scrive i quattro CSV principali in `./data/` con `encoding="utf-8-sig"`. |
| 11 | **Riepilogo** | Stampa contatori finali (righe per file, range anni, output dir). |

## 📦 File CSV prodotti

Tutti i file usano `utf-8-sig` (UTF-8 + BOM, leggibili da Excel) e separatore `,`.

### `horses_registry.csv` — anagrafica cavalli

| Campo | Descrizione |
|---|---|
| `name` | Nome del cavallo |
| `horse_id` | ID interno enduranceonline |
| `fei_id` | ID FEI (se disponibile) |
| `birth_year` | Anno di nascita |
| `breed` | Razza (Arabo, AA, ecc.) |
| `sex` | Sesso (M / F / G) |
| `microchip` | Numero microchip |
| `passport` | Numero passaporto |
| `sire` | Padre (genealogia) |
| `dam` | Madre (genealogia) |
| `breeder`, `owner`, `country` | Allevatore / proprietario / nazione |
| `letter` | Lettera iniziale usata in ricerca |
| `detail_url`, `*__href` | URL alle pagine sorgente |

### `results_full.csv` — risultati storici delle gare

| Campo | Descrizione |
|---|---|
| `year` | Anno della gara |
| `race_date` | Data (estratta dall'header gara) |
| `race_name` | Nome gara |
| `category` | Categoria FEI (CEI*, CEI**, CEI***, CEIYJ…) |
| `km` | Distanza totale |
| `country` | Nazione della gara o del cavaliere |
| `position` | Posizione finale |
| `rider` | Nome cavaliere |
| `horse` | Nome cavallo |
| `club` | Club di appartenenza |
| `total_time` | Tempo totale gara |
| `avg_speed` | Velocità media (km/h) |
| `status` | Stato finale (Finisher / Eliminato / Ritirato / Squalificato) |
| `penalties` | Penalità |
| `loop_1_time`, `loop_2_time`, … | Tempi per singolo loop / fase |
| `recovery_hr` | Frequenza cardiaca al vet gate (recupero) |
| `race_url`, `race_page_title` | Link sorgente |

### `rankings.csv` — classifiche mondiali

| Campo | Descrizione |
|---|---|
| `ranking_filter` | Nome del ranking (es. *Open Riders World Ranking*) |
| `position` / `rank` | Posizione in classifica |
| `rider` o `horse` | Soggetto in classifica |
| `country` | Nazione |
| `points` | Punteggio |
| `scraped_at` | Timestamp UTC dello scraping |

### `races_index.csv` — indice di tutte le gare

| Campo | Descrizione |
|---|---|
| `year` | Anno |
| `race_name` | Nome |
| `race_date` | Data |
| `category` | Categoria CEI |
| `km` | Distanza |
| `race_url` | URL pagina gara |
| `params` | Parametri GET originali (id gara) |

## 🤖 Campi utili per modelli predittivi

A partire dai CSV puoi costruire feature come:

- **Performance storica binomio rider+horse**: media velocità, % completamenti
  (`status == Finisher`), numero di gare nello stesso anno → da `results_full.csv`.
- **Età del cavallo al momento della gara**: `year - birth_year`
  (join `results_full.csv` ↔ `horses_registry.csv` su `horse`/`name`).
- **Esperienza del cavaliere**: numero gare e km cumulativi prima della gara target.
- **Difficoltà della gara**: `km`, `category`, numero partenti, % finisher.
- **Ritmo per loop**: differenza tra `loop_n_time` consecutivi → indicatore di
  fatica / strategia.
- **Recupero cardiaco** (`recovery_hr`): proxy della condizione fisica.
- **Genealogia**: feature categoriche da `sire` / `dam` per modelli a effetti
  random sul cavallo.
- **Ranking attuale**: join con `rankings.csv` (per `ranking_filter`).

## ⚙️ Note tecniche

- Tutti gli endpoint sono pagine PHP che restituiscono HTML; lo scraper non usa
  alcuna API non documentata.
- Politeness: **0.8 s di delay** tra richieste + jitter; retry esponenziale (max 4)
  su errori di rete o `5xx`.
- Encoding forzato a UTF-8 anche quando il server dichiara Latin-1.
- Il flag `TEST_MODE` controlla volume (lettere, anni, follow-up dettagli) per
  permettere un primo giro di validazione rapido.
- Lo scraping rispetta lo scopo informativo del sito: usa il notebook con
  buon senso ed evita esecuzioni concorrenti multiple.

## 📁 File nel repository

- [`endurance_scraper.ipynb`](./endurance_scraper.ipynb) — notebook principale
- [`requirements.txt`](./requirements.txt) — dipendenze Python
- `data/*.csv` — CSV generati dall'esecuzione (creati dopo il primo run)
