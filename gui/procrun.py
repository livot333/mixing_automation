"""procrun.py - spousteni pipeline skriptu jako subprocess pres QProcess.

Skripty (michadlo/nadoba geometrie, mesh, solver) bezi v PyAnsys venv - vlastni proces,
aby pad Fluentu/Discovery neshodil GUI a log se streamoval zive. StepRunner obali jeden
QProcess a vysila signaly output(str) / finished(int).
"""

import os
import sys
import importlib.util
from pathlib import Path

from PySide6 import QtCore


def find_pyansys_python() -> str:
    """Vrati interpreter, ktery umi spustit pipeline skripty (ansys.geometry+fluent).

    1) kdyz jsou baliky importovatelne v TOMTO interpretu -> sys.executable (GUI bezi
       primo v pyAnsys venv, coz je typicky pripad);
    2) env promenna PYANSYS_PYTHON;
    3) znamy venv pyAnsys_SVSFEM.
    """
    def _has(mods):
        try:
            return all(importlib.util.find_spec(m) is not None for m in mods)
        except Exception:
            return False

    if _has(("ansys.geometry.core", "ansys.fluent.core")):
        return sys.executable
    env = os.environ.get("PYANSYS_PYTHON")
    if env and Path(env).is_file():
        return env
    guess = Path.home() / ".virtualenvs" / "pyAnsys_SVSFEM" / "Scripts" / "python.exe"
    if guess.is_file():
        return str(guess)
    return sys.executable   # posledni moznost - at to aspon zkusi


class StepRunner(QtCore.QObject):
    """Obal nad jednim QProcess pro spusteni jednoho skriptu.

    Signaly:
        output(str)   - kazdy kus stdout/stderr (merged) pro zivy log
        finished(int) - exit kod po dobehnuti
    """

    finished = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QtCore.QProcess | None = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QtCore.QProcess.NotRunning

    def run(self, script_path, cwd=None, python=None) -> bool:
        """Spusti `python script_path` v cwd. Vrati False, kdyz uz neco bezi.

        Vystup Discovery/Fluentu jde PRIMO do terminalu (ForwardedChannels) - v GUI se
        log nezobrazuje (spolehlivejsi nez ho zachytavat a prepisovat).
        """
        if self.is_running():
            return False
        py = python or find_pyansys_python()
        proc = QtCore.QProcess(self)
        proc.setProgram(py)
        proc.setArguments([str(script_path)])
        if cwd:
            proc.setWorkingDirectory(str(cwd))
        proc.setProcessChannelMode(QtCore.QProcess.ForwardedChannels)   # vystup -> terminal
        proc.finished.connect(self._on_finished)
        self._proc = proc
        print("\n$ %s %s" % (Path(py).name, Path(script_path).name), flush=True)
        proc.start()
        return True

    def kill(self) -> None:
        if self.is_running():
            self._proc.kill()

    def _on_finished(self, code: int, _status) -> None:
        print("--- hotovo (exit %d) ---" % code, flush=True)
        self._proc = None
        self.finished.emit(int(code))
