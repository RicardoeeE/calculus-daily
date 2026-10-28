@echo off
rem Doble clic: sesion de practica de hoy.
rem Esta consola solo se queda si hay que instalar o reparar algo; si no,
rem lanza la ventana sin consola (pythonw) y se cierra sola en 1-2 segundos.
rem La primera vez en cada equipo crea un entorno propio (.venv) con sympy y fsrs,
rem asi no depende de que Python haya en el PATH ni de lo que tenga instalado.
chcp 65001 >nul <nul
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto comprobar
echo Primera vez en este equipo: preparo el entorno (sympy, fsrs y la ventana). Tarda 1-2 minutos y solo se hace una vez.
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if not exist "%PY%" goto sin_python
goto instalar

:instalar
echo Instalando sympy y fsrs en el entorno del proyecto (despues, la ventana)...
"%PY%" -m pip install --disable-pip-version-check -q -r programa\requirements.txt
if errorlevel 1 (
  rem Solo se borra el entorno si falta lo necesario; un extra que falle no lo tira.
  "%PY%" programa\practica.py doctor >nul 2>&1
  if errorlevel 1 goto sin_red
  echo Aviso: no se instalo todo, pero lo necesario para practicar si esta.
)

:comprobar
rem doctor --rapido: sin red ni git (lo completo: `doctor`).
"%PY%" programa\practica.py doctor --rapido >nul 2>&1
if not errorlevel 1 goto practicar
rem Si falta algo (p. ej. se borro una libreria), se reinstala una vez, con tope de red.
echo Falta algo del entorno: intento reinstalarlo (max. 1 min)...
"%PY%" -m pip install --disable-pip-version-check -q --timeout 15 --retries 1 -r programa\requirements.txt >nul 2>&1
"%PY%" programa\practica.py doctor --rapido >nul 2>&1
if not errorlevel 1 goto practicar
echo Algo no esta bien. Revision:
"%PY%" programa\practica.py doctor
pause
exit /b 1

:practicar
rem Lo que crea el programa (.venv, .cache) queda oculto en la raiz
rem (attrib +h; sin error si ya lo esta). La .cache se crea aqui para ocultarla ya la primera vez.
if not exist ".cache" mkdir ".cache" >nul 2>&1
for %%D in (.venv .cache) do if exist "%%D" attrib +h "%%D" >nul 2>&1
rem La ventana es opcional. Si falta, se intenta instalar como mucho una
rem vez al dia (marca en .cache), avisando antes; si no se instala, la sesion va
rem en esta misma terminal. Hoy solo 2: boton en la ventana.
"%PY%" -c "import webview" >nul 2>&1
if not errorlevel 1 goto abrir_ventana
"%PY%" -c "import datetime, pathlib, sys; m = pathlib.Path('.cache/intento-ventana.txt'); h = datetime.date.today().isoformat(); hecho = m.exists() and m.read_text().strip() == h; m.parent.mkdir(exist_ok=True); m.write_text(h); sys.exit(1 if hecho else 0)" >nul 2>&1
if errorlevel 1 goto terminal
echo Intento instalar la ventana (max. 30 s)...
"%PY%" -m pip install --disable-pip-version-check -q --timeout 15 --retries 1 -r programa\requirements-ventana.txt >nul 2>&1
"%PY%" -c "import webview" >nul 2>&1
if errorlevel 1 goto terminal

:abrir_ventana
rem pythonw (sin consola) y desacoplada con start: esta consola se cierra ya
rem y cerrarla no cierra la ventana. Si la ventana no abre (WebView2...) o se cae,
rem ella misma abre otras-opciones\Terminal.bat en una consola nueva (--respaldo-terminal).
set "PYW=.venv\Scripts\pythonw.exe"
if not exist "%PYW%" goto terminal
start "" "%PYW%" programa\practica.py ventana --respaldo-terminal
exit /b 0

:terminal
"%PY%" programa\practica.py hoy
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
