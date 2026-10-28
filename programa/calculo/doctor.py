"""Comprobacion rapida de que todo esta en orden antes de practicar.

No importa sympy ni fsrs al cargar: si faltan, lo dice en vez de caerse. Practicar no necesita git: sus fallos son avisos (OJO)."""
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import registro
from .rutas import HERRAMIENTAS, RAIZ

VERSIONES = {"sympy": "1.14.0", "fsrs": "6.3.2"}
PYWEBVIEW = "6.2.1"   # requirements-ventana.txt: la ventana es opcional
WEBVIEW2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_CLAVES_WEBVIEW2 = (
    ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2}"),
    ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2}"),
    ("HKEY_CURRENT_USER", rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2}"),
)
_MARCAS = re.compile(r"^(<{7}|>{7}|={7})( |$)", re.M)


def revisar(rapido=False):
    """Devuelve lista de (ok, mensaje). ok=None es un aviso que no impide practicar.
    rapido=True (Practicar.bat): sin red, sin repositorio ni muestras del verificador."""
    r = []
    r.append((sys.version_info >= (3, 11), f"Python {sys.version.split()[0]} (hace falta 3.11 o mas)"))
    faltan = False
    for paquete, fijada in VERSIONES.items():
        try:
            v = version(paquete)
            r.append((True if v == fijada else None,
                      f"{paquete} {v}" + ("" if v == fijada else
                                          f" (probado con {fijada}; si algo falla: python -m pip install --user {paquete}=={fijada})")))
        except PackageNotFoundError:
            faltan = True
            r.append((False, f"falta {paquete}: python -m pip install --user {paquete}=={fijada}"))
    r.extend(_ventana())
    fichas = {}
    if not faltan:
        try:
            from .fichas import cargar
            fichas = cargar()
            r.append((True, f"{len(fichas)} fichas cargadas"))
            from .fichas import cargar_grafo
            r.append((True, f"grafo de tecnicas: {len(cargar_grafo(fichas=fichas))} tecnicas que contienen otras"))
        except Exception as exc:  # cualquier error de una ficha impide practicar
            r.append((False, f"fichas: {exc}"))
    try:
        entradas = registro.leer(estricto=True)
        r.append((True, f"usuario/datos/registro.jsonl: {len(entradas)} intentos validos"))
        if fichas:
            huerfanas = sorted({e["ficha"] for e in entradas} - set(fichas))
            if huerfanas:
                r.append((None, f"intentos de fichas que ya no existen (se ignoran): {', '.join(huerfanas)}"))
    except registro.ErrorRegistro as exc:   # al empezar la sesion se aparta sola (calculo/datos.py)
        r.append((None, f"{exc}. Al empezar la sesion se aparta a usuario/datos/apartado-*.jsonl (sin borrarla)"))
    for nombre in ("usuario/datos/registro.jsonl", "usuario/diario.md", "usuario/datos/notas.jsonl"):
        ruta = RAIZ / nombre
        if ruta.exists() and _MARCAS.search(ruta.read_text(encoding="utf-8")):
            r.append((False, f"{nombre} tiene marcas de conflicto de git (<<<<<<<): hay que resolverlo"))
    if rapido:
        return r
    if fichas:
        try:
            from .sesion import comprobar
            malas = []
            for f in list(fichas.values())[::10]:  # una de cada diez, de todos los tipos
                v = f.variante(1)
                if not comprobar(v, v.respuesta_modelo).correcto:
                    malas.append(f.id)
            r.append((not malas, "el verificador acepta las soluciones de muestra"
                      + (f" salvo {', '.join(malas)}" if malas else "")))
        except Exception as exc:
            r.append((False, f"verificador: {exc}"))
    r.extend(_recordatorio())
    r.extend(_git())
    r.extend(_datos())
    return r


def _datos():
    """Seccion «datos»: intentos, copias, perdidas, apartadas y commits sin subir."""
    try:
        from . import datos
        return datos.resumen()
    except Exception as exc:
        return [(None, f"datos: no se pudo revisar ({type(exc).__name__}: {exc})")]


def version_webview2():
    """Version del runtime WebView2 (el motor de Edge para ventanas) o None."""
    if sys.platform != "win32":
        return None
    import winreg
    for raiz, clave in _CLAVES_WEBVIEW2:
        try:
            with winreg.OpenKey(getattr(winreg, raiz), clave) as k:
                v, _ = winreg.QueryValueEx(k, "pv")
                if v and v != "0.0.0.0":
                    return v
        except OSError:
            continue
    return None


def _ventana():
    """La ventana es opcional: lo que falte es un aviso (OJO), nunca MAL."""
    try:
        v = version("pywebview")
    except PackageNotFoundError:
        v = None
    w = version_webview2() if sys.platform == "win32" else "no hace falta"
    if v is None:
        return [(None, "ventana: falta pywebview; se practica en la terminal "
                       "(python -m pip install -r programa\\requirements-ventana.txt)")]
    if w is None:
        return [(None, "ventana: falta WebView2 (el motor de Edge); se practica en la terminal")]
    if v != PYWEBVIEW:
        return [(None, f"ventana: pywebview {v} (probada con {PYWEBVIEW}; "
                       "python -m pip install -r programa\\requirements-ventana.txt)")]
    return [(True, f"ventana: pywebview {v}, WebView2 {w}")]


TAREA = "calculo-diario recordatorio"


def _consultar_tarea():
    """(codigo, xml) de `schtasks /query /tn TAREA /xml`: solo lectura."""
    r = subprocess.run(["schtasks", "/query", "/tn", TAREA, "/xml"], capture_output=True, text=True,
                       errors="replace", timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, r.stdout


def _recordatorio(consultar=None):
    """OJO si la tarea programada del recordatorio existe pero apunta a otro
    recordatorio.ps1 (p. ej. de una copia antigua de la carpeta). Sin tarea, nada."""
    if sys.platform != "win32" and consultar is None:
        return []
    try:
        codigo, xml = (consultar or _consultar_tarea)()
    except (OSError, subprocess.SubprocessError):
        return []
    if codigo:
        return []   # no hay tarea: el recordatorio es opcional
    m = re.search(r"-File\s+(?:\"|&quot;)(.+?)(?:\"|&quot;)", xml or "")
    esperado = HERRAMIENTAS / "recordatorio.ps1"
    if m is None:
        return [(None, f"recordatorio: la tarea «{TAREA}» no lanza recordatorio.ps1; reinstalala "
                       "(programa\\herramientas\\instalar-recordatorio.ps1)")]
    ruta = m.group(1)
    if str(Path(ruta)).lower().rstrip("\\/") != str(esperado).lower():
        return [(None, f"recordatorio: la tarea «{TAREA}» usa {ruta}, no la de esta carpeta ({esperado}); "
                       "reinstalala con programa\\herramientas\\instalar-recordatorio.ps1")]
    return [(True, f"recordatorio: tarea «{TAREA}» instalada")]


def _git():
    def git(*args, timeout=15):
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
    try:
        if git("rev-parse", "--is-inside-work-tree").returncode:
            return [(None, "la carpeta no es un repositorio git: se practica igual, sin copia en GitHub")]
        r = []
        remoto = git("remote", "get-url", "origin")
        if remoto.returncode:
            return [(None, "sin remoto en GitHub: se practica igual, pero no hay copia fuera del portatil")]
        r.append((True, f"remoto: {remoto.stdout.strip()}"))
        if (RAIZ / ".git" / "MERGE_HEAD").exists() or git("ls-files", "-u").stdout.strip():
            r.append((False, "hay una fusion de git a medias: hay que resolverla"))
        pendientes = git("status", "--porcelain", "usuario").stdout.strip()
        r.append((None if pendientes else True,
                  "usuario/ guardado en git" if not pendientes
                  else "hay cambios en usuario/ sin commit: se guardaran al cerrar la proxima sesion"))
        try:
            git("fetch", "-q", timeout=20)
            cuenta = git("rev-list", "--left-right", "--count", "HEAD...@{u}")
            if cuenta.returncode == 0:
                locales, remotos = (int(n) for n in cuenta.stdout.split())
                if remotos:
                    r.append((None, f"GitHub tiene {remotos} commits de otro equipo: se traen al cerrar (o `git pull --rebase`)"))
                if locales:
                    r.append((None, f"{locales} commits sin subir: se suben al cerrar con red"))
        except subprocess.TimeoutExpired:
            r.append((None, "sin red para comprobar GitHub"))
        return r
    except FileNotFoundError:
        return [(None, "git no esta instalado o no esta en el PATH: se practica igual, sin copia en GitHub")]


def informe_doctor(rapido=False):
    lineas, todo_ok = [], True
    for ok, mensaje in revisar(rapido):
        marca = {True: "OK ", False: "MAL", None: "OJO"}[ok]
        todo_ok &= ok is not False
        lineas.append(f"[{marca}] {mensaje}")
    lineas.append("Todo listo para practicar." if todo_ok else "Hay que arreglar lo marcado MAL antes de practicar.")
    return todo_ok, "\n".join(lineas)
