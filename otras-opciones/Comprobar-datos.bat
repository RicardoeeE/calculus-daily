@echo off
rem Doble clic: como estan tus datos, en lenguaje llano: cuantos intentos hay,
rem cuando fue la ultima copia y si esta comprobada, si falta algo o hay lineas apartadas.
rem No cambia nada. Para recuperar lo que falte: programa\practica.py datos --recuperar.
chcp 65001 >nul <nul
rem Este .bat vive en otras-opciones\; se trabaja desde la raiz.
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto datos
echo Aun no esta preparado el entorno: abre una vez Practicar.bat (en la carpeta de arriba; lo prepara) y vuelve.
pause
exit /b 1

:datos
"%PY%" programa\practica.py datos
pause
exit /b 0
