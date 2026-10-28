"""Ventana de la sesion de hoy.

pywebview (WebView2 de Edge) sirve interfaz/index.html con su servidor http
interno y expone a JavaScript la clase `API`, que solo llama a servicio.Sesion
(seguro=True) y devuelve sus dicts. Si la ventana no se puede abrir, `abrir`
devuelve SIN_VENTANA (3) sin mostrar nada y Practicar.bat sigue en la terminal.

  python practica.py ventana [--minimo] [--prueba] [--captura RUTA]
"""
import ctypes
import functools
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
from datetime import date
from pathlib import Path

from . import datos, registro, servicio, tutela
from .doctor import version_webview2
from . import sesion as _sesion
from .huecos import HUECO, recortar
from .latex import enunciado_latex, trozos
from .lector import Lector
from .rutas import INTERFAZ

SIN_VENTANA = 3
TITULO = "Cálculo diario"
# ---------- Comprobaciones previas ----------

def tema_oscuro():
    """True si Windows usa el tema oscuro en las aplicaciones (fondo de la
    ventana antes de cargar la pagina; la pagina sigue prefers-color-scheme)."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


# ---------- Instancia unica: cerrojo con PID en .cache ----------

_inicio_proceso = registro.inicio_proceso   # el mismo que usan los cerrojos de fichero


def tomar_instancia(cache):
    """True si este proceso es la unica ventana; False si ya hay otra viva."""
    ruta = servicio.ruta_cache(cache, "ventana.pid")
    yo = {"pid": os.getpid(), "inicio": _inicio_proceso(os.getpid())}
    with registro.cerrojo(ruta):
        try:
            otro = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            otro = None
        if otro and otro.get("pid") != yo["pid"]:
            inicio = _inicio_proceso(int(otro.get("pid", 0)))
            if inicio is not None and inicio == otro.get("inicio"):
                return False
        registro.escribir_json(ruta, yo)
    return True


def _al_frente(titulo=TITULO):
    """Con pythonw no hay consola para decir «ya hay una ventana»: se trae
    la que esta abierta al frente. True si se encontro."""
    if sys.platform != "win32":
        return False
    u32 = ctypes.WinDLL("user32")
    hwnd = u32.FindWindowW(None, titulo)
    if not hwnd:
        return False
    u32.ShowWindow(hwnd, 9)   # SW_RESTORE
    u32.SetForegroundWindow(hwnd)
    return True


def dialogo(texto, pregunta=False):
    """Cuadro de mensaje de Windows: avisos de datos antes de abrir la
    ventana, sin consola. Con pregunta=True, Si/No -> bool."""
    if sys.platform != "win32":
        return False
    banderas = 0x40000 | 0x10000 | (0x4 | 0x30 if pregunta else 0x40)   # encima, delante; Si/No o informacion
    return ctypes.WinDLL("user32").MessageBoxW(None, str(texto), TITULO, banderas) == 6   # IDYES


def soltar_instancia(cache):
    ruta = Path(cache) / "ventana.pid"
    try:
        if json.loads(ruta.read_text(encoding="utf-8")).get("pid") == os.getpid():
            ruta.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


# ---------- Datos de prueba (humo): nunca usuario/datos ----------

def datos_temporales(carpeta):
    """Redirige registro, diario, notas, revisiones y .cache a `carpeta`.
    Devuelve la .cache. Solo para `--prueba`."""
    carpeta = Path(carpeta)
    registro.RUTA = carpeta / "registro.jsonl"
    _sesion.DIARIO = carpeta / "diario.md"
    _sesion.SIMULACROS = carpeta / "simulacros"
    tutela.NOTAS = carpeta / "notas.jsonl"
    tutela.REVISIONES = carpeta / "revisiones"
    servicio.CACHE = carpeta / ".cache"
    return servicio.CACHE


# ---------- La API que ve JavaScript ----------

def _log(cache, texto):
    try:
        ruta = servicio.ruta_cache(cache, "servicio.log")
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"--- {registro.ahora().isoformat()} ventana: {texto}\n")
    except OSError:
        pass


def _envuelto(metodo):
    """Cada metodo devuelve un dict con `ok`; una excepcion o un ok:false quedan
    en .cache/servicio.log (condicion 7). La vista previa no anota sus errores
    de lectura: son lo normal mientras se escribe."""
    @functools.wraps(metodo)
    def envuelto(self, *args):
        try:
            r = metodo(self, *args)
        except Exception as exc:
            servicio._al_log(self._cache, f"ventana.{metodo.__name__}", args, exc)
            return {"ok": False, "error": str(exc) or type(exc).__name__}
        if isinstance(r, dict) and r.get("ok") is False and not r.get("_lectura"):
            _log(self._cache, f"{metodo.__name__}{args!r} -> {r.get('error') or r.get('mensaje')}")
        if isinstance(r, dict):
            r.pop("_lectura", None)
        return r
    return envuelto


def _partes_enunciado(texto):
    """Lo que el LaTeX del enunciado no lleva: la entrada («Ecuacion
    caracteristica:») y la instruccion final («Escribe ∂M/∂y, ∂N/∂x»)."""
    m = re.match(r"^([^:=()\[\]]{3,40}:)\s", texto)
    antes = m.group(1) if m else ""
    despues = texto.split(".  ", 1)[1].strip() if ".  " in texto else ""
    return antes, despues


class API:
    """Puente fino entre interfaz/app.js y servicio.Sesion. Todo lo que guarda
    son atributos privados (pywebview solo expone los metodos publicos)."""

    def __init__(self, sesion=None, cache=None, git=True, minimo=False, lector=None):
        self._cache = Path(cache) if cache is not None else servicio.CACHE
        self._s = sesion or servicio.Sesion(cache=self._cache, seguro=True)
        self._git = git
        self._minimo = minimo
        self._lector = lector if lector is not None else Lector(self._cache)
        self._ventana = None
        self._subida = None
        self._hilo_subida = None
        self._dias = {self._s.hoy()}
        self._cerrojo = threading.Lock()

    # --- arranque ---

    @_envuelto
    def inicio(self):
        """Datos fijos de la sesion y, si toca, la revision semanal (como `hoy`)."""
        dia = self._s.hoy()
        lineas = []
        if tutela.toca_revision(dia, registro.leer()):
            texto = tutela.revision(dia, self._s.fichas)
            reco = texto.split("## 6. Recomendaciones (automaticas)")[1].split("##")[0]
            lineas = [x[2:] for x in reco.splitlines() if x.startswith("- ")][:3]
        causas = [{"clave": k, "texto": v} for k, v in tutela.CAUSAS.items() if k != "5"]
        return {"ok": True, "dia": dia.isoformat(), "revision": lineas, "causas": causas,
                "limite": servicio.LIMITE_LECTURA, "prueba": not self._git, "minimo": self._minimo}

    @_envuelto
    def cola(self):
        from .ver import argumentos
        r = self._s.cola(self._minimo)
        if not r.get("ok"):
            return r
        for e in r["ejercicios"]:
            v = self._s.fichas[e["ficha"]].variante(e["semilla"])
            try:
                e["grafica"] = argumentos(v) is not None
            except Exception:
                e["grafica"] = False
            e["enunciado_antes"], e["enunciado_despues"] = _partes_enunciado(e["enunciado"])
            self._enunciado_trozos(e)
            if e.get("ejemplo"):
                self._ejemplo_trozos(e["ejemplo"])
        return r

    @_envuelto
    def minimo(self):
        """«Hoy solo 2»: el dia minimo, como `ventana --minimo`."""
        self._minimo = True
        return self.cola.__wrapped__(self)

    # --- un ejercicio ---

    @_envuelto
    def mostrar(self, ficha, semilla):
        return self._s.mostrar(ficha, semilla)

    @_envuelto
    def leer(self, texto, ficha, semilla):
        """Vista previa neutra, en el proceso lector (tope de tiempo real)."""
        texto = str(texto)[:servicio.LIMITE_LECTURA + 1]
        r = self._lector.leer(texto, ficha, semilla)
        r["_lectura"] = "leido" in r
        return r

    @_envuelto
    def comprobar(self, ficha, semilla, respuesta):
        respuesta = str(respuesta)
        if len(respuesta) > servicio.LIMITE_LECTURA:
            return {"ok": True, "correcto": False, "error": f"es demasiado larga (más de "
                    f"{servicio.LIMITE_LECTURA} caracteres)", "leido": None, "avisos": [], "diagnostico": []}
        previa = self._lector.leer(respuesta, ficha, semilla)
        if previa.get("tope"):  # 9**9**9**9 colgaria el motor: no se corrige ni cuenta
            return {"ok": True, "correcto": False, "error": previa["error"], "leido": None, "avisos": [],
                    "diagnostico": []}
        r = self._s.comprobar(ficha, semilla, respuesta)
        if r.get("ok"):
            r["diagnostico_trozos"] = [self._trozos(ficha, d) for d in r.get("diagnostico") or []]
            r["leido_trozos"] = self._trozos(ficha, r["leido"]) if r.get("leido") else None
            r["avisos_trozos"] = [self._trozos(ficha, a) for a in r.get("avisos") or []]
        return r

    def _trozos(self, ficha, texto):
        """Texto del motor en trozos de texto y de formula (KaTeX en la ventana).
        El conversor no depende de la ficha (`ficha` se conserva por las llamadas)."""
        try:
            return trozos(texto)
        except Exception:
            return [{"texto": str(texto)}]

    def _enunciado_trozos(self, e):
        """Todo lo que se ensena del enunciado, en trozos. Con `enunciado_latex`,
        la entrada y la instruccion final; sin el (algebra, EDOs, calculos), el enunciado entero."""
        e["enunciado_antes_trozos"] = self._trozos(None, e.get("enunciado_antes") or "")
        e["enunciado_despues_trozos"] = self._trozos(None, e.get("enunciado_despues") or "")
        e["enunciado_trozos"] = None if e.get("enunciado_latex") else self._trozos(None, e.get("enunciado", ""))
        e["como_responder_trozos"] = self._trozos(None, e.get("como_responder") or "")
        return e

    def _ejemplo_trozos(self, ej):
        """El ejemplo resuelto en trozos: idea y pasos (visibles y ocultos) desde
        las formulas marcadas con $...$ de fichas/ejemplos.toml; enunciado y resultado,
        como los del ejercicio. Sin marcas (o si no cuadran los pasos), el texto plano."""
        try:
            cargado = self._s.ejemplo_cargado(ej.get("tecnica"))
        except Exception:
            cargado = None
        marcado = (cargado or {}).get("marcado") or {}
        todos = marcado.get("pasos")
        ocultos_planos = ej.get("pasos_ocultos") or []
        if todos and len(todos) == len(ej.get("pasos") or []):
            visibles, ocultos = recortar(todos, len(ocultos_planos))
        else:
            visibles, ocultos = ej.get("pasos") or [], ocultos_planos
        ej["idea_trozos"] = self._trozos(None, marcado.get("idea", ej.get("idea", "")))
        ej["pasos_trozos"] = [[{"texto": HUECO}] if p == HUECO else self._trozos(None, p) for p in visibles]
        ej["ocultos_trozos"] = [self._trozos(None, p) for p in ocultos]
        ej["resultado_trozos"] = self._trozos(None, ej.get("resultado", ""))
        try:
            tex = enunciado_latex(cargado["variante"]) if cargado else None
        except Exception:
            tex = None
        ej["enunciado_latex"] = tex
        ej["enunciado_antes"], ej["enunciado_despues"] = _partes_enunciado(ej.get("enunciado", ""))
        return self._enunciado_trozos(ej)

    @_envuelto
    def pista(self, ficha, semilla, nivel):
        nivel = int(nivel)
        if not 1 <= nivel <= 3:
            raise ValueError("en la ventana las pistas van de 1 a 3; despues, la solución")
        r = self._s.pista(ficha, semilla, nivel)
        if r.get("ok"):
            r["trozos"] = self._trozos(ficha, r["texto"])
        return r

    @_envuelto
    def solucion(self, ficha, semilla):
        """Solo si ya toca (tras la pista 2 o un fallo): la ventana no la ofrece antes."""
        d = self._s.ejercicio(ficha, semilla)
        if not d.get("ok"):
            return d
        if not d["solucion_disponible"]:
            return {"ok": False, "error": "La solución aparece después de la pista 2 o de un intento."}
        r = self._s.solucion(ficha, semilla)
        if r.get("ok"):
            r["trozos"] = self._trozos(ficha, r["texto"])
        return r

    @_envuelto
    def sin_saber_empezar(self, ficha, semilla):
        r = self._s.sin_saber_empezar(ficha, semilla)
        if r.get("ok"):
            r["pistas_trozos"] = [self._trozos(ficha, x) for x in r.get("pistas") or []]
            if r.get("ejemplo"):
                self._ejemplo_trozos(r["ejemplo"])
        return r

    @_envuelto
    def practicar(self, ficha, semilla, respuesta):
        return self._s.practicar(ficha, semilla, str(respuesta)[:servicio.LIMITE_LECTURA])

    @_envuelto
    def causa_necesaria(self, ficha, semilla, rendido=False, reclamo=False):
        return self._s.causa_necesaria(ficha, semilla, rendido=bool(rendido), reclamo=bool(reclamo))

    @_envuelto
    def registrar(self, ficha, semilla, confianza, respuesta=None, rendido=False, causa=None, reclamo=False):
        with self._cerrojo:
            self._dias.add(self._s.hoy())
            r = self._s.registrar(ficha, semilla, confianza, respuesta or None, bool(rendido), causa or None,
                                  bool(reclamo))
        if r.get("ok") and r.get("proximo"):
            r["proximo_texto"] = date.fromisoformat(r["proximo"]).strftime("%d/%m")
        r.pop("entrada", None)
        return r

    @_envuelto
    def comprobar_ejemplo(self, tecnica, respuesta):
        return self._s.comprobar_ejemplo(tecnica, str(respuesta)[:servicio.LIMITE_LECTURA])

    @_envuelto
    def ver(self, ficha, semilla):
        """La grafica con math-plotter, en otro proceso (CREATE_NO_WINDOW)."""
        from .ver import ver_ficha
        v = self._s.fichas[ficha].variante(int(semilla))
        return {"ok": True, "mensaje": ver_ficha(v)}

    # --- final ---

    @_envuelto
    def sensacion(self, valor, texto=""):
        return self._s.sensacion(valor, texto or "")

    @_envuelto
    def queja(self, texto):
        return self._s.queja(texto)

    def _hay_registros(self):
        return any(registro.fecha(e) in self._dias | {self._s.hoy()} for e in registro.leer())

    @_envuelto
    def terminar(self):
        """El diario al momento (cerrar_local) y git en un hilo con tope."""
        self._dias.add(self._s.hoy())
        mensajes, n = [], 0
        for d in sorted(self._dias):
            r = self._s.cerrar_local(d)
            if not r.get("ok"):
                return r
            n += r["ejercicios"]
            if r["ejercicios"] or d == self._s.hoy():
                mensajes.append(r["mensaje"])
        self._empezar_subida(n)
        return {"ok": True, "ejercicios": n, "mensaje": "\n\n".join(mensajes), "subida": self._subida}

    def _empezar_subida(self, n):
        with self._cerrojo:
            if self._hilo_subida is not None:
                return
            if not self._git:
                self._subida = {"estado": "local", "mensaje": "Modo prueba: no se sube nada."}
                return
            if not n:
                self._subida = {"estado": "nada", "mensaje": "Hoy no hay ejercicios que subir."}
                return
            self._subida = {"estado": "subiendo", "mensaje": "Subiendo a GitHub…"}

            def subir():
                r = self._s.sincronizar(timeout=60)
                mensaje = r.get("mensaje") or r.get("error", "")
                if r.get("ok"):
                    estado = "subido"
                elif "Sin red" in mensaje or "se agoto el tiempo" in mensaje:
                    estado = "sin_red"
                else:   # un choque con otro equipo o un fallo de git: se revisa a mano, sin alarma
                    estado = "revisar"
                self._subida = {"estado": estado, "mensaje": mensaje}
                if not r.get("ok"):
                    _log(self._cache, f"sincronizar -> {self._subida['mensaje']}")
            self._hilo_subida = threading.Thread(target=subir, name="subida")
            self._hilo_subida.start()

    @_envuelto
    def preparar_salida(self):
        """Antes de cerrar con el boton o Esc: si hay algo registrado y aun no se
        ha subido, se escribe el diario y se empieza la subida, para que la ventana
        ensene como acaba («Sin red: se sube la próxima vez») en vez de una consola."""
        if self._hilo_subida is None and self._hay_registros():
            self._dias.add(self._s.hoy())
            n = 0
            for d in sorted(self._dias):
                r = self._s.cerrar_local(d)
                n += r.get("ejercicios", 0) if r.get("ok") else 0
            self._empezar_subida(n)
        return {"ok": True, **(self._subida or {"estado": "nada", "mensaje": ""})}

    @_envuelto
    def estado_subida(self):
        return {"ok": True, **(self._subida or {"estado": "pendiente", "mensaje": ""})}

    @_envuelto
    def salir(self):
        if self._ventana is not None:
            threading.Timer(0.05, self._ventana.destroy).start()
        return {"ok": True}

    @_envuelto
    def anotar_error(self, texto):
        """Errores de JavaScript: al log, nunca tragados."""
        _log(self._cache, f"js: {str(texto)[:2000]}")
        return {"ok": True}

    def al_cerrar(self):
        """Evento closing y salida: lo registrado ya esta en disco; se reescribe
        el bloque del diario si hubo algun registro (cerrar_local es idempotente)."""
        try:
            if self._hay_registros():
                self._dias.add(self._s.hoy())
                for d in sorted(self._dias):
                    self._s.cerrar_local(d)
                return True
        except Exception as exc:
            servicio._al_log(self._cache, "ventana.al_cerrar", (), exc)
        return False

    def despues(self, tope=70):
        """Tras cerrar la ventana: esperar la subida en marcha o, si se cerro a
        mitad con registros, subir ahora (con tope). Devuelve el mensaje."""
        self._lector.cerrar()
        if self._hilo_subida is not None:
            self._hilo_subida.join(tope)
            return (self._subida or {}).get("mensaje", "")
        if self._git and self._hay_registros():
            r = self._s.sincronizar(timeout=30)
            return r.get("mensaje") or r.get("error", "")
        return ""


# ---------- Abrir la ventana ----------

def _captura(titulo, ruta):
    """PNG de la ventana (PrintWindow con PW_RENDERFULLCONTENT): solo el humo."""
    import struct
    import zlib
    from ctypes import wintypes
    u32, g32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")  # propias: no tocar las de pywebview
    H, DC, BM, OBJ = wintypes.HWND, wintypes.HDC, wintypes.HBITMAP, wintypes.HGDIOBJ
    for f, args, res in ((u32.FindWindowW, [wintypes.LPCWSTR, wintypes.LPCWSTR], H),
                         (u32.GetWindowRect, [H, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
                         (u32.GetWindowDC, [H], DC), (u32.ReleaseDC, [H, DC], ctypes.c_int),
                         (u32.PrintWindow, [H, DC, wintypes.UINT], wintypes.BOOL),
                         (g32.CreateCompatibleDC, [DC], DC),
                         (g32.CreateCompatibleBitmap, [DC, ctypes.c_int, ctypes.c_int], BM),
                         (g32.SelectObject, [DC, OBJ], OBJ), (g32.DeleteObject, [OBJ], wintypes.BOOL),
                         (g32.DeleteDC, [DC], wintypes.BOOL),
                         (g32.GetDIBits, [DC, BM, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                                          wintypes.UINT], ctypes.c_int)):
        f.argtypes, f.restype = args, res
    hwnd = u32.FindWindowW(None, titulo)
    if not hwnd:
        return False
    rect = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    an, al = rect.right - rect.left, rect.bottom - rect.top
    hdc = u32.GetWindowDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, an, al)
    g32.SelectObject(mem, bmp)
    u32.PrintWindow(hwnd, mem, 2)

    class Cabecera(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    cab = Cabecera(ctypes.sizeof(Cabecera), an, -al, 1, 32, 0, 0, 0, 0, 0, 0)
    datos = ctypes.create_string_buffer(an * al * 4)
    g32.GetDIBits(mem, bmp, 0, al, datos, ctypes.byref(cab), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)
    crudo = datos.raw
    filas = b"".join(b"\x00" + bytes(_bgra_a_rgb(crudo[y * an * 4:(y + 1) * an * 4])) for y in range(al))

    def bloque(tipo, contenido):
        return (struct.pack(">I", len(contenido)) + tipo + contenido
                + struct.pack(">I", zlib.crc32(tipo + contenido) & 0xffffffff))
    png = (b"\x89PNG\r\n\x1a\n" + bloque(b"IHDR", struct.pack(">IIBBBBB", an, al, 8, 2, 0, 0, 0))
           + bloque(b"IDAT", zlib.compress(filas, 9)) + bloque(b"IEND", b""))
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta).write_bytes(png)
    return True


def _bgra_a_rgb(fila):
    salida = bytearray(len(fila) // 4 * 3)
    salida[0::3], salida[1::3], salida[2::3] = fila[2::4], fila[1::4], fila[0::4]
    return salida


def _resto_prueba(js, esperar, resultado, api=None):
    """El resto de la cola sin acertar: «No se por donde empezar» (ejemplo y vuelta),
    un fallo («Estaba bien» y Solucion aparecen), una pista, la solucion con su
    confirmacion, la causa, reescribirla de memoria y, al final, sensacion y cierre."""
    fase = "document.body.dataset.fase"
    vistos = {}
    while True:
        js("document.getElementById('siguiente').click()")
        esperar(f"['ejemplo', 'confianza', 'final'].includes({fase})")
        if js(fase) == "final":
            break
        if js(fase) == "ejemplo":
            js("document.getElementById('ejemplo-seguir').click()")
            if js(fase) == "ejemplo":
                js("document.getElementById('ejemplo-seguir').click()")
            esperar(f"{fase} === 'confianza'")
        oculta = js("document.getElementById('ver-solucion').hidden")
        js("document.querySelector('[data-confianza=\"2\"]').click()")
        esperar(f"{fase} === 'respuesta'")
        vistos.setdefault("solucion_oculta_al_empezar", oculta)
        actual = json.loads(js("JSON.stringify(window.estadoPrueba())"))
        if not js("document.getElementById('no-se').hidden"):
            js("document.getElementById('no-se').click()")
            esperar(f"{fase} === 'ejemplo' || document.querySelectorAll('#pistas li').length >= 2")
            if js(fase) == "ejemplo":
                js("document.getElementById('ejemplo-seguir').click()")
            esperar(f"{fase} === 'respuesta'")
            vistos.setdefault("no_se_vuelve_al_ejercicio", (
                json.loads(js("JSON.stringify(window.estadoPrueba())"))["ficha"] == actual["ficha"]
                and not js("document.getElementById('ver-solucion').hidden")))
        for mala in ("0", "0, 0"):
            js(f"window.escribirPrueba({json.dumps(mala)})")
            js("document.getElementById('comprobar').click()")
            esperar("document.getElementById('mensaje').textContent !== ''")
            if "No cuadra" in js("document.getElementById('mensaje').textContent"):
                break
            js("document.getElementById('mensaje').textContent = ''")
        vistos.setdefault("fallo_ensena", (not js("document.getElementById('estaba-bien').hidden")
                                           and not js("document.getElementById('ver-solucion').hidden")))
        antes = js("document.querySelectorAll('#pistas li').length")
        js("document.getElementById('pista').click()")
        esperar(f"document.querySelectorAll('#pistas li').length === {antes + 1}")
        js("document.getElementById('ver-solucion').click()")
        esperar("!document.getElementById('confirmar-solucion').hidden")
        vistos.setdefault("solucion_pide_confirmacion", js(fase) == "respuesta")
        js("document.getElementById('solucion-si').click()")
        esperar(f"{fase} === 'causa'")
        vistos.setdefault("solucion_con_katex", bool(js("!!document.querySelector('#solucion-texto .katex')"))
                          or "Solucion" in (js("document.getElementById('solucion-texto').textContent") or ""))
        js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '1', bubbles: true}))")
        esperar(f"{fase} === 'hecho'")
        if api is not None and not js("document.getElementById('bloque-memoria').hidden"):
            v = api._s.fichas[actual["ficha"]].variante(actual["semilla"])
            js("document.getElementById('reescribir').click()")
            js(f"document.getElementById('memoria').value = {json.dumps(v.respuesta_modelo)}")
            js("document.getElementById('memoria-comprobar').click()")
            esperar("document.getElementById('memoria-mensaje').textContent !== ''")
            vistos.setdefault("memoria_sin_nota", "Bien" in js("document.getElementById('memoria-mensaje').textContent"))
    js("document.querySelector('[data-sensacion=\"4\"]').click()")
    js("document.getElementById('comentario').value = 'humo de la ventana'")
    js("document.getElementById('terminar').click()")
    esperar(f"{fase} === 'resumen'")
    esperar("document.getElementById('estado-subida').textContent !== ''")
    resultado["resumen"] = js("document.getElementById('resumen').textContent")
    resultado["subida"] = js("document.getElementById('estado-subida').textContent")
    resultado["comprobado"] = vistos
    entradas = registro.leer()
    resultado["registro"] = [(e["ficha"], e["nota"], e.get("fallos"), e.get("pistas"), e.get("causa"))
                             for e in entradas]
    notas = tutela.leer_notas()
    return (all(vistos.values()) and len(vistos) == 6 and len(entradas) >= 2
            and all(e["nota"] == 1 for e in entradas[1:]) and any(n.get("tipo") == "sensacion" for n in notas)
            and _sesion.DIARIO.exists() and "prueba" in resultado["subida"])


def _recorrido_prueba(ventana, api, resultado, captura=None, completa=True):
    """Humo real: cola -> (ejemplo) -> confianza -> respuesta correcta de la
    primera ficha -> registrar, por evaluate_js sobre la interfaz de verdad."""
    t0 = time.monotonic()
    tiempos = resultado["tiempos"]

    def js(codigo):
        return ventana.evaluate_js(codigo)

    def esperar(condicion, tope=30):
        fin = time.monotonic() + tope
        while time.monotonic() < fin:
            try:
                if js(condicion):
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        raise TimeoutError(f"no se cumplio: {condicion}")

    try:
        esperar("document.body.dataset.fase === 'ejemplo' || document.body.dataset.fase === 'confianza'")
        tiempos["interfaz_lista"] = round(time.monotonic() - t0, 2)
        # «Hoy solo 2»: la cola minima del motor (y el humo va mas rapido).
        resultado["solo_dos"] = not js("document.getElementById('solo-dos').hidden")
        if resultado["solo_dos"]:
            js("document.getElementById('solo-dos').click()")
            esperar("document.getElementById('progreso-texto').textContent.endsWith(' de 2')")
            esperar("document.body.dataset.fase === 'ejemplo' || document.body.dataset.fase === 'confianza'")
        if js("document.body.dataset.fase") == "ejemplo":
            js("document.getElementById('ejemplo-seguir').click()")
            esperar("document.body.dataset.fase === 'confianza'")
        actual = json.loads(js("JSON.stringify(window.estadoPrueba())"))
        v = api._s.fichas[actual["ficha"]].variante(actual["semilla"])
        tiempos["enunciado_katex"] = bool(js("!!document.querySelector('#enunciado .katex')"))
        js("document.querySelector('[data-confianza=\"4\"]').click()")
        esperar("document.body.dataset.fase === 'respuesta'")
        js(f"window.escribirPrueba({json.dumps(v.respuesta_modelo)})")
        t1 = time.monotonic()
        esperar("document.getElementById('vista-previa').dataset.estado === 'leido'")
        tiempos["vista_previa"] = round(time.monotonic() - t1, 2)
        if captura:
            time.sleep(0.3)
            resultado["captura"] = _captura(ventana.title, captura)
        t1 = time.monotonic()
        js("document.getElementById('comprobar').click()")
        esperar("document.body.dataset.fase === 'hecho'")
        tiempos["comprobar_registrar"] = round(time.monotonic() - t1, 2)
        resultado["texto_final"] = js("document.getElementById('mensaje-hecho').textContent")
        resultado["barra"] = js("document.getElementById('barra-relleno').style.width")
        primera = registro.leer()
        resultado["primera"] = [(e["ficha"], e["semilla"], e["nota"]) for e in primera]
        bien = (len(primera) == 1 and primera[0]["ficha"] == actual["ficha"] and primera[0]["nota"] == 3
                and "Próximo repaso" in resultado["texto_final"] and resultado["solo_dos"]
                and resultado["barra"] == "50%")
        if completa:
            bien &= _resto_prueba(js, esperar, resultado, api)
        resultado["csp"] = json.loads(js("JSON.stringify(window.estadoPrueba())"))["violaciones"]
        resultado["ok"] = bien and not resultado["csp"]
    except Exception as exc:
        resultado["error"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    finally:
        tiempos["total"] = round(time.monotonic() - t0, 2)
        ventana.destroy()


def abrir(minimo=False, prueba=False, captura=None, salida=print):
    """Abre la ventana. Devuelve el codigo de salida: 0 bien (o ya habia una
    ventana abierta), 1 humo fallido, SIN_VENTANA si no se pudo abrir."""
    t0 = time.monotonic()
    try:
        import webview
    except Exception as exc:  # ImportError o una dependencia rota
        salida(f"No se puede abrir la ventana ({type(exc).__name__}: {exc}). Sigo en la terminal.")
        return SIN_VENTANA
    if sys.platform == "win32" and version_webview2() is None:
        salida("Falta WebView2 (el motor de Edge para ventanas). Sigo en la terminal.")
        return SIN_VENTANA
    if not (INTERFAZ / "index.html").exists() or not (INTERFAZ / "katex" / "katex.min.js").exists():
        salida("Falta la carpeta interfaz/ (o KaTeX). Sigo en la terminal.")
        return SIN_VENTANA

    temporal = None
    if prueba:
        temporal = Path(tempfile.mkdtemp(prefix="calculo-ventana-"))
        cache = datos_temporales(temporal)
    else:
        cache = servicio.CACHE
    if not tomar_instancia(cache):
        salida("Ya hay una ventana de práctica abierta: sigue en ella.")
        if not prueba:
            _al_frente()
        return 0
    # Revision y copia de los datos antes de empezar (calculo/datos.py).
    if prueba:
        resultado_datos = datos.al_arrancar(preguntar=lambda _: False, git=False, cache=cache)
    else:
        avisos = datos.al_arrancar(preguntar=lambda t: dialogo(t, pregunta=True), cache=cache)
        if avisos:
            dialogo("Tus datos:\n\n" + "\n\n".join(avisos))
    api = API(cache=cache, git=not prueba, minimo=minimo)
    threading.Thread(target=api._lector.preparar, daemon=True).start()
    resultado = {"ok": False, "tiempos": {}}
    if prueba:
        resultado["avisos_datos"] = resultado_datos
    mostrada = threading.Event()
    try:
        titulo = TITULO + (f" (prueba {os.getpid()})" if prueba else "")
        # Sin text_select, pywebview mete un <style> en linea que la CSP bloquea.
        ventana = webview.create_window(titulo, url=str(INTERFAZ / "index.html"), js_api=api, width=980,
                                        height=820, min_size=(560, 560), text_select=True,
                                        background_color="#1B1D21" if tema_oscuro() else "#F7F6F2")
        api._ventana = ventana
        ventana.events.shown += lambda: mostrada.set()
        ventana.events.closing += lambda: (api.al_cerrar(), None)[1]
        if prueba:
            def humo():
                ventana.events.loaded.wait(60)
                resultado["tiempos"]["abrir"] = round(time.monotonic() - t0, 2)
                _recorrido_prueba(ventana, api, resultado, captura)
            webview.start(humo, gui="edgechromium", http_server=True, private_mode=True)
        else:
            webview.start(gui="edgechromium", http_server=True, private_mode=True)
    except Exception as exc:
        servicio._al_log(cache, "ventana.abrir", (), exc)
        if not mostrada.is_set():
            salida(f"No se pudo abrir la ventana ({type(exc).__name__}: {exc}). Sigo en la terminal.")
            soltar_instancia(cache)
            api._lector.cerrar()
            return SIN_VENTANA
        salida(f"La ventana se cerró por un error ({exc}). Lo registrado está guardado; sigo en la terminal.")
        api.al_cerrar()
        api.despues()
        datos.al_cerrar(cache=cache)
        soltar_instancia(cache)
        return SIN_VENTANA
    finally:
        api.al_cerrar()
    if not mostrada.is_set() and not prueba:
        soltar_instancia(cache)
        api._lector.cerrar()
        salida("La ventana no llegó a abrirse. Sigo en la terminal.")
        return SIN_VENTANA
    mensaje = api.despues()
    copia = datos.al_cerrar(cache=cache)   # copia verificada al cerrar
    if prueba:
        resultado["copia_al_cerrar"] = bool(copia.get("hecha"))
    soltar_instancia(cache)
    if mensaje:
        salida(mensaje)
    if prueba:
        resultado["mostrada"] = mostrada.is_set()   # sin el evento shown, la ventana real volveria a la terminal
        bien = resultado["ok"] and resultado["mostrada"] and resultado.get("copia_al_cerrar")
        if bien:   # si sale bien no se deja basura en %TEMP%; si falla, se queda para mirarla
            shutil.rmtree(temporal, ignore_errors=True)
        salida(json.dumps({**resultado, "carpeta": str(temporal) + ("" if bien else " (se conserva)"),
                           "carpeta_borrada": not temporal.exists()}, ensure_ascii=False, indent=1))
        return 0 if bien else 1
    return 0
