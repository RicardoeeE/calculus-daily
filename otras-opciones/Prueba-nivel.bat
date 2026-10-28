@echo off
rem Doble clic: prueba de nivel (hasta 10 ejercicios, sin pistas) para colocar la escalera al empezar.
rem La primera vez en cada equipo crea un entorno propio (.venv) con sympy y fsrs,
rem asi no depende de que Python haya en el PATH ni de lo que tenga instalado.
chcp 65001 >nul <nul
rem Este .bat vive en otras-opciones\; se trabaja desde la raiz.
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto comprobar
echo Primera vez en este equipo: preparo el entorno. Tarda 1-2 minutos y solo se hace una vez.
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if not exist "%PY%" goto sin_python
goto instalar

:instalar
echo Instalando sympy y fsrs en el entorno del proyecto...
"%PY%" -m pip install --disable-pip-version-check -q -r programa\requirements.txt
if errorlevel 1 (
  rem Solo se borra el entorno si falta lo necesario; un extra que falle no lo tira.
  "%PY%" programa\practica.py doctor >nul 2>&1
  if errorlevel 1 goto sin_red
  echo Aviso: no se instalo todo, pero lo necesario para practicar si esta.
)

:comprobar
"%PY%" programa\practica.py doctor >nul 2>&1
if not errorlevel 1 goto practicar
rem Si falta algo (p. ej. se borro una libreria), se reinstala una vez.
"%PY%" -m pip install --disable-pip-version-check -q -r programa\requirements.txt >nul 2>&1
"%PY%" programa\practica.py doctor >nul 2>&1
if not errorlevel 1 goto practicar
echo Algo no esta bien. Revision:
"%PY%" programa\practica.py doctor
pause
exit /b 1

:practicar
"%PY%" programa\practica.py nivel
pause
exit /b 0

:sin_python
echo No encuentro Python 3 en este equipo.
echo Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH" y vuelve a hacer doble clic.
pause
exit /b 1

:sin_red
echo No se pudieron instalar sympy y fsrs. Comprueba la conexion a internet y vuelve a probar.
rmdir /s /q .venv
pause
exit /b 1
