@echo off
rem Doble clic: simulacro cronometrado del proximo examen (4 ejercicios, 40 minutos, sin pistas).
rem Usa el mismo entorno que Practicar.bat; si no existe, lo crea Practicar.bat.
chcp 65001 >nul <nul
rem Este .bat vive en otras-opciones\; se trabaja desde la raiz.
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto simulacro
echo Primero haz doble clic una vez en Practicar.bat (en la carpeta de arriba) para preparar el entorno.
pause
exit /b 1

:simulacro
"%PY%" programa\practica.py simulacro
pause
exit /b 0
