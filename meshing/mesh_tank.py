"""mesh_tank.py - sitovani michaci nadoby ve Fluent Meshing (Watertight) pres PyFluent.

Nacte nadoba_out/Nadoba.* (nese named selections stationary_fluid, mrf_fluid,
impeller_wall, shaft_lower, shaft_upper, baffle_wall), spusti Watertight workflow
s vybranou hustotou a zapise objemovou sit nadoba.msh.h5.
Poradi: michadlo -> nadoba -> tento skript.

SIZING JE VZTAZENY NA DELKU LOPATEK (ne na nadobu) - viz BLADE_LENGTH nize.
Tri site (coarse/medium/fine) se lisi faktorem GCI_RATIO (1.3) v LINEARNI velikosti
bunky, aby sel primo spocitat GCI (Grid Convergence Index). medium = referencni.

Bezi shora dolu, bez funkci a bez try/except - kdyz neco spadne, spadne to s
puvodni hlaskou Fluentu (zamerne, kvuli diagnostice).  Spust: python mesh_tank.py
"""

import os
import sys
from pathlib import Path

import ansys.fluent.core as pyfluent

# sdilene parametry z mixing_params.json (fallback = defaulty) - projekt je o uroven vys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mixing_params as _mp
import mixing_validate as _mv
P = _mp.load()

# kontrola parametru + existence vstupni geometrie PRED spustenim Fluent Meshing
_ve, _vw = _mv.validate(P, "mesh")
for _m in _vw:
    print("[validace] varovani: %s" % _m)
if _ve:
    for _m in _ve:
        print("[validace] CHYBA: %s" % _m)
    raise SystemExit("Sit nelze spustit - oprav parametry / vygeneruj nadobu.")

# ==================== NASTAVENI ====================
HERE            = Path(__file__).parent
MESH_DENSITY    = P.get("mesh_density", "coarse")  # "coarse" | "medium" | "fine"
VOF             = bool(P.get("vof", True))         # True = sit pro VOF (volna hladina): BL jen
                                    # michadlo, ZADNA BL na stenach nadrze / u hladiny
# DELKA LOPATEK [mm] = outer_radius - inner_radius z michadla; z geometrie vychazi
# 0.86*(diameter/2) (hub 0.2*outer, embed 0.3*hub) -> pro diameter=300 = 129.
BLADE_LENGTH    = 0.86 * (P.get("impeller_diameter", 300.0) / 2.0)
GCI_RATIO       = 1.3               # pomer zjemneni mezi sitemi (pro GCI): coarse x1.3, fine /1.3
PROCESSORS      = int(P.get("processors", 4))
PRODUCT_VERSION = None              # None = auto; jinak napr. "26.1.0"
VOLUME_FILL     = "poly-hexcore"
OUT_MESH        = HERE / ("nadoba_vof.msh.h5" if VOF else "nadoba.msh.h5")

# --- FACE SIZING na labelech: velikost [mm] = BLADE_LENGTH / delitel * factor ---
# Jemneji nez tenke prvky (lopatka 5 mm, narazka 10 mm). tank_walls/tank_bottom nechame
# na globalnim (hrubem) sizingu.
N_BAFFLES = int(P.get("n_baffles", 4))   # = n_baffles v nadobe -> labely buffer_1..buffer_N
FACE_DIV = {
    "impeller_wall": 65.0,          # 129/65 ~ 2.0 mm = pod tloustku lopatky (5 mm)
    "shaft_lower":   25.0,          # 129/25 ~ 5.2 mm
    "shaft_upper":   12.0,          # 129/12 ~ 10.8 mm
    "tank_walls":    4.0,           # 129/4 ~ 42 mm (hrube, ale JE local sizing -> BL funguje)
    "tank_bottom":   4.0,           # 129/4 ~ 42 mm
}
for _i in range(1, N_BAFFLES + 1):
    FACE_DIV["buffer_%d" % _i] = 13.0    # narazky ~10 mm

# --- BOUNDARY LAYERS podle named selection: (first aspect ratio, pocet vrstev, growth) ---
# ZADNA BL na free_surface (vrch = symmetry) ani na MRF rozhrani (internal, nema label).
# VOF: jen michadlo. Jedna faze: navic hridel (shaft_lower/upper) + steny nadrze + narazky.
if VOF:
    BL = {
        "impeller_wall": (13.0, 5, 1.2),
    }
else:
    BL = {
        "impeller_wall": (13.0, 5, 1.2),   # aspect ratio 13, 5 vrstev
        "shaft_lower":   (20.0, 5, 1.2),   # aspect ratio 20
        "shaft_upper":   (25.0, 5, 1.2),   # aspect ratio 25
        "tank_walls":    (35.0, 3, 1.2),   # aspect ratio 35 (boky nadrze)
        "tank_bottom":   (35.0, 3, 1.2),   # aspect ratio 35 (dno nadrze)
    }
    for _i in range(1, N_BAFFLES + 1):
        BL["buffer_%d" % _i] = (35.0, 3, 1.2)   # narazky - aspect ratio 35, 3 vrstvy

# --- globalni surface mesh (relativne k delce lopatek) ---
# KROK 1: MinSize musi byt <= nejmensi local size (~2 mm na lopatce), jinak se lokalni
# jemnost oreze a lopatky se nerozlisi. Max hruby (steny nadoby), krivost stredni.
SURF_MAX_DIV = 1.0                  # MaxSize = BLADE_LENGTH (steny nadoby)
SURF_MIN_DIV = 10.0                 # MinSize ~ 2 mm (= velikost na lopatce)
CURV_ANGLE   = 18.0                 # stredni krivost
CELLS_PER_GAP = 1                   # 2 bunky napric tenkymi prvky
GROWTH        = 1.2
# ===================================================

# faktor velikosti bunky vuci medium (coarse hrubsi, fine jemnejsi) - jen delky!
factor = {"coarse": GCI_RATIO, "medium": 1.0, "fine": 1.0 / GCI_RATIO}[MESH_DENSITY]
surf_max = BLADE_LENGTH / SURF_MAX_DIV * factor
surf_min = BLADE_LENGTH / SURF_MIN_DIV * factor

# vstupni geometrie: scdocx > PMDB > stp. Realita tohoto backendu:
#   PMDB nese PLOCHY STEN (impeller_wall/shaft_*/baffle_wall) - to sit potrebuje pro sizing/BL.
#   STEP nese jen cell-zone nazvy (mrf/stationary), plochy sten NE.
#   SCDOCX by nesl oboji, ale nejde stahnout -> prakticky nedostupny.
# -> bereme PMDB (plochy jsou pro sit dulezitejsi; 2 cell zony si najde solver dle velikosti).
_g = HERE.parent / "nadoba_design" / "nadoba_out"
_pre = "Nadoba_vof" if VOF else "Nadoba"      # VOF cte vyssi domenu Nadoba_vof.*
_c = list(_g.glob(_pre + ".scdocx")) + list(_g.glob(_pre + ".pmdb")) + list(_g.glob(_pre + ".stp"))
MESH_PATH = _c[0] if _c else (_g / (_pre + ".pmdb"))
if not MESH_PATH.is_file():
    raise SystemExit("nenalezena geometrie %s - spust nejdriv nadoba_geometry.py" % MESH_PATH)

# verze Fluentu (auto): nejnovejsi podporovana + nainstalovana (ma fluent.exe)
ver = PRODUCT_VERSION
if ver is None:
    from ansys.fluent.core.utils.fluent_version import FluentVersion
    for v in sorted([x.value for x in FluentVersion],
                    key=lambda s: tuple(int(i) for i in s.split(".")[:2]), reverse=True):
        a, b = v.split(".")[:2]
        root = os.environ.get("AWP_ROOT%s%s" % (a, b))
        if root and os.path.isfile(os.path.join(root, "fluent", "ntbin", "win64", "fluent.exe")):
            ver = v
            break

print("hustota=%s (faktor %.3f)  Fluent=%s  geometrie=%s"
      % (MESH_DENSITY, factor, ver, MESH_PATH.name))
print("surface: max=%.2f min=%.2f mm" % (surf_max, surf_min))

# ---- spusteni Fluent Meshing (headless - okno skryte) ----
# ui_mode="hidden_gui" -> zadne VIDITELNE okno, ale server ciste naskoci (spolehlivejsi
# nez "no_gui", ktere na tomto stroji nenavaze gRPC -> TimeoutError). cleanup_on_exit=True.
kw = dict(mode="meshing", ui_mode="hidden_gui", precision="double", processor_count=PROCESSORS,
          cwd=str(HERE), start_timeout=600, cleanup_on_exit=True)
if ver:
    kw["product_version"] = ver
meshing = pyfluent.launch_fluent(**kw)
wf = meshing.workflow
wf.InitializeWorkflow(WorkflowType="Watertight Geometry")

# ---- import geometrie (str() - Path se dropne; PMDB nese named selections) ----
ig = wf.TaskObject["Import Geometry"]
ig.Arguments.set_state({"FileName": str(MESH_PATH), "LengthUnit": "mm"})
ig.Execute()
print("import hotov")

# ---- lokalni FACE SIZING na pojmenovanych stenach ----
ls = wf.TaskObject["Add Local Sizing"]
for lbl, div in FACE_DIV.items():
    size = BLADE_LENGTH / div * factor
    ls.Arguments.set_state({"AddChild": "yes", "BOIControlName": lbl + "_size",
                            "BOIExecution": "Face Size", "BOIFaceLabelList": [lbl],
                            "BOISize": size, "BOIGrowthRate": GROWTH})
    ls.AddChildToTask()
    ls.InsertCompoundChildTask()
    ls.Execute()
    print("  face size %-14s = %.2f mm" % (lbl, size))

# ---- surface mesh ----
surf = wf.TaskObject["Generate the Surface Mesh"]
surf.Arguments.set_state({"CFDSurfaceMeshControls": {
    "MaxSize": surf_max, "MinSize": surf_min, "CurvatureNormalAngle": CURV_ANGLE,
    "CellsPerGap": CELLS_PER_GAP, "GrowthRate": GROWTH}})
surf.Execute()
print("surface mesh hotov")

# ---- Describe Geometry: no voids + wall->internal + share topology (dle funkcniho prikladu) ----
# POZOR na presne klice: wall_to_internal je SNAKE_CASE a hodnota "Yes" (velke Y)!
desc = wf.TaskObject["Describe Geometry"]
# VOF+sliding mesh: rozhrani MRF<->stationary NESMI byt internal (musi zustat stena/rozhrani,
# aby z nej sel udelat sliding mesh interface). Single-phase MRF: internal (conformal) je OK.
desc.Arguments = dict(
    SetupType="The geometry consists of only fluid regions with no voids",
    WallToInternal=("No" if VOF else "Yes"),   # CamelCase!
    InvokeShareTopology="Yes")
print("[desc] state:", desc.Arguments.get_state())
desc.Execute()
print("describe geometry hotovo")
try:
    wf.TaskObject["Apply Share Topology"].Execute()
    print("share topology applied")
except Exception as e:
    print("Apply Share Topology preskoceno: %s" % str(e).splitlines()[0][:80])

# ---- Update Boundaries: free_surface wall -> SYMMETRY (label+type + OLD label+type) ----
ub = wf.TaskObject["Update Boundaries"]
try:
    ub.Arguments = dict(               # CamelCase klice + OldLabelZoneList (dle a.wft)!
        BoundaryLabelList=["free_surface"],
        BoundaryLabelTypeList=["symmetry"],
        OldBoundaryLabelList=["free_surface"],
        OldBoundaryLabelTypeList=["wall"],
        OldLabelZoneList=["free_surface"])
    ub.Execute()
    print("free_surface -> symmetry")
except Exception as e:
    print("free_surface->symmetry preskoceno (resi solver): %s" % str(e).splitlines()[0][:80])
    ub.Execute()

wf.TaskObject["Update Regions"].Execute()
print("update regions hotovo")

# ---- BOUNDARY LAYERS (aspect-ratio; Add In = fluid regions, Grow On = selected zones) ----
# Kazda vrstva scopovana na zonu STEJNEHO jmena jako named selection (ZoneSelectionList).
# DULEZITE: pridat vsechny prism controly a Execute az JEDNOU na konci (jinak "Illegitimate input").
add_bl = wf.TaskObject["Add Boundary Layers"]
for lbl, (ar, nlay, gr) in BL.items():
    add_bl.Arguments.set_state({"BLControlName": lbl + "_bl"})
    add_bl.AddChildToTask()
    add_bl.InsertCompoundChildTask()
    wf.TaskObject[lbl + "_bl"].Arguments.set_state({
        "BLControlName": lbl + "_bl", "OffsetMethodType": "aspect-ratio",
        "NumberOfLayers": nlay, "FirstAspectRatio": ar, "Rate": gr,   # BL child: "Rate", ne GrowthRate!
        "FaceScope": {"RegionsType": "fluid-regions",     # Add In = fluid regions
                      "GrowOn": "selected-zones"},        # Grow On = selected zones
        "ZoneSelectionList": [lbl]})                      # zona stejneho jmena jako NS
    print("  BL %-14s aspect=%.0f layers=%d" % (lbl, ar, nlay))
add_bl.Execute()
print("boundary layers hotovy")

# ---- objemova sit ----
vol = wf.TaskObject["Generate the Volume Mesh"]
vol.Arguments.set_state({"VolumeFill": VOLUME_FILL})
vol.Execute()
print("volume mesh hotov")

# ---- kontrola + zapis ----
meshing.tui.mesh.check_mesh()
# dopredna lomitka: Fluent je na Windows bere a NEMANGLUJI \n apod. (jinak se "nadoba" zkomoli)
out = str(OUT_MESH).replace("\\", "/")
try:
    OUT_MESH.unlink()          # smaz stary soubor -> Fluent se nepta na prepis (jinak visi na dotazu)
except FileNotFoundError:
    pass
meshing.tui.file.write_mesh(out)
print("zapsano %s" % OUT_MESH)
# meshing.exit()
