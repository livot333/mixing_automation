"""mixing_params.py - JEDEN zdroj pravdy pro parametry cele pipeline michaci nadoby.

GUI (gui/mixing_gui.py) parametry edituje a uklada do mixing_params.json; vsechny
pipeline skripty (michadlo_geometry, nadoba_geometry, mesh_tank, run_cfd) si na zacatku
CONFIG bloku zavolaji load() a prepisou sve vychozi hodnoty. Kdyz JSON neexistuje,
pouziji se DEFAULTS zde -> skripty jdou spustit i samostatne bez GUI.

Cisty modul (jen stdlib json) - importovatelny v jakemkoli venv (geometry-core i
fluent-core i PySide6 GUI). Odvozene hodnoty (mrf_split, BLADE_LENGTH, dom_height,
LIQUID_LEVEL, omega, MODE) se NEUKLADAJI - pocitaji se v kazdem skriptu ze sdilene baze,
aby nemohly rozjet nekonzistenci.
"""

import json
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parent / "mixing_params.json"

# ---- PODMINKY VIDITELNOSTI (parametr se v GUI ukaze jen kdyz predikat vrati True) ----
# Predikat dostane aktualni slovnik parametru. None = vzdy viditelne.
def _pbt(p):        return str(p.get("impeller_type", "PBT")) == "PBT"        # PBT michadlo
def _is_rect(p):    return str(p.get("baffle_type", "triangular")) == "rectangular"
def _is_tri(p):     return str(p.get("baffle_type", "triangular")) == "triangular"
def _is_vof(p):     return bool(p.get("vof", True))
def _is_single(p):  return not bool(p.get("vof", True))
def _mode(p):       return "vof" if p.get("vof", True) else str(p.get("single_phase_mode", "steady"))
def _transient(p):  return _mode(p) != "steady"     # transient NEBO vof
def _steady(p):     return _mode(p) == "steady"
def _adv(p):        return bool(p.get("advanced", False))       # zaskrtnute "Pokrocile"
def _adv_vof(p):    return _adv(p) and _is_vof(p)

# ---- SCHEMA: skupiny -> parametry (pro stavbu GUI formulare) ----
# kazdy parametr: (klic, popisek, default, jednotka, typ, volby, viditelnost)
#   typ: "float" | "int" | "bool" | "choice"
#   volby: list moznosti pro "choice", jinak None
#   viditelnost: predikat(params)->bool nebo None (vzdy viditelne)
SCHEMA = [
    ("Nádoba", [
        ("tank_diameter",   "Průměr nádoby",         1000.0, "mm",  "float", None, None),
        ("tank_height",     "Výška (= hladina)",      1200.0, "mm",  "float", None, None),
        ("bottom_depth",    "Poloměr dna nádoby",      100.0, "mm",  "float", None, None),
        ("clearance",       "Výška středu míchadla",   300.0, "mm",  "float", None, None),
        # VOF je vlastnost domeny nadoby (volna hladina + vzduch nad ni) -> zaskrtnute=True,
        # propojeno se scriptem nadoba_geometry (klic 'vof').
        ("vof",             "VOF (volná hladina + vzduch)", True, "-", "bool", None, None),
    ]),
    ("Míchadlo", [
        # typ michadla - zatim jen PBT, pripraveno na dalsi typy (pak jim pridej vlastni
        # parametry s viditelnosti napr. lambda p: p["impeller_type"]=="Rushton")
        ("impeller_type",     "Typ míchadla", "PBT", "-", "choice", ["PBT"], None),
        ("impeller_diameter", "Průměr míchadla",  300.0, "mm",  "float", None, None),   # spolecne
        # --- parametry PBT (pitch blade turbine) ---
        ("n_blades",          "Počet lopatek",        4, "-",   "int",   None, _pbt),
        ("blade_tilt",        "Úhel lopatek",      45.0, "deg", "float", None, _pbt),
        ("blade_thickness",   "Tloušťka lopatky",   5.0, "mm",  "float", None, _pbt),
        ("blade_wide",        "Výška lopatky",     30.0, "mm",  "float", None, _pbt),
    ]),
    ("Narážky", [
        ("n_baffles",         "Počet narážek",           4, "-",  "int",    None, None),
        ("baffle_type",       "Typ narážky", "triangular", "-",  "choice", ["rectangular", "triangular"], None),
        # trojuhelnikove:
        ("baffle_tri_height", "Výška trojúhelníku",     120.0, "mm", "float", None, _is_tri),
        # obdelnikove:
        ("baffle_width",      "Šířka",                   100.0, "mm", "float", None, _is_rect),
        ("baffle_thickness",  "Tloušťka",                 10.0, "mm", "float", None, _is_rect),
        ("baffle_gap",        "Mezera od stěny",          20.0, "mm", "float", None, _is_rect),
    ]),
    # Pokrocile: checkbox "Pokrocile nastaveni" (jako VOF) odkryje MRF zonu + vysku vzduchu.
    ("Pokročilé", [
        ("advanced",   "Pokročilé nastavení (MRF / vzduch)", False, "-", "bool", None, None),
        ("mrf_auto",   "Automaticky dopočítat MRF", True, "-", "bool", None, _adv),
        ("mrf_radius", "Poloměr MRF válce", 250.0, "mm", "float", None, _adv),
        ("mrf_height", "Výška MRF válce",   200.0, "mm", "float", None, _adv),
        # zvetseni objemu domeny pro vzduch nad hladinou v % vysky nadoby (VOF); default 15%
        ("air_pct",    "Zvětšení objemu pro vzduch [%] (VOF)", 15.0, "%", "float", None, _adv_vof),
    ]),
    ("Režim / kapalina", [
        ("single_phase_mode", "Režim single-phase",      "steady", "-",       "choice", ["steady", "transient"], _is_single),
        ("density",          "Hustota kapaliny",           1100.0, "kg/m3",   "float",  None, None),
        ("viscosity",        "Viskozita kapaliny",          0.022, "kg/(m.s)", "float", None, None),
        ("surface_tension",  "Povrchové napětí (VOF)",      0.072, "N/m",     "float",  None, _is_vof),
        ("air_density",      "Hustota vzduchu (VOF)",       1.225, "kg/m3",   "float",  None, _is_vof),
        ("air_viscosity",    "Viskozita vzduchu (VOF)",   1.79e-5, "kg/(m.s)", "float", None, _is_vof),
    ]),
    ("Rotace", [
        ("rpm",     "Otáčky míchadla",        1470.0, "rpm", "float", None, None),
        ("rot_dir", "Směr rotace", "po směru hod. ručiček (doporučeno pro PBT)", "-", "choice",
         ["po směru hod. ručiček (doporučeno pro PBT)", "proti směru hod. ručiček"], None),
    ]),
    ("Síť", [
        ("mesh_density", "Hustota sítě", "coarse", "-", "choice", ["coarse", "medium", "fine"], None),
        ("processors",   "Počet jader",        4, "-", "int",    None, None),
    ]),
    ("Solver", [
        ("total_time",      "Napočítaný čas (transient/VOF)", 0.0025, "s", "float", None, _transient),
        ("iter_per_step",   "Iterace na krok (transient/VOF)",    15, "-", "int",   None, _transient),
        ("max_iter_steady", "Max iterací (steady)",               80, "-", "int",   None, _steady),
    ]),
]

# plochy slovnik vychozich hodnot (odvozeny ze SCHEMA)
DEFAULTS = {key: default for _grp, params in SCHEMA for (key, _lbl, default, _u, _t, _c, _v) in params}


def _baffle_depth(p):
    """Radialni hloubka narazky od steny dovnitr."""
    if str(p.get("baffle_type", "triangular")) == "triangular":
        return float(p.get("baffle_tri_height", 120.0))
    return float(p.get("baffle_gap", 20.0)) + float(p.get("baffle_width", 100.0))


def compute_mrf(p):
    """Vrati (mrf_radius, mrf_height) [mm].

    mrf_auto=False -> vrati ulozene hodnoty (rucni).
    mrf_auto=True  -> dopocita:
        prumer MRF = prumer michadla * 1.5 (tj. polomer = r_michadla*1.5),
        ale kdyby se dotkl narazek, koeficient se zmensuje az na 1.0 (prumer MRF =
        prumer michadla) tak, aby mezi MRF a narazkami byla mezera 0.001*D nadoby;
        vyska MRF = vyska lopatek * 2.
    """
    if not bool(p.get("mrf_auto", True)):
        return float(p.get("mrf_radius", 250.0)), float(p.get("mrf_height", 200.0))
    r_imp = float(p.get("impeller_diameter", 300.0)) / 2.0
    R = float(p.get("tank_diameter", 1000.0)) / 2.0
    n_baf = int(p.get("n_baffles", 4))
    baffle_inner = (R - _baffle_depth(p)) if n_baf > 0 else R
    gap = 0.001 * float(p.get("tank_diameter", 1000.0))     # odstup MRF od narazek
    max_r = baffle_inner - gap
    r = min(r_imp * 1.5, max_r)     # zacni na 1.5x, zmensi kdyz by narazil na narazky
    r = max(r, r_imp)               # koeficient nejmene 1.0 (prumer MRF = prumer michadla)
    h = 2.0 * float(p.get("blade_wide", 30.0))
    return r, h


def rot_sign(p):
    """Znamenko smeru rotace: -1 = po smeru hod. rucicek (doporuceno pro PBT), +1 = proti.

    Prijima novou volbu (retezec 'po smeru'/'proti smeru') i stare ciselne +1/-1.
    """
    v = p.get("rot_dir", -1)
    if isinstance(v, (int, float)):
        return -1 if v < 0 else 1
    return 1 if "proti" in str(v).lower() else -1


def dom_height(p):
    """Celkova vyska domeny: hladina (tank_height) zvetsena o air_pct % pro vzduch (jen VOF).

    Default air_pct=15 -> tank_height*1.15 (jako puvodne ve scriptu).
    """
    th = float(p.get("tank_height", 1200.0))
    if not bool(p.get("vof", True)):
        return th
    return th * (1.0 + float(p.get("air_pct", 15.0)) / 100.0)


def load():
    """Vrati parametry: DEFAULTS prepsane hodnotami z mixing_params.json (pokud existuje)."""
    data = dict(DEFAULTS)
    if JSON_PATH.is_file():
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception as exc:
            print("[mixing_params] nelze nacist %s (%s) - pouzivam defaulty" % (JSON_PATH, exc))
    return data


def save(params):
    """Zapise parametry do mixing_params.json (odsazene, utf-8)."""
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    return JSON_PATH


if __name__ == "__main__":
    # rychla kontrola: vypis defaulty a stav JSON
    print("JSON:", JSON_PATH, "(existuje)" if JSON_PATH.is_file() else "(neni - defaulty)")
    for k, v in load().items():
        print("  %-20s = %s" % (k, v))
