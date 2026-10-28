@echo off
rem Doble clic: sesion extra para el proximo examen (no gasta el cupo diario).
rem Usa el mismo entorno que Practicar.bat; si no existe, lo crea Practicar.bat.
chcp 65001 >nul <nul
rem Este .bat vive en otras-opciones\; se trabaja desde la raiz.
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto examen
echo Primero haz doble clic una vez en Practicar.bat (en la carpeta de arriba) para preparar el entorno.
pause
exit /b 1

:examen
"%PY%" programa\practica.py examen
pause
exit /b 0
