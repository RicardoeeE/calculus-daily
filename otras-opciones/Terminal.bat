@echo off
rem Doble clic: la sesion de hoy en la terminal, sin ventana (programa\practica.py hoy).
rem El entorno (.venv) lo prepara Practicar.bat la primera vez.
chcp 65001 >nul <nul
rem Este .bat vive en otras-opciones\; se trabaja desde la raiz.
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto practicar
echo Aun no esta preparado el entorno: abre una vez Practicar.bat (en la carpeta de arriba; lo prepara) y vuelve.
pause
exit /b 1

:practicar
rem La ventana la abre asi como respaldo (pasa --minimo si hacia falta).
"%PY%" programa\practica.py hoy %*
pause
exit /b 0
