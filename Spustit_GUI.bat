@echo off
rem ==========================================================================
rem  Spousteci ikona pro GUI michaci nadoby (dvojklik).
rem  Otevre konzoli (vypis Discovery/Fluentu) a spusti main.py v pyAnsys venv.
rem ==========================================================================
setlocal
cd /d "%~dp0"

rem --- python z pyAnsys venv (fallback na python na PATH) ---
set "PY=C:\Users\tomasl\.virtualenvs\pyAnsys_SVSFEM\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem --- volitelne: cesta k Ansys v261 pro Fluent (odkomentuj a uprav, kdyz to hlasi
rem     "cannot find fluent.exe"). Slozka, kde je fluent\ntbin\win64\fluent.exe:
rem set "AWP_ROOT261=C:\Program Files\ANSYS Inc\v261"

echo Spoustim GUI michaci nadoby ...
"%PY%" main.py

echo.
echo (GUI ukonceno) - okno zavri klavesou.
pause
