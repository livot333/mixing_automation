"""main.py - spousteni GUI michaci nadoby (PySide6).

    python main.py            # otevre GUI
    python main.py --run-all  # headless: michadlo -> nadoba -> sit -> solver (subprocessy)

GUI parametry uklada do mixing_params.json, ze ktereho ctou vsechny pipeline skripty.
Spust v PyAnsys venv (ma PySide6 i ansys.* i pyvista pro PNG nahled).
"""

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPELINE = [
    "michadlo_design/michadlo_geometry.py",
    "nadoba_design/nadoba_geometry.py",
    "meshing/mesh_tank.py",
    "solver/run_cfd.py",
]


def run_all():
    """Spusti celou pipeline v poradi; zastavi se pri prvni chybe."""
    from gui.procrun import find_pyansys_python
    py = find_pyansys_python()
    for rel in PIPELINE:
        script = ROOT / rel
        print("\n===== %s (%s) =====" % (rel, py))
        rc = subprocess.call([py, str(script)], cwd=str(script.parent))
        if rc != 0:
            print("!! %s skoncil s chybou (exit %d) - koncim." % (rel, rc))
            return rc
    print("\nHotovo - cela pipeline probehla.")
    return 0


def main():
    if "--run-all" in sys.argv:
        return run_all()

    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    from gui.uiscale import apply_base_font
    apply_base_font(app)
    from gui.mixing_gui import MainWindow
    win = MainWindow()
    win.show()          # normalni okno (ne fullscreen); velikost dle resize v MainWindow
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
