"""Registro de intentos: usuario/datos/registro.jsonl, una linea por intento, solo se anade.

Es la fuente de verdad. El estado de repaso se recalcula siempre desde aqui.
"""
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from .rutas import DATOS

RUTA = DATOS / "registro.jsonl"


def ahora():
    return datetime.now().astimezone().replace(microsecond=0)


CAMPOS = ("ts", "ficha", "nota")


class ErrorRegistro(ValueError):
    pass


def leer(ruta=None, estricto=False, crudo=False):
    """Intentos validos. Una linea danada (p. ej. un corte a mitad de escritura)
    se salta para que la sesion no se caiga; `doctor` la senala (estricto=True)."""
    ruta = Path(ruta or RUTA)
    if not ruta.exists():
        return []
    entradas = []
    with open(ruta, encoding="utf-8") as f:
        for n, linea in enumerate(f, 1):
            if not linea.strip():
                continue
            try:
                e = validar(linea)
            except ValueError as exc:
                if estricto:
                    raise ErrorRegistro(f"registro.jsonl linea {n}: {exc}") from exc
                continue
            entradas.append(e)
    return entradas if crudo else _aplicar_correcciones(entradas)


def validar(linea):
    """El intento de una linea del registro, o ValueError si esta danada."""
    e = json.loads(linea)   # JSONDecodeError es ValueError
    if not isinstance(e, dict) or not all(c in e for c in CAMPOS) or e["nota"] not in (1, 2, 3, 4):
        raise ValueError("faltan campos o nota fuera de 1-4")
    try:
        datetime.fromisoformat(e["ts"])
    except TypeError:
        raise ValueError("fecha (ts) ilegible") from None
    return e


CORRECCION = "correccion"


def _aplicar_correcciones(entradas):
    """Una entrada con motivo «correccion» (tutela.resolver) no es un intento: cambia
    la nota y el acierto del intento reclamado (`corrige` = su ts) y desaparece. Asi
    el intento sigue en su dia y FSRS, el dominio, la racha y los informes ven la
    nota buena sin contar un ejercicio de mas."""
    correcciones = {(e["ficha"], e.get("corrige")): e for e in entradas if e.get("motivo") == CORRECCION}
    if not correcciones:
        return entradas
    salida = []
    for e in entradas:
        if e.get("motivo") == CORRECCION:
            continue
        c = correcciones.get((e["ficha"], e["ts"]))
        if c is not None:
            e = {**e, "nota": c["nota"], "correcto": c.get("correcto", False), "corregido": c["ts"]}
        salida.append(e)
    return salida


def reclamado(ficha_id, semilla, ruta=None):
    """El ultimo intento reclamado de esa ficha y semilla (sin corregir), o None."""
    candidatos = [e for e in leer(ruta) if e["ficha"] == ficha_id and e.get("reclamo")
                  and (semilla is None or e.get("semilla") == semilla) and "corregido" not in e]
    return candidatos[-1] if candidatos else None


def correccion(original, aceptada, texto=""):
    """Entrada correctora de un intento reclamado: nota 3 si se acepta, 1 si no."""
    return {"ts": ahora().isoformat(), "ficha": original["ficha"], "semilla": original.get("semilla"),
            "tecnica": original.get("tecnica"), "motivo": CORRECCION, "corrige": original["ts"],
            "nota": 3 if aceptada else 1, "correcto": bool(aceptada), "texto": texto}


class YaExiste(ErrorRegistro):
    """`anadir(..., repetida=...)` encontro ya esa entrada en el registro."""


def inicio_proceso(pid):
    """Hora de creacion del proceso (para no confundirlo con otro que reuse el
    PID), 0 si existe pero no se sabe, o None si no existe."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return 0
        except PermissionError:
            return 0
        except OSError:
            return None
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return 0 if ctypes.GetLastError() == 5 else None   # 5: acceso denegado, pero existe
    try:
        codigo = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(h, ctypes.byref(codigo)) or codigo.value != 259:  # STILL_ACTIVE
            return None
        t = [ctypes.c_ulonglong() for _ in range(4)]
        if not k32.GetProcessTimes(h, *(ctypes.byref(x) for x in t)):
            return 0
        return t[0].value
    finally:
        k32.CloseHandle(h)


ESPERA_CERROJO = 10   # segundos: lo que se espera a un cerrojo y la edad a la que se da por abandonado
_PAUSA = 0.05


def _cerrojo_huerfano(marca):
    """True si el cerrojo es de un proceso que ya no existe (o del mismo PID con
    otra hora de inicio), o si tiene mas de ESPERA_CERROJO segundos."""
    try:
        if time.time() - marca.stat().st_mtime > ESPERA_CERROJO:
            return True
        dueno = json.loads(marca.read_text(encoding="utf-8") or "null")
    except (OSError, ValueError):   # recien creado (aun vacio) o borrandose: no es huerfano
        return False
    if not isinstance(dueno, dict) or not isinstance(dueno.get("pid"), int):
        return False
    inicio = inicio_proceso(dueno["pid"])
    return inicio is None or (inicio and dueno.get("inicio") and inicio != dueno["inicio"])


@contextmanager
def cerrojo(ruta):
    """Cerrojo de fichero junto a `ruta` (ruta.lock). Vale entre procesos y entre
    hilos: la terminal, la ventana y la linea de comandos pueden usar el registro a la vez.
    Guarda el PID: el cerrojo de un proceso que murio se rompe al momento."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    marca = ruta.with_name(ruta.name + ".lock")
    fin = time.monotonic() + ESPERA_CERROJO + 1
    while True:
        try:
            fd = os.open(marca, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):  # Windows: PermissionError si otro lo esta borrando
            try:
                if _cerrojo_huerfano(marca):
                    marca.unlink(missing_ok=True)
                    continue
            except OSError:  # ya no existe, o otro lo esta borrando
                pass
            if time.monotonic() > fin:
                raise ErrorRegistro(f"{ruta.name} ocupado por otro proceso; vuelve a intentarlo") from None
            time.sleep(_PAUSA)
    try:
        try:
            os.write(fd, json.dumps({"pid": os.getpid(), "inicio": inicio_proceso(os.getpid())}).encode())
        except OSError:
            pass
        yield
    finally:
        os.close(fd)
        _reintentar(lambda: marca.unlink(missing_ok=True))   # Windows: alguien lo esta leyendo


def _sin_salto_final(ruta):
    try:
        with open(ruta, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                return False
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except FileNotFoundError:
        return False


def anadir(entrada, ruta=None, repetida=None):
    """Anade una linea con un cerrojo de fichero: dos procesos pueden escribir a la
    vez sin mezclar lineas. Con `repetida(entradas)`,
    la comprobacion se hace dentro del mismo cerrojo y, si da True, lanza YaExiste
    sin escribir: dos registros simultaneos del mismo ejercicio dejan una sola linea."""
    ruta = Path(ruta or RUTA)
    linea = json.dumps(entrada, ensure_ascii=False) + "\n"
    with cerrojo(ruta):
        if repetida is not None and repetida(leer(ruta)):
            raise YaExiste(f"{entrada.get('ficha')} ya esta en el registro")
        if _sin_salto_final(ruta):
            linea = "\n" + linea   # la ultima linea quedo cortada: la nueva no se pega a ella
        _escribir_comprobado(ruta, linea)


INTENTOS_ESCRITURA = 2


def _escribir_comprobado(ruta, linea):
    """Anade `linea` (ya con su salto), la fuerza al disco y la relee. Si
    falla la escritura (disco lleno, permiso denegado) o al releer no esta, se deja
    el fichero como estaba (se recorta lo escrito a medias) y se reintenta una vez;
    si sigue mal, ErrorRegistro con un mensaje claro. Nunca queda media linea."""
    esperado = linea.strip()
    ultimo = None
    for intento in range(INTENTOS_ESCRITURA):
        try:
            antes = ruta.stat().st_size if ruta.exists() else 0
        except OSError as exc:
            ultimo, antes = exc, None
        try:
            with open(ruta, "a", encoding="utf-8") as f:
                f.write(linea)
                f.flush()
                os.fsync(f.fileno())
            with open(ruta, "rb") as f:
                f.seek(antes or 0)
                nuevo = f.read().decode("utf-8", errors="replace").strip()
            if nuevo and nuevo.splitlines()[-1].strip() == esperado:
                return
            ultimo = OSError("la linea no aparece al releer el fichero")
        except OSError as exc:
            ultimo = exc
        if antes is not None:   # lo escrito a medias se quita: el fichero queda como estaba
            try:
                if ruta.exists() and ruta.stat().st_size > antes:
                    os.truncate(ruta, antes)
            except OSError:
                pass
        if intento + 1 < INTENTOS_ESCRITURA:
            time.sleep(0.2)
    raise ErrorRegistro(f"no se ha podido guardar en {ruta.name} ({_explicar(ultimo)}). "
                        "Lo anterior sigue intacto; vuelve a intentarlo") from ultimo


def _explicar(exc):
    import errno
    if isinstance(exc, PermissionError):
        return "permiso denegado: el fichero esta bloqueado o es de solo lectura"
    if getattr(exc, "errno", None) == errno.ENOSPC or getattr(exc, "winerror", None) in (39, 112):
        return "el disco esta lleno"
    return str(exc) or type(exc).__name__


def _reintentar(accion, veces=40):
    """En Windows, un fichero abierto por otro hilo o proceso da PermissionError
    durante unos milisegundos (os.replace o lectura a la vez): se reintenta."""
    for n in range(veces):
        try:
            return accion()
        except PermissionError:
            if n == veces - 1:
                raise
            time.sleep(0.025)


def escribir_json(ruta, datos):
    """Escritura atomica (temporal + os.replace): quien lea a la vez ve el fichero
    viejo o el nuevo, nunca uno a medias."""
    ruta = Path(ruta)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    _reintentar(lambda: os.replace(temporal, ruta))


def leer_json(ruta, vacio=None):
    """Lee un JSON escrito con escribir_json; `vacio` si no existe."""
    ruta = Path(ruta)
    if not ruta.exists():
        return vacio
    return json.loads(_reintentar(lambda: ruta.read_text(encoding="utf-8")))


def fecha(entrada):
    """Fecha local (date) del intento."""
    return datetime.fromisoformat(entrada["ts"]).date()


MINIMO_DIA = 2  # el dia minimo: con 2 ejercicios el dia cuenta


def racha(entradas, dia):
    """(hecho_hoy, dias): dias seguidos con al menos MINIMO_DIA ejercicios.
    Un sabado o domingo sin practica no la rompe ni la suma. Si hoy aun no esta hecho, cuenta hasta ayer."""
    por_dia = {}
    for e in entradas:
        d = fecha(e)
        por_dia[d] = por_dia.get(d, 0) + 1
    hecho = por_dia.get(dia, 0) >= MINIMO_DIA
    if not por_dia:
        return hecho, 0
    primero = min(por_dia)
    d = dia if hecho else dia - timedelta(days=1)
    dias = 0
    while d >= primero:
        if por_dia.get(d, 0) >= MINIMO_DIA:
            dias += 1
        elif d.weekday() < 5:
            break
        d -= timedelta(days=1)
    return hecho, dias


def nota(correcto, pistas, confianza=None, segundos=None, mediana=None, fallos=0):
    """Nota FSRS (1-4) a partir de hechos (docs/DESIGN.md). Acertar tras algun
    intento fallido vale como mucho 2: si no, tantear hasta acertar puntuaria
    como saberlo a la primera."""
    if not correcto or pistas >= 4:
        return 1
    if pistas >= 2 or fallos >= 1:
        return 2
    rapido = segundos is not None and mediana is not None and segundos < mediana
    if pistas == 0 and rapido and (confianza or 0) >= 4:
        return 4
    return 3


def mediana_segundos(entradas, tecnica):
    tiempos = [e["segundos"] for e in entradas
               if e.get("tecnica") == tecnica and e.get("correcto") and e.get("segundos")]
    return median(tiempos) if len(tiempos) >= 3 else None
