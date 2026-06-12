@echo off
setlocal
:: COMPASS_ROOT se resuelve en runtime desde la ubicacion del .bat (%~dp0).
:: %~dp0 expande a la carpeta del script con barra final — portable entre maquinas.
set "COMPASS_ROOT=%~dp0"
if "%COMPASS_ROOT:~-1%"=="\" set "COMPASS_ROOT=%COMPASS_ROOT:~0,-1%"
python "%COMPASS_ROOT%\compass.py" %*