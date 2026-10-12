"""mixing_validate.py - kontrola validity parametru PRED spustenim jednotlivych casti.

Cil: aby geometrie/sit/solver nespadly kvuli nesmyslnym nebo nekonzistentnim parametrum
(napr. michadlo vetsi nez nadrz, MRF neobkopuje michadlo, rpm=0 -> deleni nulou v timestepu).

Pouziti:
    import mixing_validate as mv
    errors, warnings = mv.validate(params, "impeller"|"tank"|"mesh"|"solver")
    # errors = tvrde chyby (blokuji beh), warnings = rizika (jen upozorneni)

Stage odpovidaji krokum pipeline:
    impeller -> michadlo_design/michadlo_geometry.py
    tank     -> nadoba_design/nadoba_geometry.py
    mesh     -> meshing/mesh_tank.py
    solver   -> solver/run_cfd.py
"""

import os
import math
from pathlib import Path

import mixing_params as mp

ROOT = Path(__file__).resolve().parent
STAGES = ["impeller", "tank", "mesh", "solver"]


def _num(params, key):
    try:
        return float(params.get(key, mp.DEFAULTS.get(key, 0)))
    except Exception:
        return 0.0


def _check_processors(P, E):
    """Pocet jader >= 1 a MENSI nez pocet jader v tomto PC (nechat aspon 1 volne)."""
    procs = int(_num(P, "processors"))
    cpu = os.cpu_count() or 1
    if procs < 1:
        E.append("Pocet jader (processors) musi byt >= 1.")
    elif procs >= cpu:
        E.append("Pocet jader (%d) musi byt mensi nez pocet jader v PC (%d)." % (procs, cpu))


def _check_impeller(P, E, W, check_files=True):
    d = _num(P, "impeller_diameter")
    nb = int(_num(P, "n_blades"))
    th = _num(P, "blade_thickness")
    if d <= 0:
        E.append("Prumer michadla musi byt > 0 (je %.3g mm)." % d)
    if nb < 2:
        E.append("Pocet lopatek musi byt >= 2 (je %d)." % nb)
    if nb > 10:
        E.append("Pocet lopatek musi byt max 10 (je %d)." % nb)
    if _num(P, "blade_wide") <= 0:
        E.append("Vyska lopatky (blade_wide) musi byt > 0.")
    if th <= 0:
        E.append("Tloustka lopatky musi byt > 0.")
    if d > 0 and th > d / 6.0:
        E.append("nevhodna tloustka lopatek (tloustka %.3g > prumer/6 = %.3g mm)." % (th, d / 6.0))
    tilt = _num(P, "blade_tilt")
    if tilt < 0 or tilt >= 90:
        E.append("Sklon lopatek musi byt v <0, 90) deg (je %.3g)." % tilt)


def _check_tank(P, E, W, check_files=True):
    D_tank = _num(P, "tank_diameter")
    D_imp = _num(P, "impeller_diameter")
    R = D_tank / 2.0
    r_imp = D_imp / 2.0
    mrf_r, mrf_h = mp.compute_mrf(P)     # efektivni MRF (auto-dopocet nebo rucne)
    clr = _num(P, "clearance")
    th = _num(P, "tank_height")
    bd = _num(P, "bottom_depth")        # vzdouleni (hloubka klenuteho dna) pod z=0
    tilt = math.radians(_num(P, "blade_tilt"))
    # svisly polo-rozsah naklonene lopatky (box blade_wide x blade_thickness naklonen o tilt)
    blade_half = 0.5 * (_num(P, "blade_wide") * math.cos(tilt)
                        + _num(P, "blade_thickness") * math.sin(tilt))

    # vyska klenuteho dna v polomeru r (kulova vrchlik podle bottom_depth; 0 = ploche)
    def z_bottom(r):
        if bd <= 0:
            return 0.0
        cz = (R * R - bd * bd) / (2.0 * bd)   # stred koule na ose
        sph = cz + bd                         # polomer koule
        return cz - math.sqrt(max(sph * sph - r * r, 0.0))

    if R <= 0:
        E.append("Prumer nadrze musi byt > 0.")
    if th <= 0:
        E.append("Vyska nadrze musi byt > 0.")
    if clr <= 0:
        E.append("Vyska stredu michadla (clearance) musi byt > 0.")
    # vzdouleni dna musi byt v rozmezi 0 az polomer valce nadoby
    if bd < 0 or (R > 0 and bd > R):
        E.append("Polomer dna nadoby (%.3g) musi byt v rozmezi 0 az polomer nadrze (%.3g)." % (bd, R))

    # 1) nadrz musi byt vetsi nez michadlo
    if D_tank > 0 and D_imp > 0 and D_tank <= D_imp:
        E.append("Prumer nadrze (%.3g) musi byt vetsi nez prumer michadla (%.3g)." % (D_tank, D_imp))
    elif R > 0 and r_imp > 0.9 * R:
        W.append("Michadlo skoro vyplnuje nadrz (r_imp %.3g vs R %.3g) - male mezery." % (r_imp, R))

    # 2) hladina musi byt nad michadlem (vrch lopatek pod hladinou)
    imp_top = clr + blade_half
    if th > 0 and th <= imp_top:
        E.append("Hladina (tank_height=%.3g) musi byt nad michadlem (vrch michadla ~ %.3g)." % (th, imp_top))

    # 3) lopatky se nesmi dotykat dna (spodek michadla nad polokoulovym dnem v polomeru r_imp)
    imp_bottom = clr - blade_half
    if R > 0 and imp_bottom <= z_bottom(r_imp):
        E.append("Michadlo je moc nizko - lopatky by se dotykaly dna (spodek %.3g <= dno %.3g)."
                 % (imp_bottom, z_bottom(r_imp)))

    # narazky: hloubka od steny dovnitr + vnitrni polomer narazek
    n_baf = int(_num(P, "n_baffles"))
    btype = str(P.get("baffle_type", "triangular"))
    if btype not in ("rectangular", "triangular"):
        E.append("baffle_type musi byt 'rectangular' nebo 'triangular' (je '%s')." % btype)
    if n_baf < 0:
        E.append("Pocet narazek nesmi byt zaporny.")
    if n_baf > 18:
        E.append("Pocet narazek musi byt max 18 (je %d)." % n_baf)
    if btype == "triangular":
        baffle_depth = _num(P, "baffle_tri_height")
    else:
        baffle_depth = _num(P, "baffle_gap") + _num(P, "baffle_width")
    baffle_inner = R - baffle_depth        # vnitrni polomer, kam narazky dosahuji

    if n_baf > 0 and R > 0:
        if baffle_depth <= 0:
            E.append("Rozmery narazek musi byt > 0.")
        # 4) mezera+sirka (hloubka narazky) < polomer nadoby - polomer michadla
        if baffle_depth >= (R - r_imp):
            E.append("Narazky (hloubka %.3g) musi byt mensi nez polomer nadrze - polomer michadla (%.3g)."
                     % (baffle_depth, R - r_imp))

    # 5) MRF: obkopit michadlo, ale NEDOTKNOUT se narazek
    if mrf_r <= r_imp:
        E.append("MRF polomer (%.3g) musi byt vetsi nez polomer michadla (%.3g)." % (mrf_r, r_imp))
    limit = baffle_inner if n_baf > 0 else R
    if mrf_r >= limit:
        E.append("MRF se dotyka narazek/steny - mrf_radius (%.3g) musi byt mensi nez %.3g."
                 % (mrf_r, limit))

    # MRF vyska: kladna, obkopit lopatky, zustat v domene
    if mrf_h <= 0:
        E.append("MRF vyska musi byt > 0.")
    if mrf_h > 0 and mrf_h < _num(P, "blade_wide"):
        W.append("MRF vyska (%.3g) < vyska lopatky (%.3g) - MRF nemusi obsahnout lopatky."
                 % (mrf_h, _num(P, "blade_wide")))
    if R > 0 and clr - mrf_h / 2.0 <= z_bottom(mrf_r):
        E.append("MRF zasahuje pod dno nadrze (spodek MRF %.3g <= dno %.3g)."
                 % (clr - mrf_h / 2.0, z_bottom(mrf_r)))
    if th > 0 and clr + mrf_h / 2.0 > th:
        W.append("MRF sahá nad hladinu (%.3g > tank_height=%.3g)." % (clr + mrf_h / 2.0, th))


def _check_mesh(P, E, W, check_files=True):
    if str(P.get("mesh_density", "coarse")) not in ("coarse", "medium", "fine"):
        E.append("mesh_density musi byt coarse/medium/fine.")
    _check_processors(P, E)
    # vstupni geometrie musi existovat (jinak mesh_tank spadne na SystemExit)
    if check_files:
        vof = bool(P.get("vof", True))
        pre = "Nadoba_vof" if vof else "Nadoba"
        out = ROOT / "nadoba_design" / "nadoba_out"
        if not (list(out.glob(pre + ".pmdb")) or list(out.glob(pre + ".stp"))
                or list(out.glob(pre + ".scdocx"))):
            E.append("Chybi geometrie nadoby (%s.pmdb/.stp) - nejdriv 'Generovat nadobu'." % pre)


def _check_solver(P, E, W, check_files=True):
    _check_processors(P, E)          # pocet jader < pocet jader v PC
    if _num(P, "density") <= 0:
        E.append("Hustota kapaliny musi byt > 0.")
    if _num(P, "viscosity") <= 0:
        E.append("Viskozita kapaliny musi byt > 0.")
    if _num(P, "rpm") <= 0:
        E.append("Otacky (rpm) musi byt > 0 (jinak nulovy casovy krok / deleni nulou).")
    # smer rotace je volba (po/proti smeru) -> rot_sign vzdy da +-1, netreba tvrde kontroly
    if int(_num(P, "iter_per_step")) < 1:
        E.append("Iterace na krok musi byt >= 1.")
    if int(_num(P, "max_iter_steady")) < 1:
        E.append("Max iteraci (steady) musi byt >= 1.")
    vof = bool(P.get("vof", True))
    mode = "vof" if vof else str(P.get("single_phase_mode", "steady"))
    if not vof and mode not in ("steady", "transient"):
        E.append("single_phase_mode musi byt 'steady' nebo 'transient'.")
    if mode != "steady" and _num(P, "total_time") <= 0:
        E.append("Napocitany cas (total_time) musi byt > 0 pro transient/VOF.")

    # dlouhe vypocty = jen VAROVANI (jde spustit): steady > 1e6 iter; transient/VOF > 30 s
    if mode == "steady" and int(_num(P, "max_iter_steady")) > 1000000:
        W.append("Steady: %d iteraci je hodne - vypocet zabere hodne casu."
                 % int(_num(P, "max_iter_steady")))
    if mode != "steady" and _num(P, "total_time") > 30.0:
        W.append("Transient/VOF: napocitany cas %.3g s je velky - vypocet zabere hodne casu."
                 % _num(P, "total_time"))
    if vof:
        if _num(P, "surface_tension") < 0:
            E.append("Povrchove napeti nesmi byt zaporne.")
        if _num(P, "air_density") <= 0:
            E.append("Hustota vzduchu musi byt > 0.")
        if _num(P, "air_viscosity") <= 0:
            E.append("Viskozita vzduchu musi byt > 0.")
    # vstupni sit musi existovat (pri Simulovat se preskoci - sit vznika tesne predtim)
    if check_files:
        pre = "nadoba_vof" if vof else "nadoba"
        if not (ROOT / "meshing" / (pre + ".msh.h5")).is_file():
            E.append("Chybi sit %s.msh.h5 - nejdriv spust sitovani ('Simulovat')." % pre)


_CHECKS = {
    "impeller": _check_impeller,
    "tank": _check_tank,
    "mesh": _check_mesh,
    "solver": _check_solver,
}


def validate(params, stage, check_files=True):
    """Vrati (errors, warnings) pro dany stage.

    stage: 'impeller'|'tank'|'mesh'|'solver'|'all'
    check_files=False preskoci kontrolu existence vstupnich souboru (geometrie/sit) -
        pouzij pri 'Simulovat', kde sit vznika tesne pred solverem.
    """
    E, W = [], []
    stages = STAGES if stage == "all" else [stage]
    for st in stages:
        fn = _CHECKS.get(st)
        if fn:
            fn(params, E, W, check_files)
    return E, W


def format_report(errors, warnings):
    """Text pro vypis do konzole/dialogu."""
    lines = []
    if errors:
        lines.append("CHYBY (nutno opravit):")
        lines += ["  - " + e for e in errors]
    if warnings:
        lines.append("VAROVANI (lze pokracovat):")
        lines += ["  - " + w for w in warnings]
    if not errors and not warnings:
        lines.append("Parametry OK.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    P = mp.load()
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    E, W = validate(P, stage)
    print("=== validace parametru (stage=%s) ===" % stage)
    print(format_report(E, W))
    sys.exit(1 if E else 0)
