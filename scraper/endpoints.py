"""Mappa completa degli endpoint reali del sito Endurance Online.

Indici scoperti via DevTools. Gli indici 22-26 erano troncati nel browser ma
seguono lo stesso schema ``?v_filtro=`` degli altri.
"""

from __future__ import annotations

BASE = "https://www.enduranceonline.it"

ENDPOINTS: list[str] = [
    f"{BASE}/contacts/contacts.php",
    f"{BASE}/db/db.php",
    f"{BASE}/db/db_champions.php?v_filtro=CEN%20A%20Under%2014",
    f"{BASE}/db/db_champions.php?v_filtro=CEN%20BR%20Under%2014",
    f"{BASE}/db/db_champions.php?v_filtro=Criterium%20Pony",
    f"{BASE}/db/db_champions.php?v_filtro=Criterium%20Senior",
    f"{BASE}/db/db_champions.php?v_filtro=Criterium%20Under%2014",
    f"{BASE}/db/db_champions.php?v_filtro=Criterium%20Young%20Riders",
    f"{BASE}/db/db_champions.php?v_filtro=Debuttanti%20Under%2014",
    f"{BASE}/db/db_champions.php?v_filtro=European%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Italian%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Italian%20Championships%20CEI1*",
    f"{BASE}/db/db_champions.php?v_filtro=Italian%20Championships%20CEI2*",
    f"{BASE}/db/db_champions.php?v_filtro=Open%20Combination%20World%20Ranking",
    f"{BASE}/db/db_champions.php?v_filtro=Open%20Horse%20World%20Ranking",
    f"{BASE}/db/db_champions.php?v_filtro=Open%20Riders%20World%20Ranking",
    f"{BASE}/db/db_champions.php?v_filtro=Pony%20A",
    f"{BASE}/db/db_champions.php?v_filtro=Pony%20Avviamento",
    f"{BASE}/db/db_champions.php?v_filtro=Pony%20B",
    f"{BASE}/db/db_champions.php?v_filtro=Pony%20Elite",
    f"{BASE}/db/db_champions.php?v_filtro=Pony%20Emergenti",
    f"{BASE}/db/db_champions.php?v_filtro=World%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Horses%207%20YO%20World%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Horses%208%20YO%20World%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20CEIYJ1*%20Italian%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20Combination%20World%20Ranking",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20European%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20Horse%20World%20Ranking",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20Italian%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20World%20Championships",
    f"{BASE}/db/db_champions.php?v_filtro=Young%20Riders%20World%20Ranking",
    f"{BASE}/db/db_ewc_2026.php",
    f"{BASE}/db/db_horses.php",
    f"{BASE}/db/db_horses_km.php?v_f=120",
    f"{BASE}/db/db_horses_km.php?v_f=160",
    f"{BASE}/db/db_horses_km.php?v_f=30",
    f"{BASE}/db/db_horses_km.php?v_f=60",
    f"{BASE}/db/db_horses_km.php?v_f=90",
    f"{BASE}/db/db_horses_top.php",
    f"{BASE}/db/db_horses_win.php",
    f"{BASE}/db/db_results.php",
    f"{BASE}/db/db_riders.php",
    f"{BASE}/db/db_riders_km.php?v_f=120",
    f"{BASE}/db/db_riders_km.php?v_f=160",
    f"{BASE}/db/db_riders_km.php?v_f=30",
    f"{BASE}/db/db_riders_km.php?v_f=60",
    f"{BASE}/db/db_riders_km.php?v_f=90",
    f"{BASE}/db/db_riders_top.php",
    f"{BASE}/db/db_riders_win.php",
    f"{BASE}/db/db_team_italia.php",
    f"{BASE}/events/events.php",
    f"{BASE}/live/live.php",
    f"{BASE}/login/login.php",
    f"{BASE}/news/news_list.php",
    f"{BASE}/suite/suite.php",
]

# Indici delle classifiche d'élite usati come seed.
# 14 = Open Horse World Ranking
# 21 = World Championships
# 34 = db_horses_km 160 (top distance specialists)
# 38 = db_horses_top
# 39 = db_horses_win
ELITE_SEED_INDICES: tuple[int, ...] = (14, 21, 34, 38, 39)

# Template per la pagina di dettaglio cavallo (le due forme accettate dal server).
HORSE_DETAIL_TEMPLATE_FISE = f"{BASE}/db/db_horse_new.php?FISE_Cavallo={{id}}&info=1"
HORSE_DETAIL_TEMPLATE_FEI = f"{BASE}/db/db_horse_new.php?FEI_Cavallo={{id}}&info=1"
HORSE_RESULTS_TEMPLATE_FISE = f"{BASE}/db/db_horse_new.php?FISE_Cavallo={{id}}&results=1"
HORSE_RESULTS_TEMPLATE_FEI = f"{BASE}/db/db_horse_new.php?FEI_Cavallo={{id}}&results=1"


def elite_seed_urls() -> list[str]:
    """URL delle classifiche élite da cui estrarre gli ID iniziali."""
    return [ENDPOINTS[i] for i in ELITE_SEED_INDICES]
