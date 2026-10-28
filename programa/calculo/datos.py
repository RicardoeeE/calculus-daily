"""Proteccion de los datos: copias verificadas, revision al
arrancar, lineas danadas apartadas y recuperacion desde la copia.

Los datos son los *.jsonl de usuario/datos (registro, notas, progreso y los
apartados). Solo se anaden lineas: por eso «perder datos» es que una linea que
estaba en la ultima copia ya no este, y «recuperar» es juntar (union de lineas),
nunca borrar.

  - Copias: al arrancar y al cerrar, solo si algo cambio, en
    %LOCALAPPDATA%\\calculo-diario\\copias\\AAAA-MM-DD\\ (fuera del repo), con un
    manifiesto SHA256 que se comprueba tras copiar. Se guardan 30 dias y, de lo
    anterior, la ultima de cada mes. Si faltan lineas respecto a la ultima copia,
    no se hace otra (la buena no se pisa ni se queda vieja sin avisar).
  - Al arrancar: las lineas ilegibles se apartan a apartado-AAAA-MM-DD.jsonl (no
    se borran) y, si faltan lineas de la ultima copia, se avisa y se ofrece
    recuperarlas (antes se copia la version actual).
  - `resumen()` es la seccion «datos» de doctor y la orden `practica.py datos`.

En las pruebas los datos estan en una carpeta temporal y las copias van a
<carpeta>/.copias (o a CALCULO_DIARIO_COPIAS): nunca a las de verdad.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import registro
from .rutas import CACHE, DATOS, RAIZ

ENTORNO = "CALCULO_DIARIO_COPIAS"
DIAS_COPIAS = 30
ANTES_DE_RECUPERAR = "antes de recuperar"
DIAS_SIN_SUBIR = 2
_NOMBRE_COPIA = re.compile(r"^\d{4}-\d{2}-\d{2}(_\d{6})?$")
_SIN_VENTANA = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


# ---------- Donde estan las cosas ----------

def carpeta_datos(ruta_registro=None):
    return Path(ruta_registro or registro.RUTA).resolve().parent


def carpeta_copias(datos=None):
    """%LOCALAPPDATA%\\calculo-diario\\copias (o CALCULO_DIARIO_COPIAS) para los
    datos de verdad; en las pruebas (otra carpeta de datos), <datos>/.copias."""
    datos = Path(datos or carpeta_datos())
    if datos.resolve() != DATOS.resolve():
        return datos / ".copias"
    if os.environ.get(ENTORNO):
        return Path(os.environ[ENTORNO])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "calculo-diario" / "copias"


def ficheros(datos=None):
    datos = Path(datos or carpeta_datos())
    return sorted(p for p in datos.glob("*.jsonl") if p.is_file())


def _apartados(datos):
    return sorted(Path(datos).glob("apartado-*.jsonl"))


def _sha(datos_bytes):
    return hashlib.sha256(datos_bytes).hexdigest()


def _lineas(texto):
    return [x.strip() for x in texto.splitlines() if x.strip()]


def _leer_bytes(ruta):
    """El contenido entero, dentro del cerrojo del fichero: no se copia media linea."""
    with registro.cerrojo(ruta):
        return registro._reintentar(lambda: Path(ruta).read_bytes())


# ---------- Copias ----------

def copias(datos=None):
    """Manifiestos de las copias de esta carpeta de datos, de la mas vieja a la mas nueva."""
    datos = Path(datos or carpeta_datos())
    raiz = carpeta_copias(datos)
    salida = []
    if not raiz.is_dir():
        return salida
    for c in raiz.iterdir():
        if not (c.is_dir() and _NOMBRE_COPIA.match(c.name)):
            continue
        try:
            m = json.loads((c / "manifiesto.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if m.get("origen") != str(datos.resolve()):
            continue
        salida.append({**m, "carpeta": c})
    return sorted(salida, key=lambda m: (m.get("ts", ""), m["carpeta"].name))


def ultima_copia(datos=None):
    """La copia de referencia: la mas nueva que no sea la de «antes de recuperar»."""
    buenas = [m for m in copias(datos) if m.get("motivo") != ANTES_DE_RECUPERAR]
    return buenas[-1] if buenas else None


def verificar_copia(m):
    """True si cada fichero de la copia tiene el SHA256 de su manifiesto."""
    try:
        return all(_sha((m["carpeta"] / n).read_bytes()) == d["sha256"] for n, d in m["ficheros"].items())
    except (OSError, KeyError):
        return False


def _contenido_actual(datos):
    return {p.name: _leer_bytes(p) for p in ficheros(datos)}


def copiar(motivo="", datos=None, hoy=None, forzar=False):
    """Copia verificada de los *.jsonl. Devuelve un dict con `hecha` (bool), `carpeta`
    y `motivo`. No copia si nada cambio desde la ultima, ni si faltan lineas de la
    ultima (salvo forzar=True): esa copia buena es la que sirve para recuperar."""
    datos = Path(datos or carpeta_datos())
    contenido = _contenido_actual(datos)
    if not contenido:
        return {"hecha": False, "motivo": "no hay datos que copiar"}
    hashes = {n: _sha(b) for n, b in contenido.items()}
    ultima = ultima_copia(datos)
    if not forzar and ultima is not None:
        if {n: d["sha256"] for n, d in ultima["ficheros"].items()} == hashes:
            return {"hecha": False, "carpeta": ultima["carpeta"], "motivo": "sin cambios desde la ultima copia"}
        if faltan(datos, ultima, contenido):
            return {"hecha": False, "carpeta": ultima["carpeta"],
                    "motivo": "faltan lineas de la ultima copia: no se hace otra hasta recuperarlas"}
    momento = registro.ahora()
    dia = (hoy or momento.date()).isoformat()
    raiz = carpeta_copias(datos)
    raiz.mkdir(parents=True, exist_ok=True)
    destino = raiz / dia
    if destino.exists() and not _se_puede_pisar(destino, datos, contenido):
        destino = raiz / f"{dia}_{momento.strftime('%H%M%S')}"
        while destino.exists():
            time.sleep(1)
            destino = raiz / f"{dia}_{registro.ahora().strftime('%H%M%S')}"
    temporal = raiz / f".tmp-{os.getpid()}-{time.monotonic_ns()}"
    try:
        temporal.mkdir()
        for n, b in contenido.items():
            with open(temporal / n, "wb") as f:
                f.write(b)
                f.flush()
                os.fsync(f.fileno())
        manifiesto = {"ts": momento.isoformat(), "origen": str(datos.resolve()), "motivo": motivo,
                      "ficheros": {n: {"sha256": hashes[n], "bytes": len(b),
                                       "lineas": len(_lineas(b.decode("utf-8", errors="replace")))}
                                   for n, b in contenido.items()}}
        (temporal / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
        if not verificar_copia({**manifiesto, "carpeta": temporal}):
            raise OSError("la copia no coincide con el original (SHA256)")
        if destino.exists():
            viejo = raiz / f".viejo-{os.getpid()}-{time.monotonic_ns()}"
            os.replace(destino, viejo)
            os.replace(temporal, destino)
            shutil.rmtree(viejo, ignore_errors=True)
        else:
            os.replace(temporal, destino)
    finally:
        if temporal.exists():
            shutil.rmtree(temporal, ignore_errors=True)
    rotar(datos, hoy=hoy or momento.date())
    return {"hecha": True, "carpeta": destino, "motivo": motivo}


def _se_puede_pisar(destino, datos, contenido):
    """La copia del dia se sustituye solo si es de esta carpeta, no es la de antes
    de recuperar y todo lo suyo sigue en lo nuevo (lo normal: solo se anade)."""
    try:
        m = json.loads((destino / "manifiesto.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if m.get("origen") != str(Path(datos).resolve()) or m.get("motivo") == ANTES_DE_RECUPERAR:
        return False
    return not faltan(datos, {**m, "carpeta": destino}, contenido)


def rotar(datos=None, hoy=None):
    """Se guardan las copias de los ultimos DIAS_COPIAS dias y, de lo anterior, la
    mas nueva de cada mes. Devuelve las carpetas borradas (solo copias de esta carpeta)."""
    hoy = hoy or date.today()
    por_mes = {}
    viejas = []
    for m in copias(datos):
        try:
            d = date.fromisoformat(m["carpeta"].name[:10])
        except ValueError:
            continue
        if (hoy - d).days < DIAS_COPIAS:
            continue
        viejas.append(m["carpeta"])
        mes = d.strftime("%Y-%m")
        if mes not in por_mes or m["carpeta"].name > por_mes[mes].name:
            por_mes[mes] = m["carpeta"]
    borradas = [c for c in viejas if c not in por_mes.values()]
    for c in borradas:
        shutil.rmtree(c, ignore_errors=True)
    return borradas


# ---------- Perdidas y recuperacion ----------

def faltan(datos=None, copia=None, contenido=None):
    """{fichero: [lineas]} que estan en la copia (JSON legible) y ya no en los
    datos ni en los apartados. Vacio si no hay copia o no falta nada."""
    datos = Path(datos or carpeta_datos())
    copia = copia if copia is not None else ultima_copia(datos)
    if copia is None:
        return {}
    if contenido is None:
        contenido = _contenido_actual(datos)
    apartadas = set()
    for nombre, b in contenido.items():
        if nombre.startswith("apartado-"):
            apartadas.update(_lineas(b.decode("utf-8", errors="replace")))
    salida = {}
    for nombre in copia["ficheros"]:
        try:
            antes = (copia["carpeta"] / nombre).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ahora = set(_lineas(contenido.get(nombre, b"").decode("utf-8", errors="replace"))) | apartadas
        perdidas = []
        for linea in _lineas(antes):
            if linea in ahora:
                continue
            try:
                json.loads(linea)
            except ValueError:
                continue   # ya estaba rota en la copia: no se echa de menos
            perdidas.append(linea)
        if perdidas:
            salida[nombre] = perdidas
    return salida


def _clave_ts(par):
    i, linea = par
    try:
        return (datetime.fromisoformat(json.loads(linea)["ts"]).timestamp(), i)
    except (ValueError, KeyError, TypeError):
        return (float("inf"), i)


def _reescribir(ruta, lineas):
    """Escritura atomica de un .jsonl (temporal + fsync + os.replace) y relectura."""
    ruta = Path(ruta)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
    texto = "".join(x + "\n" for x in lineas)
    with open(temporal, "w", encoding="utf-8") as f:
        f.write(texto)
        f.flush()
        os.fsync(f.fileno())
    registro._reintentar(lambda: os.replace(temporal, ruta))
    if _lineas(ruta.read_text(encoding="utf-8")) != list(lineas):
        raise OSError(f"{ruta.name}: al releerlo no coincide con lo escrito")


def recuperar(datos=None, copia=None):
    """Junta en los datos las lineas que faltan de la copia (union, ordenada por
    fecha; no se quita nada). Antes guarda la version actual en las copias.
    Devuelve {fichero: lineas recuperadas}."""
    datos = Path(datos or carpeta_datos())
    copia = copia if copia is not None else ultima_copia(datos)
    perdidas = faltan(datos, copia)
    if not perdidas:
        return {}
    copiar(ANTES_DE_RECUPERAR, datos, forzar=True)
    hecho = {}
    for nombre, lineas in perdidas.items():
        ruta = datos / nombre
        with registro.cerrojo(ruta):
            actuales = _lineas(ruta.read_text(encoding="utf-8", errors="replace")) if ruta.exists() else []
            nuevas = [x for x in lineas if x not in set(actuales)]
            juntas = [x for _, x in sorted(enumerate(actuales + nuevas), key=_clave_ts)]
            _reescribir(ruta, juntas)
        hecho[nombre] = len(nuevas)
    return hecho


# ---------- Lineas danadas ----------

def _validador(nombre):
    if nombre == registro.RUTA.name:
        return registro.validar

    def objeto(linea):
        if not isinstance(json.loads(linea), dict):
            raise ValueError("no es un objeto JSON")
    return objeto


def danadas(ruta):
    """[(numero de linea, texto, motivo)] de las lineas ilegibles de un .jsonl."""
    ruta = Path(ruta)
    validar = _validador(ruta.name)
    malas = []
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return malas
    for n, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        try:
            validar(linea)
        except ValueError as exc:
            malas.append((n, linea.strip(), str(exc)))
    return malas


def apartar_danadas(datos=None, hoy=None):
    """Mueve las lineas ilegibles a apartado-AAAA-MM-DD.jsonl (primero se escriben
    alli, despues se quitan del original). Devuelve {fichero: n apartadas}."""
    datos = Path(datos or carpeta_datos())
    hoy = hoy or date.today()
    destino = datos / f"apartado-{hoy.isoformat()}.jsonl"
    hecho = {}
    for ruta in ficheros(datos):
        if ruta.name.startswith("apartado-"):
            continue
        if not danadas(ruta):
            continue
        with registro.cerrojo(ruta):
            validar = _validador(ruta.name)
            buenas, malas = [], []
            for linea in _lineas(ruta.read_text(encoding="utf-8", errors="replace")):
                try:
                    validar(linea)
                    buenas.append(linea)
                except ValueError:
                    malas.append(linea)
            if not malas:
                continue
            with registro.cerrojo(destino):
                with open(destino, "a", encoding="utf-8") as f:
                    for linea in malas:
                        f.write(linea + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            _reescribir(ruta, buenas)
        hecho[ruta.name] = len(malas)
    return hecho


# ---------- Revision del registro ----------

def revisar_registro(ruta=None, ahora=None):
    """Lo raro del registro: duplicados no forzados, fechas en el futuro, saltos
    atras de mas de un dia y correcciones que no apuntan a ningun intento."""
    ruta = Path(ruta or registro.RUTA)
    ahora = ahora or registro.ahora()
    entradas = registro.leer(ruta, crudo=True)
    vistos, duplicados = {}, []
    futuros, saltos, previo = 0, 0, None
    intentos = {(e["ficha"], e["ts"]) for e in entradas if e.get("motivo") != registro.CORRECCION}
    huerfanas = [e for e in entradas if e.get("motivo") == registro.CORRECCION
                 and (e["ficha"], e.get("corrige")) not in intentos]
    for e in entradas:
        t = datetime.fromisoformat(e["ts"])
        if t.tzinfo is None:
            t = t.astimezone()
        if t > ahora + timedelta(days=1):
            futuros += 1
        if previo is not None and t < previo - timedelta(days=1):
            saltos += 1
        previo = t if previo is None else max(previo, t)
        if e.get("motivo") == registro.CORRECCION:
            continue
        clave = (e["ficha"], e.get("semilla"), registro.fecha(e))
        if clave in vistos and not e.get("forzado"):
            duplicados.append(clave)
        vistos[clave] = True
    return {"intentos": len(entradas) - sum(1 for e in entradas if e.get("motivo") == registro.CORRECCION),
            "duplicados": duplicados, "futuros": futuros, "saltos": saltos, "huerfanas": len(huerfanas)}


# ---------- Git como segunda copia ----------

def _git(*args, timeout=10):
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, **_SIN_VENTANA)


def sin_subir(ahora=None):
    """(commits sin subir, dias del mas viejo) sin usar la red, o None si no se sabe."""
    try:
        r = _git("log", "@{u}..HEAD", "--format=%ct")
        if r.returncode:
            r = _git("log", "--branches", "--not", "--remotes", "--format=%ct")
            if r.returncode:
                return None
    except (OSError, subprocess.SubprocessError):
        return None
    marcas = [int(x) for x in r.stdout.split() if x.isdigit()]
    if not marcas:
        return 0, 0
    ahora = ahora or time.time()
    return len(marcas), int((ahora - min(marcas)) // 86400)


def ignorados():
    """Ficheros de usuario/datos que git ignoraria (no viajarian a GitHub)."""
    try:
        nombres = [f"usuario/datos/{p.name}" for p in ficheros(DATOS)] or ["usuario/datos/registro.jsonl"]
        r = _git("check-ignore", "--no-index", *nombres)
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.split() if r.returncode == 0 else []


# ---------- Arranque y resumen ----------

def _log(texto, cache=None):
    try:
        ruta = Path(cache or CACHE) / "servicio.log"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"--- {registro.ahora().isoformat()} datos: {texto}\n")
    except OSError:
        pass


def _plural(n, uno, varios):
    return f"{n} {uno if n == 1 else varios}"


def al_arrancar(preguntar=None, datos=None, git=True, cache=None):
    """Lo que se hace al empezar una sesion: apartar lineas danadas, comprobar que
    no falta nada de la ultima copia (y ofrecer recuperarlo con `preguntar(texto)`
    -> bool), hacer la copia y mirar si git lleva dias sin subir. Devuelve los
    avisos para el usuario (lista vacia si todo esta bien). Nunca lanza."""
    avisos = []
    try:
        datos = Path(datos or carpeta_datos())
        for nombre, n in apartar_danadas(datos).items():
            avisos.append(f"{_plural(n, 'linea danada', 'lineas danadas')} de {nombre} (p. ej. de un apagon a "
                          f"mitad de guardar) se ha apartado a usuario/datos/apartado-{date.today().isoformat()}"
                          ".jsonl. No se ha borrado nada y el resto esta bien.")
        perdidas = faltan(datos)
        if perdidas:
            copia = ultima_copia(datos)
            n = sum(len(v) for v in perdidas.values())
            texto = (f"Faltan {_plural(n, 'linea', 'lineas')} de tus datos que si estaban en la copia del "
                     f"{copia['ts'][:10]} ({', '.join(perdidas)}).")
            if preguntar is not None and preguntar(texto + "\n\n¿Las recupero ahora? Se juntan con lo que hay; "
                                                   "no se borra nada."):
                hecho = recuperar(datos, copia)
                avisos.append(f"Recuperadas {_plural(sum(hecho.values()), 'linea', 'lineas')} desde la copia del "
                              f"{copia['ts'][:10]}. La version de antes queda guardada en las copias.")
            else:
                avisos.append(texto + " No se ha tocado nada. Para recuperarlas: programa\\practica.py datos --recuperar "
                              "(lo explica `doctor`).")
        copiar("arranque", datos)
        if git and datos.resolve() == DATOS.resolve():
            s = sin_subir()
            if s and s[0] and s[1] > DIAS_SIN_SUBIR:
                avisos.append(f"Hay {_plural(s[0], 'cambio', 'cambios')} sin subir a GitHub desde hace {s[1]} "
                              "dias (estan en el disco y en las copias). Se suben al cerrar si hay red.")
    except Exception as exc:   # proteger los datos nunca debe impedir practicar
        _log(f"al_arrancar: {type(exc).__name__}: {exc}", cache)
        avisos.append(f"No he podido revisar o copiar tus datos ({exc}). Se practica igual; "
                      "si se repite, mira `programa\\practica.py doctor`.")
    for a in avisos:
        _log(a, cache)
    return avisos


def al_cerrar(datos=None, cache=None):
    """La copia del final de la sesion. Nunca lanza; devuelve el resultado."""
    try:
        return copiar("cierre", datos)
    except Exception as exc:
        _log(f"al_cerrar: {type(exc).__name__}: {exc}", cache)
        return {"hecha": False, "motivo": str(exc)}


def resumen(datos=None, git=True):
    """[(ok, texto)] en lenguaje llano; ok=None es un aviso. Seccion «datos» de doctor."""
    datos = Path(datos or carpeta_datos())
    r = []
    ruta = datos / registro.RUTA.name
    rev = revisar_registro(ruta)
    r.append((True, f"datos: {_plural(rev['intentos'], 'intento guardado', 'intentos guardados')} "
                    f"en usuario/datos/{ruta.name}"))
    for p in ficheros(datos):
        if p.name.startswith("apartado-"):
            continue
        malas = danadas(p)
        if malas:
            r.append((None, f"datos: {p.name} tiene {_plural(len(malas), 'linea danada', 'lineas danadas')} "
                            f"(la {malas[0][0]}); al empezar la sesion se apartan solas"))
    apartadas = sum(len(_lineas(p.read_text(encoding="utf-8", errors="replace"))) for p in _apartados(datos))
    if apartadas:
        r.append((None, f"datos: {_plural(apartadas, 'linea apartada', 'lineas apartadas')} en "
                        f"{', '.join(p.name for p in _apartados(datos))} (guardadas, no borradas; conviene revisarlas)"))
    if rev["duplicados"]:
        f, s, d = rev["duplicados"][0]
        r.append((None, f"datos: {_plural(len(rev['duplicados']), 'intento repetido', 'intentos repetidos')} el "
                        f"mismo dia sin --forzar (p. ej. {f} semilla {s} el {d})"))
    if rev["futuros"]:
        r.append((None, f"datos: {_plural(rev['futuros'], 'intento', 'intentos')} con fecha en el futuro "
                        "(¿reloj del equipo mal puesto?)"))
    if rev["huerfanas"]:
        r.append((None, f"datos: {_plural(rev['huerfanas'], 'correccion', 'correcciones')} de reclamaciones "
                        "que no apuntan a ningun intento"))
    ultima = ultima_copia(datos)
    if ultima is None:
        r.append((None, f"datos: aun no hay ninguna copia en {carpeta_copias(datos)}; se hace al empezar la "
                        "proxima sesion"))
    else:
        ok = verificar_copia(ultima)
        dias = (date.today() - date.fromisoformat(ultima["ts"][:10])).days
        r.append((True if ok else False,
                  f"datos: ultima copia del {ultima['ts'][:10]} "
                  f"({'hoy' if dias == 0 else 'hace ' + _plural(dias, 'dia', 'dias')}) en "
                  f"{ultima['carpeta']}: " + ("comprobada (SHA256 bien)" if ok
                                              else "NO coincide con su SHA256: la copia esta danada")))
        perdidas = faltan(datos, ultima)
        if perdidas:
            n = sum(len(v) for v in perdidas.values())
            r.append((False, f"datos: faltan {_plural(n, 'linea', 'lineas')} que si estan en esa copia "
                             f"({', '.join(perdidas)}): programa\\practica.py datos --recuperar las junta sin borrar nada"))
        r.append((True, f"datos: {_plural(len(copias(datos)), 'copia guardada', 'copias guardadas')} "
                        f"(se guardan {DIAS_COPIAS} dias y despues una por mes)"))
    if git and datos.resolve() == DATOS.resolve():
        malos = ignorados()
        if malos:
            r.append((False, f"datos: .gitignore excluye {', '.join(malos)}: no viajaria a GitHub"))
        s = sin_subir()
        if s is not None and s[0]:
            r.append((None if s[1] > DIAS_SIN_SUBIR else True,
                      f"datos: {_plural(s[0], 'commit', 'commits')} sin subir a GitHub"
                      + (f", el mas viejo de hace {_plural(s[1], 'dia', 'dias')}" if s[1] else ", de hoy")
                      + ("; se suben al cerrar con red" if s[1] > DIAS_SIN_SUBIR else "")))
    return r
