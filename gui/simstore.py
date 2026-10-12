"""simstore.py - ukladani vystupu simulace do struktury slozek.

SAVE = True:
    <base>/mixing_simulation/simulation_NN_d<d>_D<D>_a<a>_r<r>/
        geometry/        Michadlo.*, Nadoba*.*, *_preview.png
        mesh/            nadoba*.msh.h5
        simulation/      nadoba*.cas.h5 / .dat.h5, *.out
        postprocessing/  vysledky.csv, *.png
        mixing_params.json
    (NN = poradove cislo simulace; d=prumer michadla, D=prumer nadrze,
     a=sklon lopatek, r=rpm)

SAVE = False:
    <base>/results/   - vse vyse dohromady v jedne slozce
"""

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# zdroje vystupu (relativne k PROJECT_ROOT) -> kategorie
SOURCES = {
    "geometry": [
        "michadlo_design/michadlo_out/Michadlo.*",
        "michadlo_design/michadlo_out/*_preview.png",
        "nadoba_design/nadoba_out/Nadoba*.*",
    ],
    "mesh": [
        "meshing/nadoba.msh.h5",
        "meshing/nadoba_vof.msh.h5",
    ],
    "simulation": [
        "solver/nadoba.cas.h5", "solver/nadoba.dat.h5",
        "solver/nadoba_vof.cas.h5", "solver/nadoba_vof.dat.h5",
        "solver/vysledky/*.out",
    ],
    "postprocessing": [
        "solver/vysledky/*.csv",
        "solver/vysledky/*.png",
    ],
}


def _i(x):
    """Cislo -> cely retezec bez desetinne casti (pro nazev slozky)."""
    try:
        return str(int(round(float(x))))
    except Exception:
        return str(x)


def sim_folder_name(params: dict, number: int) -> str:
    """simulation_NN_d<prumer michadla>_D<prumer nadrze>_a<sklon>_r<rpm>."""
    return "simulation_%02d_d%s_D%s_a%s_r%s" % (
        number,
        _i(params.get("impeller_diameter", 0)),
        _i(params.get("tank_diameter", 0)),
        _i(params.get("blade_tilt", 0)),
        _i(params.get("rpm", 0)),
    )


def next_sim_number(mixing_root: Path) -> int:
    """Nejnizsi volne poradove cislo (podle existujicich slozek simulation_NN_...)."""
    if not mixing_root.is_dir():
        return 1
    nums = []
    for d in mixing_root.glob("simulation_*"):
        if d.is_dir():
            part = d.name.split("_", 2)
            if len(part) >= 2 and part[1].isdigit():
                nums.append(int(part[1]))
    return (max(nums) + 1) if nums else 1


def prepare_targets(base_dir, params: dict, save: bool) -> dict:
    """Vytvori cilove slozky a vrati mapu {kategorie: Path, 'root': Path, 'name': str}."""
    base = Path(base_dir)
    if save:
        mixing_root = base / "mixing_simulation"
        mixing_root.mkdir(parents=True, exist_ok=True)
        num = next_sim_number(mixing_root)
        name = sim_folder_name(params, num)
        root = mixing_root / name
        targets = {cat: root / cat for cat in SOURCES}
        for p in targets.values():
            p.mkdir(parents=True, exist_ok=True)
        targets["root"] = root
        targets["name"] = name
    else:
        root = base / "results"
        root.mkdir(parents=True, exist_ok=True)
        targets = {cat: root for cat in SOURCES}
        targets["root"] = root
        targets["name"] = "results"
    return targets


def copy_outputs(targets: dict, project_root: Path = PROJECT_ROOT) -> list:
    """Nakopiruje vsechny existujici vystupy do cilovych slozek. Vrati seznam (src->dst)."""
    copied = []
    for cat, patterns in SOURCES.items():
        dst_dir = Path(targets[cat])
        for pat in patterns:
            for src in project_root.glob(pat):
                if src.is_file():
                    dst = dst_dir / src.name
                    try:
                        shutil.copy2(src, dst)
                        copied.append((src, dst))
                    except Exception:
                        pass
    # kopie parametru simulace k rootu
    jp = project_root / "mixing_params.json"
    if jp.is_file():
        try:
            shutil.copy2(jp, Path(targets["root"]) / "mixing_params.json")
            copied.append((jp, Path(targets["root"]) / "mixing_params.json"))
        except Exception:
            pass
    return copied
