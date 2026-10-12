"""nadoba_geometry.py - michaci NADOBA (kulate dno) + nactene MICHADLO,
s vymezenim tekutinovych oblasti pro CFD (stationary vs MRF).

Postavi valcovou nadobu s KLENUTYM/kulatym dnem (revolve), MRF valec a narazky,
NACTE hotove michadlo (insert_file) a booleany vytvori ODDELENE oblasti:
  stationary_fluid = nadoba - MRF - hridel - narazky
  mrf_fluid        = MRF valec - michadlo
Michadlo a narazky zustavaji jako solidy (steny), share_topology dela konformni
rozhrani. Export do nadoba_out/.

Poradi: nejdriv spust michadlo_design/michadlo_geometry.py (vytvori Michadlo.*),
pak tento skript.
"""

import math
import sys
from pathlib import Path

# sdilene parametry z mixing_params.json (fallback = defaulty) - projekt je o uroven vys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mixing_params as _mp
import mixing_validate as _mv
P = _mp.load()

# kontrola parametru PRED spustenim (michadlo vs nadrz vs MRF, dno, narazky)
_ve, _vw = _mv.validate(P, "tank")
for _m in _vw:
    print("[validace] varovani: %s" % _m)
if _ve:
    for _m in _ve:
        print("[validace] CHYBA: %s" % _m)
    raise SystemExit("Neplatne parametry nadoby - oprav v GUI / mixing_params.json.")

from ansys.geometry.core import (
    launch_modeler_with_spaceclaim,
    launch_modeler_with_discovery,
)
from ansys.geometry.core.math import Point2D, Point3D, UnitVector3D, Vector3D, Plane
from ansys.geometry.core.misc import UNITS, DEFAULT_UNITS, Distance
from ansys.geometry.core.sketch import Sketch

# ================= PARAMETRY (mm / deg) - z mixing_params (fallback = default) ==========
tank_diameter   = P.get("tank_diameter", 1000.0)  # vnitrni prumer (sirka) nadoby
tank_height     = P.get("tank_height", 1200.0)    # vyska valcove casti
bottom_depth    = P.get("bottom_depth", 100)      # VZDOULENI (hloubka klenuteho dna) pod z=0
clearance       = P.get("clearance", 300.0)       # vyska stredu michadla nade dnem (z=0)

# --- VOF: vzduchovy prostor nad hladinou (vyska vzduchu = parametr air_height) ---
VOF             = bool(P.get("vof", True))        # True = VOF domena: vzduch nad hladinou
dom_height      = _mp.dom_height(P)               # hladina (tank_height) + air_height (jen VOF)

# --- narazky ---
baffle_type      = P.get("baffle_type", "triangular")   # "rectangular" | "triangular"
n_baffles        = int(P.get("n_baffles", 4))
# rectangular:
baffle_width     = P.get("baffle_width", 100)
baffle_thickness = P.get("baffle_thickness", 10.0)
baffle_gap       = P.get("baffle_gap", 20)
# triangular (rovnostranny troj., zakladna PRIMO na stene nadrze = bez mezery):
baffle_tri_height = P.get("baffle_tri_height", 120.0)   # vyska trojuhelniku (radialni hloubka)

# --- MRF zona (domenova, kolem michadla) - auto-dopocet nebo rucne (mrf_auto) ---
# auto: prumer = prumer michadla*1.5 (zmensi se kdyz by narazil na narazky, s odstupem
# 0.001*D nadoby), vyska = vyska lopatek*2. Viz mixing_params.compute_mrf.
mrf_radius, mrf_height = _mp.compute_mrf(P)

# --- hotove michadlo (auto: scdocx > STP > pmdb z michadlo_out) ---
# POZOR poradi: insert_file umi CAD (scdocx/step), NE pmdb (fasetovy format pro meshing).
# Na remote/PIM backendu scdocx neni -> MUSI nasledovat STEP, jinak by to spadlo na pmdb
# a insert_file by vratil prazdno => michadlo by v nadobe chybelo.
_mout = Path(__file__).parent.parent / "michadlo_design" / "michadlo_out"
_cands = (list(_mout.glob("Michadlo.scdocx")) + list(_mout.glob("Michadlo.stp"))
          + list(_mout.glob("Michadlo.pmdb")))
IMPELLER_FILE = str(_cands[0]) if _cands else str(_mout / "Michadlo.stp")

BACKEND = "discovery"     # "spaceclaim" | "discovery"
VERSION = None            # napr. 261; None = auto
OUT = Path(__file__).parent / "nadoba_out"
# ========================================================

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
    design = modeler.create_design("Nadoba_vof" if VOF else "Nadoba")   # VOF -> Nadoba_vof.* (koexistuje)
    ORIGIN = Point3D([0, 0, 0], UNITS.mm)
    AX_X = UnitVector3D([1, 0, 0])
    AX_Z = UnitVector3D([0, 0, 1])
    R = tank_diameter / 2.0
    z_imp = clearance

    # ===== NADOBA (kulate dno = revolve profilu; jinak ploche = extrude) =====
    if bottom_depth > 0:
        plane_xz = Plane(ORIGIN, UnitVector3D([1, 0, 0]), UnitVector3D([0, 0, 1]))
        prof = Sketch(plane=plane_xz)                                     # (u=polomer X, v=vyska Z)
        prof.segment(Point2D([0, dom_height], UNITS.mm), Point2D([R, dom_height], UNITS.mm))
        prof.segment(Point2D([R, dom_height], UNITS.mm), Point2D([R, 0], UNITS.mm))
        # DNO = JEDEN obloukovy edge (kruhova kulova klenba). Stred nad osou dna,
        # aby nejhlubsi bod byl na ose = -bottom_depth (ne aby oblouk pretekal niz).
        cz = (R * R - bottom_depth * bottom_depth) / (2.0 * bottom_depth)
        prof.arc(Point2D([R, 0], UNITS.mm), Point2D([0, -bottom_depth], UNITS.mm),
                 Point2D([0, cz], UNITS.mm), clockwise=True)
        prof.segment(Point2D([0, -bottom_depth], UNITS.mm), Point2D([0, dom_height], UNITS.mm))
        tank = design.revolve_sketch("tank", prof, Vector3D([0, 0, 1]), 360 * UNITS.degree, ORIGIN)
    else:
        s = Sketch()
        s.circle(Point2D([0, 0], UNITS.mm), R)
        tank = design.extrude_sketch("tank", s, dom_height)

    # ===== MRF valec (kolem michadla, vycentrovany na z_imp) =====
    s = Sketch()
    s.circle(Point2D([0, 0], UNITS.mm), mrf_radius)
    mrf = design.extrude_sketch("mrf", s, mrf_height)
    mrf.translate(AX_Z, mm(z_imp - mrf_height / 2.0))

    # ===== NARAZKY (else-if: rectangular / triangular) =====
    baffle_mid = R - baffle_gap - baffle_width / 2.0          # jen pro rectangular
    baffles = []
    for k in range(n_baffles):
        s = Sketch()
        if baffle_type == "triangular":
            # rovnostranny trojuhelnik: zakladna na stene (X=R) sirky b, vrchol dovnitr
            # v X=R-h. Rovnostranny => b = 2h/sqrt(3). Zakladna PRIMO na stene -> bez mezery
            # (rohy lehce presahnou valec, po subtractu je zakladna = plocha nadrze).
            b = 2.0 * baffle_tri_height / math.sqrt(3.0)
            s.segment(Point2D([R, -b / 2.0], UNITS.mm), Point2D([R, b / 2.0], UNITS.mm))
            s.segment(Point2D([R, b / 2.0], UNITS.mm), Point2D([R - baffle_tri_height, 0], UNITS.mm))
            s.segment(Point2D([R - baffle_tri_height, 0], UNITS.mm), Point2D([R, -b / 2.0], UNITS.mm))
            bf = design.extrude_sketch("baffle_%d" % k, s, dom_height)   # uz na spravnem miste u steny
        else:  # "rectangular"
            s.box(Point2D([0, 0], UNITS.mm), baffle_width, baffle_thickness)
            bf = design.extrude_sketch("baffle_%d" % k, s, dom_height)
            bf.translate(AX_X, mm(baffle_mid))                            # posun ke stene (s mezerou)
        if k > 0:
            bf.rotate(ORIGIN, AX_Z, k * 2.0 * math.pi / n_baffles)
        baffles.append(bf)

    # ===== NACTENI MICHADLA + posun na clearance =====
    comp = design.insert_file(IMPELLER_FILE)
    comp.translate_bodies(comp.get_all_bodies(), AX_Z, mm(z_imp))
    imp = comp.get_all_bodies()      # reference AZ po presunu (translate meni ID teles)
    print("[michadlo] nacteno teles: %d %s" % (len(imp), [b.name for b in imp]))

    # ===== PNG NAHLED pro GUI: PRED vytvorenim vnitrniho objemu (jeste jsou solidy) =====
    # Snimame vnejsi povrch: STENA NADRZE transparentne (80%, opacity 0.2), narazky a
    # michadlo pevne -> pekne videt vevnitr. Delame ted, dokud existuji tank(shell) +
    # narazky + michadlo; pozdeji je booleany zmeni na fluid a solidy se smazou.
    # MRF valec zamerne NEKRESLIME (je to jen domenova pomucka, zakryval by michadlo).
    try:
        import pyvista as _pv
        _pv.OFF_SCREEN = True
        from ansys.geometry.core.plotting import GeometryPlotter
        OUT.mkdir(parents=True, exist_ok=True)
        _prev = OUT / (("Nadoba_vof" if VOF else "Nadoba") + "_preview.png")
        _pl = GeometryPlotter()
        _pl.plot(tank, opacity=0.2, color="#9db4c8")     # stena nadrze - 80% transparent
        for _bf in baffles:
            _pl.plot(_bf, color="#e07b39")               # narazky
        for _b in imp:
            _pl.plot(_b, color="#8a8f99")                # michadlo (lopatky+naboj+hridel)
        _pl.show(screenshot=str(_prev))
        print("nahled ulozen %s" % _prev)
    except Exception as exc:
        print("nahled preskocen: %s" % str(exc).splitlines()[0][:90])

    # ===== BOOLEANY + POJMENOVANI DUTIN NA STRANE FLUIDU (diff ploch podle id) =====
    # Solidy odecteme z fluidu (vzniknou dutiny), po kazdem subtractu si ulozime NOVE
    # plochy fluidu = STENY dutiny. Solidy pak SMAZEME -> do mesheru jde uz jen cisty
    # fluid (tank + mrf), ale dutinove steny na nem zustanou a jdou pojmenovat.
    low  = [b for b in imp if "lower" in b.name.lower()]      # shaft_lower (v MRF)
    up   = [b for b in imp if "upper" in b.name.lower()]      # shaft_upper (nad MRF)
    rest = [b for b in imp if b not in low and b not in up]   # lopatky + naboj
    if not up:
        print("[POZOR] shaft_upper nenalezen dle nazvu - pregeneruj michadlo (split hridele)!")

    fids = lambda b: {f.id for f in b.faces}

    tank.subtract(mrf, keep_other=True)              # tank - MRF valec => rozhrani (nepojmenovane)

    ids0 = fids(mrf)
    mrf.subtract(rest, keep_other=True)              # dutina lopatek + naboje v MRF
    imp_ids = fids(mrf) - ids0
    ids0 = fids(mrf)
    if low:
        mrf.subtract(low, keep_other=True)           # dutina spodni hridele v MRF
    shaft_lo_ids = fids(mrf) - ids0

    ids0 = fids(tank)
    if up:
        tank.subtract(up, keep_other=True)           # dutina horni hridele v tank
    shaft_up_ids = fids(tank) - ids0
    # narazky odecist JEDNU PO DRUHE, at je muzeme pojmenovat zvlast (buffer_1..n)
    buffer_ids = []
    for bf in baffles:
        ids0 = fids(tank)
        tank.subtract([bf], keep_other=True)
        buffer_ids.append(fids(tank) - ids0)

    # ===== SMAZANI SOLIDU -> zustane cisty fluid (dutinove steny zustavaji) =====
    # POZOR: michadlo je v SUB-KOMPONENTE (insert_file vytvori comp). delete_body na
    # jednotliva telesa michadla casto SELZE (reference maji stale ID po booleanech, nebo
    # telo lezi v komponente) - API jen vypise warning "Body ... not found ... Ignoring"
    # a telo ZUSTANE. export_to_step komponentu NENESE (proto je STEP cisty), ale
    # export_to_pmdb ji faceted ZAHRNE -> v siti se objevi GHOST michadla jako dalsi telo.
    # Reseni: smazat CELOU komponentu michadla naraz (delete_component pracuje pres id
    # komponenty = imunni vuci stale ID jednotlivych teles).
    try:
        design.delete_component(comp)
        print("[del] komponenta michadla smazana")
    except Exception as exc:
        print("[del] komponenta michadla preskocena: %s" % exc)
    # narazky jsou KORENOVA telesa - smazat podle jmena (re-fetch z design.bodies, at
    # nepouzivame potencialne stale reference z listu 'baffles').
    for b in [bd for bd in design.bodies if bd.name.lower().startswith("baffle")]:
        try:
            design.delete_body(b)
        except Exception as exc:
            print("[del] %s preskoceno: %s" % (b.name, exc))

    # ===== POJMENOVANI (re-fetch ploch podle id + klasifikace sten podle typu plochy) =====
    mrf_now = {f.id: f for f in mrf.faces}
    tank_now = {f.id: f for f in tank.faces}
    pick = lambda now, ids: [now[i] for i in ids if i in now]
    R = tank_diameter / 2.0
    mmv = lambda q: q.to(UNITS.mm).m                # bounding_box vraci METRY -> mm
    def rmax_of(f):
        bb = f.bounding_box
        return max(abs(mmv(bb.min_corner.x)), abs(mmv(bb.max_corner.x)),
                   abs(mmv(bb.min_corner.y)), abs(mmv(bb.max_corner.y)))

    # STENA NADRZE = vsechny VALCOVE plochy na vnejsim polomeru (surface_type CYLINDER=2).
    # Spolehlive odlisi valcovou stenu od ROVINNYCH narazek, i kdyz narazka stenu rozrizne.
    wall_ids = set(fid for fid, f in tank_now.items()
                   if f.surface_type.value == 2 and rmax_of(f) > 0.9 * R)
    # z narazek ODEBRAT valcove kousky steny (patri do tank_walls, ne do buffer)
    buffer_ids = [b - wall_ids for b in buffer_ids]
    buffer_all = set()
    for b in buffer_ids:
        buffer_all |= b
    # vrch (free_surface) / dno (tank_bottom) podle polohy - vnejsi plochy mimo stenu i narazky
    free_ids, bottom_ids = set(), set()
    for fid, f in tank_now.items():
        if fid in wall_ids or fid in buffer_all or rmax_of(f) < 0.9 * R:
            continue
        bb = f.bounding_box
        if mmv(bb.min_corner.z) > 0.9 * dom_height:       # nejvyssi = volna hladina/vrch domeny
            free_ids.add(fid)
        elif mmv(bb.max_corner.z) < 0.1 * dom_height:     # nejnizsi = dno
            bottom_ids.add(fid)

    design.create_named_selection("stationary_fluid", bodies=[tank])
    design.create_named_selection("mrf_fluid", bodies=[mrf])
    design.create_named_selection("impeller_wall", faces=pick(mrf_now, imp_ids))
    if shaft_lo_ids:
        design.create_named_selection("shaft_lower", faces=pick(mrf_now, shaft_lo_ids))
    if shaft_up_ids:
        design.create_named_selection("shaft_upper", faces=pick(tank_now, shaft_up_ids))
    for i, bids in enumerate(buffer_ids, start=1):
        fs = pick(tank_now, bids)
        if fs:
            design.create_named_selection("buffer_%d" % i, faces=fs)
        else:
            print("[POZOR] buffer_%d: 0 ploch" % i)
    for nm, ids in (("tank_walls", wall_ids), ("tank_bottom", bottom_ids), ("free_surface", free_ids)):
        fs = pick(tank_now, ids)
        if fs:
            design.create_named_selection(nm, faces=fs)
        else:
            print("[POZOR] %s: 0 ploch" % nm)
    print("[ns] impeller_wall=%d, shaft_lower=%d, shaft_upper=%d"
          % (len(pick(mrf_now, imp_ids)), len(pick(mrf_now, shaft_lo_ids)),
             len(pick(tank_now, shaft_up_ids))))
    print("[ns] buffers=%s" % [len(pick(tank_now, b)) for b in buffer_ids])
    print("[ns] tank_walls=%d, tank_bottom=%d, free_surface=%d"
          % (len(pick(tank_now, wall_ids)), len(pick(tank_now, bottom_ids)),
             len(pick(tank_now, free_ids))))

    # ===== KONFORMNI ROZHRANI (uz jen fluid tank<->mrf) =====
    try:
        modeler.prepare_tools.share_topology([tank, mrf])
    except Exception as exc:
        print("share_topology preskocen: %s" % exc)

    print("[telesa] %s" % [bd.name for bd in design.bodies])
    print("[named selections] %s" % [ns.name for ns in design.named_selections])
    # kontrola: do site smi jit jen fluid (tank+mrf); cokoli s lopatkou/nabojem/hrideli
    # by v pmdb udelalo ghost michadlo -> varovat, at je to hned videt v konzoli
    _leftover = [bd.name for bd in design.bodies
                 if any(k in bd.name.lower() for k in ("blade", "hub", "shaft", "impeller", "michadlo"))]
    if _leftover:
        print("[POZOR] v designu ZUSTALA telesa michadla %s -> v siti bude ghost! "
              "Zkontroluj delete_component." % _leftover)

    # ===== EXPORT =====
    OUT.mkdir(parents=True, exist_ok=True)
    # NAZVY do meshingu: STEP nese named selections a je VZDY dostupny -> hlavni nosic.
    # PMDB nese jen plochy sten (impeller_wall...), ne cell-zone nazvy. SCDOCX by nesl
    # oboji, ale na remote/PIM backendu neni ke stazeni ("SCDOCX ... not supported for
    # download") -> davame ho AZ NAKONEC (kdyz spadne, STEP+PMDB uz jsou hotove).
    for fmt, meth in (("STEP", "export_to_step"), ("PMDB", "export_to_pmdb"),
                      ("SCDOCX", "export_to_scdocx")):
        try:
            getattr(design, meth)(location=str(OUT))
            print("vyexportovano %s do %s" % (fmt, OUT))
        except Exception as exc:
            print("export %s preskocen: %s" % (fmt, exc))

    # (PNG nahled nadoby se poridil driv - PRED booleany, viz vyse: stena transparentne.)

    print("hotovo.")
finally:
    try:
        modeler.close()
    except Exception:
        pass
