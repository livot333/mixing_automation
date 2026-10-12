"""michadlo_geometry.py - vytvori geometrii michadla pres PyAnsys Geometry.

Spustis normalnim Pythonem v PyAnsys prostredi (venv s ansys-geometry-core):

    python michadlo_geometry.py

Skript SAM spusti modelar (SpaceClaim nebo Discovery), postavi geometrii
(lopatky + naboj + hridel + MRF valec), pojmenuje zony pro CFD a vyexportuje
do michadlo_out/ (SCDOCX + STEP). Neni to SpaceClaim in-app skript (zadny
ViewHelper) - je to geometry-core API.
"""

import math
import sys
from pathlib import Path

# sdilene parametry z mixing_params.json (fallback = defaulty) - projekt je o uroven vys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mixing_params as _mp
import mixing_validate as _mv
P = _mp.load()

# kontrola parametru PRED spustenim (aby to nespadlo az v Discovery)
_ve, _vw = _mv.validate(P, "impeller")
for _m in _vw:
    print("[validace] varovani: %s" % _m)
if _ve:
    for _m in _ve:
        print("[validace] CHYBA: %s" % _m)
    raise SystemExit("Neplatne parametry michadla - oprav v GUI / mixing_params.json.")

from ansys.geometry.core import (
    launch_modeler_with_spaceclaim,
    launch_modeler_with_discovery,
)
from ansys.geometry.core.math import Point2D, Point3D, UnitVector3D
from ansys.geometry.core.misc import UNITS, DEFAULT_UNITS, Distance
from ansys.geometry.core.sketch import Sketch

# ---------------- PARAMETRY (mm / deg) - z mixing_params (fallback = default) ----------
diameter        = P.get("impeller_diameter", 300.0)   # celkovy VNEJSI prumer lopatek [mm]
blade_thickness = P.get("blade_thickness", 5.0)
blade_wide      = P.get("blade_wide", 30.0)            # vyska lopatky
blade_tilt      = P.get("blade_tilt", 45.0)
n_blades        = int(P.get("n_blades", 4))

# --- lopatka definovana pres vnitrni a vnejsi POLOMER (vnejsi = diameter/2) ---
outer_radius    = diameter / 2.0            # vnejsi hrana lopatek
hub_radius      = 0.20 * outer_radius
blade_embed     = 0.30 * hub_radius          # zapusteni vnitrni hrany do hubu (bez mezery)
inner_radius    = hub_radius - blade_embed   # vnitrni hrana lopatky (v hubu); >0 => zadne zdvojeni
blade_length    = outer_radius - inner_radius        # radialni delka lopatky = sirka boxu
blade_offset    = 0.5 * (inner_radius + outer_radius)  # radialni poloha stredu boxu

hub_height      = 1.05 * blade_wide
shaft_radius    = 0.10 * outer_radius
# --- delka hridele: dosahne az na VRSEK DOMENY (ne jen na hladinu) ---
# Hridel v lokalnich souradnicich jde 0..shaft_length, po vlozeni do nadoby je stred
# michadla na z=clearance, takze vrsek hridele je na (clearance + shaft_length).
# Chceme, aby dosahl na horni okraj DOMENY = dom_height. Pro VOF je dom_height o 15%
# vetsi nez tank_height (vzduch nad hladinou), takze hridel projde i vzduchovou zonou.
# POZN: tyto parametry MUSI odpovidat nadoba_geometry.py (tank_height/clearance/VOF).
# Prilis dlouha hridel = obri bounding box => size field spadne na "unable to allocate
# heap", ale (dom_height - clearance) je rozumne kratke, takze OK.
tank_height     = P.get("tank_height", 1200.0)   # = tank_height v nadobe (vyska valcove casti = hladina)
clearance       = P.get("clearance", 300.0)      # = clearance v nadobe (stred michadla nade dnem)
VOF             = bool(P.get("vof", True))        # = VOF v nadobe (True -> +15% vzduch nad hladinou)
dom_height      = tank_height * (1.15 if VOF else 1.0)   # horni okraj domeny
shaft_length    = tank_height * 1.2   # vrsek hridele presne na vrsku domeny
# Rozdeleni HRIDELE: spodni cast (v MRF zone) vs horni (nad MRF) - aby sel v meshi
# predepsat jiny sizing. mrf_split = mrf_height/2 (MRF valec vycentrovany na z=0).
# mrf_height bere ze STEJNEHO auto-dopoctu jako nadoba (compute_mrf), at hridel sedi.
mrf_split       = _mp.compute_mrf(P)[1] / 2.0
# POZN.: MRF valec se stavi az v nadobe (nadoba_geometry.py) - je to DOMENOVA zona,
# ne soucast michadla. Michadlo exportuje jen lopatky + naboj + hridel.

BACKEND = "discovery"    # "spaceclaim" | "discovery"
VERSION = None             # napr. 261; None = auto
OUT = Path(__file__).parent / "michadlo_out"
# ------------------------------------------------------

DEFAULT_UNITS.LENGTH = UNITS.mm


def mm(x):
    return Distance(x, UNITS.mm)


# ---- spusteni modelaru (headless - okno Discovery se neotevira) ----
kw = {"hidden": True}
if VERSION:
    kw["version"] = VERSION
print("spoustim modelar: %s ..." % BACKEND)
if BACKEND == "discovery":
    modeler = launch_modeler_with_discovery(**kw)
else:
    modeler = launch_modeler_with_spaceclaim(**kw)

try:
    design = modeler.create_design("Michadlo")
    ORIGIN = Point3D([0, 0, 0], UNITS.mm)
    AX_X = UnitVector3D([1, 0, 0])
    AX_Z = UnitVector3D([0, 0, 1])

    # ---- LOPATKY ----
    blades = []
    for k in range(n_blades):
        s = Sketch()
        s.box(Point2D([0, 0], UNITS.mm), blade_length, blade_thickness)   # box centrovany na stred, plne rozmery
        b = design.extrude_sketch("blade_%d" % k, s, blade_wide)          # vytazeni do vysky (z: 0..blade_wide)
        b.translate(AX_Z, mm(-blade_wide / 2.0))                          # -> stred kvadru v (0,0,0)
        b.rotate(ORIGIN, AX_X, math.radians(blade_tilt))                  # naklon kolem radialni osy (X)
        # ODSAZENI ven: stred boxu na blade_offset -> vnejsi hrana = outer_radius = diameter/2,
        # vnitrni hrana = inner_radius (zapustena v hubu). inner_radius>0 => zadne zdvojeni.
        b.translate(AX_X, mm(blade_offset))
        if k > 0:
            b.rotate(ORIGIN, AX_Z, k * 2.0 * math.pi / n_blades)         # rozmisteni kolem osy Z
        blades.append(b)

    # ---- NABOJ (hub), vycentrovany na z=0 ----
    s = Sketch()
    s.circle(Point2D([0, 0], UNITS.mm), hub_radius)
    hub = design.extrude_sketch("hub", s, hub_height)
    hub.translate(AX_Z, mm(-hub_height / 2.0))

    # ---- HRIDEL (rozdelena: shaft_lower v MRF, shaft_upper nad MRF) ----
    s = Sketch()
    s.circle(Point2D([0, 0], UNITS.mm), shaft_radius)
    shaft_lower = design.extrude_sketch("shaft_lower", s, mrf_split)          # z: 0 .. mrf_split (v MRF)
    s = Sketch()
    s.circle(Point2D([0, 0], UNITS.mm), shaft_radius)
    shaft_upper = design.extrude_sketch("shaft_upper", s, shaft_length - mrf_split)
    shaft_upper.translate(AX_Z, mm(mrf_split))                               # z: mrf_split .. shaft_length (nad MRF)

    # ---- POJMENOVANI: michadlo (wall) ----
    design.create_named_selection("impeller", bodies=blades + [hub, shaft_lower, shaft_upper])

    # ---- EXPORT ----
    OUT.mkdir(parents=True, exist_ok=True)
    for fmt, meth in (("SCDOCX", "export_to_scdocx"), ("STEP", "export_to_step")):
        try:
            getattr(design, meth)(location=str(OUT))
            print("vyexportovano %s do %s" % (fmt, OUT))
        except Exception as exc:
            print("export %s preskocen: %s" % (fmt, exc))

    # ---- PNG nahled pro GUI (OFFSCREEN, at neotevre okno a nezablokuje; kdyz spadne, nevadi) ----
    try:
        import pyvista as _pv
        _pv.OFF_SCREEN = True
        _prev = OUT / "Michadlo_preview.png"
        design.plot(screenshot=str(_prev))
        print("nahled ulozen %s" % _prev)
    except Exception as exc:
        print("nahled preskocen: %s" % str(exc).splitlines()[0][:90])

    print("hotovo.")
finally:
    try:
        modeler.close()
    except Exception:
        pass
