"""mixing_gui.py - GUI michaci nadoby (PySide6): wizard michadlo -> nadoba -> simulace.

Tok:
  1) Michadlo   - zadej parametry, [Generovat michadlo] -> nahled v okne, [Dale]
  2) Nadoba     - zadej parametry, [Generovat nadobu]   -> nahled v okne, [Dale]
  3) Simulace   - parametry rezimu/site/solveru, volba ukladani, [Simulovat]
                  (spusti meshing a Fluent), po dobehnuti [Ulozit vysledky].

Parametry jdou pres ../mixing_params.json (viz mixing_params.SCHEMA), skripty se spousti
jako subprocessy (gui.procrun). Vystupy se kopiruji do struktury slozek (gui.simstore).
"""

import sys
import math
from pathlib import Path

# aby slo spustit i primo (python gui/mixing_gui.py) - pridej koren projektu na path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6 import QtCore, QtGui, QtWidgets

import mixing_params as mp
import mixing_validate as mv
from gui import uiscale, simstore
from gui.procrun import StepRunner

ROOT = Path(__file__).resolve().parent.parent

# ktere skupiny SCHEMA patri do ktereho kroku wizardu
STEP_GROUPS = {
    0: ["Míchadlo"],
    1: ["Nádoba", "Narážky", "Pokročilé"],   # "Pokrocile" = checkbox odkryje MRF/vzduch
    2: ["Režim / kapalina", "Rotace", "Síť", "Solver"],
}
NAV_TITLES = ["Návrh míchadla", "Návrh nádoby", "Nastavení simulace"]

# nahledy geometrie (relativne k ROOT)
IMPELLER_PREVIEW = ROOT / "michadlo_design" / "michadlo_out" / "Michadlo_preview.png"
TANK_PREVIEW_VOF = ROOT / "nadoba_design" / "nadoba_out" / "Nadoba_vof_preview.png"
TANK_PREVIEW_STD = ROOT / "nadoba_design" / "nadoba_out" / "Nadoba_preview.png"
# placeholder kresby (nez se vygeneruje geometrie) - ve slozce gui/
MICHADLO_DRW = ROOT / "gui" / "michadlo_drw.png"
NADOBA_DRW = ROOT / "gui" / "nadoba_drw.png"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Michaci nadoba - CFD automat")
        self.resize(uiscale.col_w(285), uiscale.row_h(52))   # normalni okno, ne fullscreen

        self._widgets = {}          # klic parametru -> widget
        self._conditions = {}       # klic -> predikat viditelnosti (nebo None)
        self._rows = {}             # klic -> (QFormLayout, widget) pro skryvani radku
        self._gen_done = {"impeller": False, "tank": False}   # bylo v teto relaci vygenerovano?
        self._runner = StepRunner(self)
        self._runner.finished.connect(self._on_step_finished)
        self._queue = []            # fronta skriptu pro retezeni (Simulovat)
        self._on_all_done = None    # callback po dobehnuti fronty

        params = mp.load()
        self._build_ui(params)
        self._update_reynolds()
        self._apply_visibility()    # skryj parametry, ktere se pro aktualni volby nehodi
        self._refresh_mrf_auto()    # zamkni/doplni MRF pri automatickem rezimu
        self._preview_for_section(0)  # pocatecni placeholder kresba (michadlo_drw.png)

    # ---------- stavba UI ----------
    def _build_ui(self, params):
        # STRED: stack s parametry (prepina se levou navigaci)
        self._stack = QtWidgets.QStackedWidget()
        for i in range(3):
            self._stack.addWidget(self._build_step(i, params))

        # LEVA STRANA: svisla navigace - prepina stredni cast s parametry
        self._nav = QtWidgets.QListWidget()
        self._nav.addItems(NAV_TITLES)
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.currentRowChanged.connect(self._preview_for_section)   # nahled dle sekce
        self._nav.setFont(uiscale.heading_font())
        self._nav.setSpacing(6)
        self._nav.setMaximumWidth(uiscale.col_w(30))
        self._nav.setStyleSheet(
            "QListWidget { border:none; background:#2a2f37; }"
            "QListWidget::item { color:#dfe4ea; padding:12px 8px; border-radius:4px; }"
            "QListWidget::item:selected { background:#3d6ea5; color:white; }")

        # PRAVA STRANA: nahled geometrie (obrazek). Vystup skriptu jde do TERMINALU.
        self._preview = QtWidgets.QLabel("Nahled geometrie se zobrazi po vygenerovani.\n"
                                         "(Vystup Discovery/Fluentu bezi v terminalu.)")
        self._preview.setAlignment(QtCore.Qt.AlignCenter)
        self._preview.setMinimumSize(uiscale.col_w(50), uiscale.row_h(20))
        self._preview.setStyleSheet("QLabel { background:#20242b; color:#aab; border:1px solid #333; }")
        self._preview_path = None

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(self._nav)       # vlevo navigace
        split.addWidget(self._stack)     # uprostred parametry
        split.addWidget(self._preview)   # vpravo nahled
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 0)
        split.setStretchFactor(2, 1)
        split.setSizes([uiscale.col_w(30), uiscale.col_w(95), uiscale.col_w(85)])
        self.setCentralWidget(split)
        self.statusBar().showMessage("Pripraveno.")

    def _build_step(self, idx, params):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        title = QtWidgets.QLabel(NAV_TITLES[idx])       # nadpis stredni casti
        title.setFont(uiscale.heading_font())
        v.addWidget(title)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(inner)

        for grp_name in STEP_GROUPS[idx]:
            box = QtWidgets.QGroupBox(grp_name)
            fl = QtWidgets.QFormLayout(box)
            for (key, label, default, unit, typ, choices, cond) in _params_of(grp_name):
                w = self._make_widget(key, default, typ, choices, params.get(key, default))
                self._widgets[key] = w
                self._conditions[key] = cond
                self._rows[key] = (fl, w)
                cap = "%s [%s]" % (label, unit) if unit and unit != "-" else label
                fl.addRow(cap, w)
            form.addWidget(box)
        form.addStretch(1)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)

        # krok 3: volba ukladani (Reynolds se uz nezobrazuje)
        if idx == 2:
            v.addWidget(self._build_save_box())

        # akcni tlacitka (prepinani sekci je vlevo navigaci, ne tlacitky)
        v.addLayout(self._build_actions(idx))
        return page

    def _make_widget(self, key, default, typ, choices, value):
        if typ == "bool":
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(self._on_param_changed)
            return w
        if typ == "choice":
            w = QtWidgets.QComboBox()
            w.addItems([str(c) for c in (choices or [])])
            i = w.findText(str(value))
            if i >= 0:
                w.setCurrentIndex(i)
            w.currentTextChanged.connect(self._on_param_changed)   # prepnuti typu -> zmena viditelnosti
            return w
        if typ == "int":
            w = QtWidgets.QSpinBox()
            w.setRange(0, 1000000)
            w.setValue(int(value))
            w.valueChanged.connect(self._on_param_changed)
            return w
        # float
        w = QtWidgets.QDoubleSpinBox()
        w.setRange(0.0, 1.0e9)
        mag = abs(float(default)) if default else 1.0
        if mag and mag < 1e-2:            # mala cisla (viskozita, surface tension)
            w.setDecimals(8)
            w.setSingleStep(mag / 10.0 if mag else 1e-6)
        else:
            w.setDecimals(3)
            w.setSingleStep(1.0)
        w.setValue(float(value))
        w.valueChanged.connect(self._on_param_changed)
        return w

    def _refresh_mrf_auto(self):
        """Pri 'Automaticky' zamkne a doplni MRF polomer/vysku dopoctenymi hodnotami."""
        chk = self._widgets.get("mrf_auto")
        if chk is None:
            return
        auto = chk.isChecked()
        for k in ("mrf_radius", "mrf_height"):
            if k in self._widgets:
                self._widgets[k].setEnabled(not auto)
        if auto:
            r, h = mp.compute_mrf({**self._collect(), "mrf_auto": True})
            for k, val in (("mrf_radius", r), ("mrf_height", h)):
                w = self._widgets.get(k)
                if w is not None:
                    w.blockSignals(True)
                    w.setValue(float(val))
                    w.blockSignals(False)

    def _on_param_changed(self, *_a):
        self._update_reynolds()
        self._apply_visibility()
        self._refresh_mrf_auto()

    def _apply_visibility(self):
        """Skryje/ukaze parametry podle predikatu (typ michadla, typ narazek, VOF/rezim)."""
        p = self._collect()
        for key, cond in self._conditions.items():
            if cond is None:
                continue
            vis = bool(cond(p))
            fl, w = self._rows[key]
            try:
                fl.setRowVisible(w, vis)          # Qt 6.4+
            except Exception:
                w.setVisible(vis)
                lbl = fl.labelForField(w)
                if lbl is not None:
                    lbl.setVisible(vis)

    def _build_save_box(self):
        box = QtWidgets.QGroupBox("Ulozeni simulace")
        g = QtWidgets.QGridLayout(box)
        self._save_chk = QtWidgets.QCheckBox("Ulozit simulaci (struktura slozek)")
        self._save_chk.setChecked(True)
        self._save_chk.setToolTip(
            "Zapnuto: <cesta>/mixing_simulation/simulation_NN_d.._D.._a.._r.. se slozkami\n"
            "geometry / mesh / simulation / postprocessing.\n"
            "Vypnuto: pouze <cesta>/results se vsemi vystupy.")
        self._path_edit = QtWidgets.QLineEdit(str(ROOT.parent))
        browse = QtWidgets.QPushButton("Vybrat...")
        browse.clicked.connect(self._browse_dir)
        g.addWidget(self._save_chk, 0, 0, 1, 3)
        g.addWidget(QtWidgets.QLabel("Cesta:"), 1, 0)
        g.addWidget(self._path_edit, 1, 1)
        g.addWidget(browse, 1, 2)
        return box

    def _build_actions(self, idx):
        h = QtWidgets.QHBoxLayout()
        h.addStretch(1)
        if idx == 0:
            self._btn_gen_imp = QtWidgets.QPushButton("Generovat michadlo")
            self._btn_gen_imp.clicked.connect(self._gen_impeller)
            h.addWidget(self._btn_gen_imp)
        elif idx == 1:
            self._btn_gen_tank = QtWidgets.QPushButton("Generovat nadobu")
            self._btn_gen_tank.clicked.connect(self._gen_tank)
            h.addWidget(self._btn_gen_tank)
        else:
            self._btn_sim = QtWidgets.QPushButton("Simulation")
            self._btn_sim.clicked.connect(self._simulate)
            h.addWidget(self._btn_sim)
            self._btn_save = QtWidgets.QPushButton("Ulozit vysledky")
            self._btn_save.clicked.connect(self._save_simulation)
            h.addWidget(self._btn_save)
        return h

    # ---------- parametry ----------
    def _collect(self):
        out = dict(mp.DEFAULTS)
        for key, w in self._widgets.items():
            if isinstance(w, QtWidgets.QCheckBox):
                out[key] = bool(w.isChecked())
            elif isinstance(w, QtWidgets.QComboBox):
                out[key] = w.currentText()
            elif isinstance(w, QtWidgets.QSpinBox):
                out[key] = int(w.value())
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                out[key] = float(w.value())
        return out

    def _save_params(self):
        params = self._collect()
        mp.save(params)
        return params

    def _update_reynolds(self):
        if not hasattr(self, "_re_label"):
            return
        try:
            p = self._collect()
            n = float(p["rpm"]) / 60.0
            d = float(p["impeller_diameter"]) / 1000.0
            re = p["density"] * n * d * d / p["viscosity"] if p["viscosity"] else float("inf")
            if re < 10:
                reg = "laminarni"
            elif re < 1e4:
                reg = "prechodovy"
            else:
                reg = "turbulentni"
            self._re_label.setText("Reynolds Re = %.4g  (%s rezim),  n = %.3f 1/s" % (re, reg, n))
        except Exception:
            self._re_label.setText("")

    # ---------- akce ----------
    def _browse_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Slozka pro ulozeni", self._path_edit.text())
        if d:
            self._path_edit.setText(d)

    def _busy(self, on):
        for b in (getattr(self, n, None) for n in
                  ("_btn_gen_imp", "_btn_gen_tank", "_btn_sim", "_btn_save")):
            if b is not None:
                b.setEnabled(not on)

    def _validate_ok(self, errors, warnings):
        """Zaloguje varovani, pri chybach ukaze dialog a vrati False (nespoustet)."""
        if warnings:
            self._append_log("\n[validace] VAROVANI:\n" + "\n".join("  - " + w for w in warnings) + "\n")
        if errors:
            self._append_log("\n[validace] CHYBY - beh zastaven:\n"
                             + "\n".join("  - " + e for e in errors) + "\n")
            QtWidgets.QMessageBox.critical(
                self, "Neplatne parametry",
                "Nelze spustit - oprav tyto parametry:\n\n" + "\n".join(u"• " + e for e in errors))
            self.statusBar().showMessage("Beh zastaven - neplatne parametry.")
            return False
        return True

    def _gen_impeller(self):
        params = self._collect()
        e, w = mv.validate(params, "impeller")
        if not self._validate_ok(e, w):
            return
        self._save_params()
        self._queue = ["michadlo_design/michadlo_geometry.py"]
        self._on_all_done = self._after_impeller
        self._start_queue("Generuji michadlo v Discovery...")

    def _gen_tank(self):
        params = self._collect()
        e, w = mv.validate(params, "tank")
        if not self._validate_ok(e, w):
            return
        self._save_params()
        self._queue = ["nadoba_design/nadoba_geometry.py"]
        self._on_all_done = self._after_tank
        self._start_queue("Generuji nadobu v Discovery...")

    def _simulate(self):
        params = self._collect()
        # sit potrebuje existujici geometrii; solver kontrolujeme jen parametrove
        # (sit .msh.h5 vznikne tesne pred solverem -> check_files=False)
        e1, w1 = mv.validate(params, "mesh", check_files=True)
        e2, w2 = mv.validate(params, "solver", check_files=False)
        if not self._validate_ok(e1 + e2, w1 + w2):
            return
        self._save_params()
        self._queue = ["meshing/mesh_tank.py", "solver/run_cfd.py"]
        self._on_all_done = self._after_simulate
        self._start_queue("Sitovani (Fluent Meshing)...")

    def _after_impeller(self, ok):
        if ok:
            self._gen_done["impeller"] = True     # placeholder -> obrazek z Discovery
        self._preview_for_section(self._nav.currentRow())

    def _after_tank(self, ok):
        if ok:
            self._gen_done["tank"] = True
        self._preview_for_section(self._nav.currentRow())

    def _after_simulate(self, ok):
        if ok:
            self.statusBar().showMessage("Vypocet dobehl. Muzes 'Ulozit vysledky'.")
            self._show_result_preview()
        else:
            self.statusBar().showMessage("Vypocet skoncil s chybou - viz log.")

    def _start_queue(self, msg):
        if self._runner.is_running():
            QtWidgets.QMessageBox.information(self, "Bezi", "Uz neco bezi, pockej na dokonceni.")
            return
        self._busy(True)
        self.statusBar().showMessage(msg)
        self._run_next()

    def _run_next(self):
        script = self._queue.pop(0)
        self.statusBar().showMessage("Spoustim %s" % script)
        self._runner.run(ROOT / script, cwd=(ROOT / script).parent)

    def _on_step_finished(self, code):
        if code == 0 and self._queue:
            self._run_next()
            return
        self._busy(False)
        ok = (code == 0)
        cb, self._on_all_done = self._on_all_done, None
        self._queue = []
        if cb:
            cb(ok)
        if not ok:
            self.statusBar().showMessage("Skript skoncil s chybou (exit %d) - viz log." % code)

    # ---------- nahled ----------
    def _preview_for_section(self, idx):
        """Nahled dle aktivni sekce: placeholder kresba, dokud se nevygeneruje geometrie,
        pak obrazek z Discovery.
          sekce 0 (Navrh michadla) -> michadlo_drw.png / Michadlo_preview.png
          sekce 1,2 (Nadoba, Simulace) -> nadoba_drw.png / Nadoba(_vof)_preview.png
        """
        if idx == 0:
            if self._gen_done["impeller"] and IMPELLER_PREVIEW.is_file():
                path = IMPELLER_PREVIEW
            else:
                path = MICHADLO_DRW
        else:
            tank_prev = TANK_PREVIEW_VOF if self._collect().get("vof") else TANK_PREVIEW_STD
            if self._gen_done["tank"] and tank_prev.is_file():
                path = tank_prev
            elif self._gen_done["tank"] and TANK_PREVIEW_STD.is_file():
                path = TANK_PREVIEW_STD
            else:
                path = NADOBA_DRW
        self._preview_path = path
        self._render_preview()

    def _show_result_preview(self):
        """Po vypoctu ukaz prvni obrazek rychlosti."""
        self._preview_path = ROOT / "solver" / "vysledky" / "vmag_xz.png"
        self._render_preview()

    def _render_preview(self):
        p = self._preview_path
        if not p or not Path(p).is_file():
            self._preview.setText("Nahled nenalezen: %s" % (p.name if p else "-"))
            self._preview.setPixmap(QtGui.QPixmap())
            return
        pix = QtGui.QPixmap(str(p))
        if pix.isNull():
            self._preview.setText("Nahled nelze nacist: %s" % p.name)
            return
        self._preview.setPixmap(pix.scaled(self._preview.size(), QtCore.Qt.KeepAspectRatio,
                                           QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_preview_path", None):
            self._render_preview()

    # ---------- ulozeni vysledku ----------
    def _save_simulation(self):
        params = self._save_params()
        base = self._path_edit.text().strip()
        if not base or not Path(base).is_dir():
            QtWidgets.QMessageBox.warning(self, "Cesta", "Zadej platnou slozku pro ulozeni.")
            return
        try:
            targets = simstore.prepare_targets(base, params, self._save_chk.isChecked())
            copied = simstore.copy_outputs(targets, ROOT)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Chyba ulozeni", str(exc))
            return
        self._append_log("\n[ulozeno] %d souboru -> %s\n" % (len(copied), targets["root"]))
        QtWidgets.QMessageBox.information(
            self, "Ulozeno", "Ulozeno %d souboru do:\n%s" % (len(copied), targets["root"]))

    # ---------- log (do terminalu) / zavreni ----------
    def _append_log(self, text):
        # log v GUI zrusen - vypisujeme do terminalu (tam vystup funguje spolehlive)
        print(text, end="", flush=True)

    def closeEvent(self, event):
        if self._runner.is_running():
            self._runner.kill()
        super().closeEvent(event)


def _params_of(group_name):
    for grp, params in mp.SCHEMA:
        if grp == group_name:
            return params
    return []


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    uiscale.apply_base_font(app)
    _w = MainWindow()
    _w.show()           # normalni okno (ne fullscreen)
    raise SystemExit(app.exec())
