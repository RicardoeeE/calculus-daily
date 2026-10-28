"""Capa de servicio: la sesion de practica sin input() ni print.

La usan la terminal (practica.py), los comandos JSON (modo revisor) y la
ventana. `Sesion` no guarda estado de
interfaz: todo lo que importa esta en disco (registro.jsonl y .cache), asi que
se puede retomar y las tres vias son intercambiables. Cada metodo publico
devuelve un dict serializable a JSON con la clave `ok`.
"""
import functools
import os
import re
import threading
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

from . import registro, tutela
from .rutas import CACHE
from . import sesion as _sesion
from .diagnostico import diagnosticar
from .expresiones import ErrorLectura
from .fichas import cargar, cargar_ejemplos
from .huecos import huecos_de, recortar
from .latex import enunciado_latex, latex_lectura
from .planificador import cola as calcular_cola, cola_examen, elegir_examen, progreso_al_dia

TOPE_SEGUNDOS = 20 * 60   # mas tiempo con un ejercicio: se ha ido; segundos = None
LOG_MAX = 1_000_000       # bytes de .cache/servicio.log antes de rotarlo
reloj = time.time         # las pruebas lo cambian

AYUDA_TIPO = {
    "algebra": "calentamiento: responde con los valores separados por comas (o «h = 3, k = 4»)",
    "definida": "el resultado es un numero: vale 2 ln(3), π/4, 1/3...",
    "exacta": "escribe ∂M/∂y, ∂N/∂x separados por coma",
    "raices": "escribe las raices separadas por «, » o «;» (0,5 es decimal); vale «2±3i»",
    "edo_solucion": "escribe y(x); en la general usa C1 y C2",
    "parcial": "escribe la derivada con x e y; la otra letra es un numero",
    "potencial": "escribe F(x, y); el «= C» es opcional",
    "calculo": "escribe la expresion que pide el enunciado (con x; C1 y C2 si salen)",
}
ETIQUETAS = {"repaso": "repaso", "nueva": "nueva", "refuerzo": "refuerzo",
             "previa": "previa: algebra de una ficha atascada"}
LIMITE_LECTURA = 200      # caracteres de la vista previa (la ventana corta igual)
_AMBIGUAS = (
    (re.compile(r"(?<![\w.)])\d+\s*/\s*\d+\s*[a-z(]"),
     "Una fracción seguida de algo («1/2x») la leo como (1/2)·x. Si querías 1/(2x), escribe los paréntesis."),
    (re.compile(r"(?<![a-z])e\s*\^\s*-?\d[\d.]*\s*[a-z]"),
     "«e^2x»: lo leo como e^(2x). Si no es eso, escribe los paréntesis."),
)


def ambiguedades(texto):
    """Avisos neutros de la vista previa: escrituras que se pueden leer de dos
    maneras. No dicen nada de si esta bien."""
    return [aviso for patron, aviso in _AMBIGUAS if patron.search(texto)]


# ---------- .cache: cola del dia y anotaciones ----------

def ruta_cache(cache, nombre):
    cache = Path(cache)
    cache.mkdir(exist_ok=True)
    return cache / nombre


def cola_guardada(cache, fichas, dia, minimo=False, completa=False):
    """La cola se fija al pedirla por primera vez en el dia, para que la ventana,
    la terminal y los comandos JSON vean lo mismo; se quitan las ya registradas hoy y las fichas que
    ya no existen. Las colas de dias anteriores se borran. Con completa=True
    tambien vuelven las ya hechas (para numerar «3 de 5»)."""
    cache = Path(cache)
    # Se guardan hoy y ayer: un ejercicio empezado antes de medianoche se registra
    # con sus pistas, fallos y hora de inicio (dia_ejercicio).
    guardar = (dia.isoformat(), (dia - timedelta(days=1)).isoformat())
    for vieja in cache.glob("*.json") if cache.exists() else []:
        if vieja.name != EN_CURSO and not any(d in vieja.name for d in guardar):
            vieja.unlink(missing_ok=True)
    ruta = ruta_cache(cache, f"cola-{dia.isoformat()}{'-minimo' if minimo else ''}.json")
    if ruta.exists():
        guardada = registro.leer_json(ruta)
    else:
        entradas = registro.leer()
        hitos = progreso_al_dia(fichas, entradas).escalon   # el escalon alcanzado nunca baja
        guardada = [{"ficha": x.ficha.id, "semilla": x.semilla, "motivo": x.motivo}
                    for x in calcular_cola(fichas, entradas, dia, minimo, hitos=hitos)]
        registro.escribir_json(ruta, guardada)
    hechas = set() if completa else hechas_hoy(dia)
    return [g for g in guardada if (g["ficha"], g["semilla"]) not in hechas and g["ficha"] in fichas]


def hechas_hoy(dia):
    return {(e["ficha"], e.get("semilla")) for e in registro.leer() if registro.fecha(e) == dia}


def anotado(cache, nombre, dia):
    ruta = ruta_cache(cache, f"{nombre}-{dia.isoformat()}.json")
    try:
        return registro.leer_json(ruta, {}), ruta
    except ValueError:  # fichero a medias de una version anterior: se empieza de cero
        return {}, ruta


def anotar(cache, nombre, dia, ficha_id, semilla, cambio):
    """Leer, cambiar y escribir bajo cerrojo y de forma atomica: dos procesos
    pueden anotar a la vez sin perder nada."""
    ruta = ruta_cache(cache, f"{nombre}-{dia.isoformat()}.json")
    with registro.cerrojo(ruta):
        datos, _ = anotado(cache, nombre, dia)
        clave = f"{ficha_id}:{semilla}"
        datos[clave] = cambio(datos.get(clave, 0))
        registro.escribir_json(ruta, datos)


def leer_anotacion(cache, nombre, dia, ficha_id, semilla, vacio=0):
    return anotado(cache, nombre, dia)[0].get(f"{ficha_id}:{semilla}", vacio)


EN_CURSO = "en-curso.json"   # ficha:semilla -> dia en que se empezo (mostrar, pista o comprobar)


def _en_curso(cache):
    try:
        datos = registro.leer_json(ruta_cache(cache, EN_CURSO), {})
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def marcar_en_curso(cache, dia, ficha_id, semilla, reescribir=False):
    """Anota el dia en que se empezo el ejercicio. `mostrar` lo reescribe; pista y
    comprobar solo lo ponen si no estaba (asi conservan el dia de antes de medianoche)."""
    ruta = ruta_cache(cache, EN_CURSO)
    with registro.cerrojo(ruta):
        datos = {}
        for clave, d in _en_curso(cache).items():
            try:
                if 0 <= (dia - date.fromisoformat(d)).days <= 1:
                    datos[clave] = d
            except (TypeError, ValueError):
                continue
        clave = f"{ficha_id}:{semilla}"
        if reescribir or clave not in datos:
            datos[clave] = dia.isoformat()
        registro.escribir_json(ruta, datos)


def dia_ejercicio(cache, hoy, ficha_id, semilla):
    """El dia al que pertenece el ejercicio: ayer si se empezo ayer y aun no esta
    registrado ayer (se cruzo la medianoche a mitad); si no, hoy."""
    try:
        d = date.fromisoformat(_en_curso(cache).get(f"{ficha_id}:{semilla}", ""))
    except (TypeError, ValueError):
        return hoy
    if (hoy - d).days == 1 and (ficha_id, semilla) not in hechas_hoy(d):
        return d
    return hoy


def motivo_en_cola(cache, dia, ficha_id, semilla, fichas=None):
    cache = Path(cache)
    ruta = cache / f"simulacro-{dia.isoformat()}.json"
    if ruta.exists() and any(g["ficha"] == ficha_id and g["semilla"] == semilla
                             for g in registro.leer_json(ruta)):
        return "simulacro"
    ruta = cache / f"nivel-{dia.isoformat()}.json"
    if ruta.exists() and any(g["ficha"] == ficha_id and g["semilla"] == semilla
                             for g in registro.leer_json(ruta)):
        return "nivel"
    for minimo in ("", "-minimo"):
        ruta = cache / f"cola-{dia.isoformat()}{minimo}.json"
        if ruta.exists():
            for g in registro.leer_json(ruta):
                if g["ficha"] == ficha_id and g["semilla"] == semilla:
                    return g["motivo"]
    ex = elegir_examen(dia)
    if ex is not None:
        for x in cola_examen(fichas or cargar(), registro.leer(), dia, ex, 20):
            if x.ficha.id == ficha_id and x.semilla == semilla:
                return "examen"
    return "fuera de cola"


# ---------- Ejemplos resueltos (completos o con huecos) ----------

def ejemplo_con_huecos(fichas, ficha_id, entradas=None):
    """(ejemplo, huecos) de la tecnica de esta ficha segun sus aciertos; (None, 0) si no toca."""
    ficha = fichas.get(ficha_id)
    if ficha is None:
        return None, 0
    entradas = registro.leer() if entradas is None else entradas
    huecos = huecos_de(entradas, ficha.tecnica)
    if huecos is None:
        return None, 0
    ej = cargar_ejemplos(fichas=fichas).get(ficha.tecnica)
    return (ej, huecos) if ej is not None else (None, 0)


def ejemplo_json(ej, huecos=0):
    pasos, ocultos = recortar(ej["pasos"], huecos)
    salida = {"tecnica": ej["tecnica"], "idea": ej["idea"], "enunciado": ej["enunciado"],
              "pasos": pasos, "resultado": ej["resultado"]}
    if ocultos:
        salida["huecos"] = len(ocultos)
        salida["pasos_ocultos"] = ocultos
    return salida


def con_ejemplo(fichas, items, ejemplo=None):
    """El campo `ejemplo` solo en el primer ejercicio de cada tecnica que aun lo
    necesita (completo o con huecos). `items`: pares (item, salida)."""
    ejemplo = ejemplo or ejemplo_con_huecos
    vistas = set()
    entradas = registro.leer()
    for item, salida in items:
        ej, huecos = ejemplo(fichas, item["ficha"], entradas)
        if ej is not None and ej["tecnica"] not in vistas:
            vistas.add(ej["tecnica"])
            salida["ejemplo"] = ejemplo_json(ej, huecos)


# ---------- Errores: nunca una excepcion hacia la ventana ----------

def _al_log(cache, nombre, args, exc):
    try:
        ruta = ruta_cache(cache, "servicio.log")
        if ruta.exists() and ruta.stat().st_size > LOG_MAX:
            os.replace(ruta, ruta.with_name("servicio.log.1"))
        texto = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"--- {registro.ahora().isoformat()} {nombre}{args!r}\n{texto}\n")
    except OSError:
        pass  # sin log no se para la sesion


def seguro(metodo):
    """Con Sesion(seguro=True) (la ventana), una excepcion se devuelve como
    {ok: False, error} y la traza queda en .cache/servicio.log. Con seguro=False
    (terminal y pruebas) la excepcion sube tal cual. `metodo.sin_envolver` es la
    funcion original."""
    @functools.wraps(metodo)
    def envuelto(self, *args, **kwargs):
        if not self.seguro:
            return metodo(self, *args, **kwargs)
        try:
            return metodo(self, *args, **kwargs)
        except Exception as exc:
            _al_log(self.cache, metodo.__name__, args + tuple(kwargs.items()), exc)
            return {"ok": False, "error": str(exc) or type(exc).__name__}
    envuelto.sin_envolver = metodo
    return envuelto


# ---------- La sesion ----------

class Sesion:
    """Sesion de practica sin interfaz. El dia se calcula en cada llamada.

    `registrar` y `ejemplo` permiten cambiar la funcion de registro y la de los
    ejemplos (la terminal pasa las suyas para que las pruebas puedan simularlas)."""
    _cerrojo = threading.Lock()

    def __init__(self, fichas=None, cache=None, seguro=True, registrar=None, ejemplo=None):
        self._fichas = fichas
        self._cache = Path(cache) if cache is not None else None
        self.seguro = seguro
        self._registrar = registrar
        self._ejemplo = ejemplo
        self._ejemplos = None

    @property
    def cache(self):
        return self._cache if self._cache is not None else CACHE

    @property
    def fichas(self):
        if self._fichas is None:
            self._fichas = cargar()
        return self._fichas

    @staticmethod
    def hoy():
        return registro.ahora().date()

    def _variante(self, ficha_id, semilla):
        if ficha_id not in self.fichas:
            raise KeyError(f"No existe la ficha {ficha_id}")
        try:
            semilla = int(semilla)
        except (TypeError, ValueError):
            raise ValueError(f"La semilla debe ser un numero entero (se ha recibido «{semilla}»)") from None
        return self.fichas[ficha_id].variante(semilla)

    def _ejemplo_de(self, ficha_id, entradas=None):
        return (self._ejemplo or ejemplo_con_huecos)(self.fichas, ficha_id, entradas)

    def _dia_de(self, v):
        return dia_ejercicio(self.cache, self.hoy(), v.ficha.id, v.semilla)

    def _pistas(self, dia, v):
        return leer_anotacion(self.cache, "pistas", dia, v.ficha.id, v.semilla)

    def _fallos(self, dia, v):
        return leer_anotacion(self.cache, "fallos", dia, v.ficha.id, v.semilla)

    def _segundos(self, dia, v):
        """Segundos desde `mostrar`; None si no se mostro o pasa del tope."""
        inicio = leer_anotacion(self.cache, "inicio", dia, v.ficha.id, v.semilla, None)
        if inicio is None:
            return None
        s = reloj() - inicio
        return round(s) if 0 <= s <= TOPE_SEGUNDOS else None

    def _datos(self, v, dia):
        pistas, fallos = self._pistas(dia, v), self._fallos(dia, v)
        return {"ficha": v.ficha.id, "semilla": v.semilla, "tipo": v.ficha.tipo, "tecnica": v.ficha.tecnica,
                "larga": v.ficha.larga, "enunciado": v.enunciado, "enunciado_latex": enunciado_latex(v),
                "como_responder": AYUDA_TIPO.get(v.ficha.tipo, ""), "fuente": v.ficha.fuente,
                "pistas_vistas": pistas, "fallos": fallos, "solucion_disponible": pistas >= 2 or fallos >= 1}

    @seguro
    def cola(self, minimo=False):
        """Ejercicios pendientes de hoy (los mismos que `practica.py cola`), con
        `numero` y `total` del dia y el `ejemplo` resuelto donde toca."""
        dia = self.hoy()
        completa = cola_guardada(self.cache, self.fichas, dia, minimo, completa=True)
        hechas = hechas_hoy(dia)
        salida, pares = [], []
        for n, item in enumerate(completa, 1):
            if (item["ficha"], item["semilla"]) in hechas:
                continue
            v = self._variante(item["ficha"], item["semilla"])
            d = {**item, **self._datos(v, dia), "etiqueta": ETIQUETAS.get(item["motivo"], item["motivo"]),
                 "numero": n, "total": len(completa)}
            salida.append(d)
            pares.append((item, d))
        con_ejemplo(self.fichas, pares, self._ejemplo)
        return {"ok": True, "dia": dia.isoformat(), "ejercicios": salida}

    @seguro
    def ejercicio(self, ficha, semilla):
        """Los datos de un ejercicio, sin poner en marcha el reloj."""
        v = self._variante(ficha, semilla)
        return {"ok": True, **self._datos(v, self._dia_de(v))}

    @seguro
    def mostrar(self, ficha, semilla):
        """Como `ejercicio`, y anota la hora: los segundos los mide el motor."""
        dia, v = self.hoy(), self._variante(ficha, semilla)
        ahora = reloj()
        marcar_en_curso(self.cache, dia, v.ficha.id, v.semilla, reescribir=True)
        anotar(self.cache, "inicio", dia, v.ficha.id, v.semilla, lambda _: ahora)
        return {"ok": True, **self._datos(v, dia)}

    @seguro
    def leer(self, texto, ficha, semilla):
        """Solo lectura (vista previa neutra): no corrige ni anota nada. Usa la
        misma funcion de lectura que `comprobar`."""
        v = self._variante(ficha, semilla)
        texto = str(texto)
        if len(texto) > LIMITE_LECTURA:
            return {"ok": False, "leido": None, "latex": None, "avisos": [],
                    "error": f"es demasiado larga (más de {LIMITE_LECTURA} caracteres)"}
        avisos = ambiguedades(texto)
        try:
            lec = _sesion.lectura(v, texto)
        except ErrorLectura as exc:
            return {"ok": False, "leido": None, "latex": None, "avisos": avisos, "error": str(exc)}
        try:
            tex = latex_lectura(lec)
        except Exception:  # el LaTeX es un extra: sin el, queda el texto
            tex = None
        return {"ok": True, "leido": lec.leido, "latex": tex, "avisos": avisos, "error": None}

    @seguro
    def comprobar(self, ficha, semilla, respuesta):
        """Como `practica.py comprobar`: si no cuadra, anota el fallo. Una
        respuesta ilegible no cuenta (`error`)."""
        v = self._variante(ficha, semilla)
        dia = self._dia_de(v)
        r = _sesion.comprobar(v, respuesta)
        diag = [] if r.correcto or r.error else diagnosticar(v, respuesta)
        if not r.correcto and not r.error:
            marcar_en_curso(self.cache, dia, v.ficha.id, v.semilla)
            anotar(self.cache, "fallos", dia, v.ficha.id, v.semilla, lambda n: n + 1)
        pistas, fallos = self._pistas(dia, v), self._fallos(dia, v)
        return {"ok": True, "correcto": r.correcto, "leido": r.leido, "avisos": list(r.avisos), "error": r.error,
                "diagnostico": diag, "fallos": fallos, "solucion_disponible": pistas >= 2 or fallos >= 1}

    @seguro
    def pista(self, ficha, semilla, nivel):
        """Anota la pista mas alta vista y devuelve su texto (nivel 1-4)."""
        nivel = int(nivel)
        if not 1 <= nivel <= 4:
            raise ValueError("la pista va de 1 a 4")
        v = self._variante(ficha, semilla)
        dia = self._dia_de(v)
        marcar_en_curso(self.cache, dia, v.ficha.id, v.semilla)
        anotar(self.cache, "pistas", dia, v.ficha.id, v.semilla, lambda n: max(n, nivel))
        pistas, fallos = self._pistas(dia, v), self._fallos(dia, v)
        return {"ok": True, "nivel": nivel, "texto": v.pista(nivel),
                "solucion_disponible": pistas >= 2 or fallos >= 1}

    @seguro
    def solucion(self, ficha, semilla):
        """Ver la solucion: equivale a rendirse (pista 4)."""
        r = Sesion.pista.sin_envolver(self, ficha, semilla, 4)
        v = self._variante(ficha, semilla)
        return {"ok": True, "texto": r["texto"], "solucion": v.solucion_texto, "rendido": True}

    def _causa_texto(self, causa):
        if causa in (None, ""):
            return None
        if str(causa) in tutela.CAUSAS and str(causa) != "5":
            return tutela.CAUSAS[str(causa)]
        if causa in tutela.CAUSAS.values():
            return causa
        raise ValueError(f"causa desconocida: {causa!r} (1-4)")

    @seguro
    def causa_necesaria(self, ficha, semilla, rendido=False, pistas=0, reclamo=False):
        """True si hay que preguntar que ha pasado: se rindio o vio 2 pistas o mas."""
        if reclamo:
            return {"ok": True, "necesaria": False}
        v = self._variante(ficha, semilla)
        vistas = max(int(pistas), self._pistas(self._dia_de(v), v))
        return {"ok": True, "necesaria": bool(rendido or vistas >= 2)}

    @seguro
    def registrar(self, ficha, semilla, confianza, respuesta=None, rendido=False, causa=None, reclamo=False,
                  *, pistas=0, fallos=0, segundos=None, motivo=None, diagnostico=None, forzar=False):
        """Registra el intento con las pistas y fallos anotados y los segundos de
        `mostrar`. Idempotente: si ya esta registrado hoy, devuelve
        {ok: True, ya_registrado: True, entrada} sin escribir otra linea."""
        with Sesion._cerrojo:
            confianza = int(confianza)
            if not 1 <= confianza <= 5:
                raise ValueError("la confianza va de 1 a 5")
            if not respuesta and not rendido:
                raise ValueError("falta la respuesta (o rendido si se vio la solucion)")
            v = self._variante(ficha, semilla)
            dia = self._dia_de(v)   # el dia en que se empezo, aunque ya sea otro (medianoche)
            pistas = max(int(pistas), self._pistas(dia, v))
            fallos = max(int(fallos), self._fallos(dia, v))
            if segundos is None:
                segundos = self._segundos(dia, v)
            if reclamo and (rendido or pistas >= 4):
                raise ValueError("no se puede reclamar si se vio la solucion (rendido o pista 4)")
            if respuesta and not rendido:
                previo = _sesion.comprobar(v, respuesta)
                if previo.error:
                    raise _sesion.RespuestaIlegible(f"no se lee la respuesta ({previo.error}); escribela de "
                                                    "otra forma o registra como rendido")
                if diagnostico is None:
                    diagnostico = [] if previo.correcto else diagnosticar(v, respuesta)
            if diagnostico is None:
                diagnostico = []
            motivo = motivo or motivo_en_cola(self.cache, dia, v.ficha.id, v.semilla, self.fichas)
            hacer = self._registrar or _sesion.registrar
            try:
                entrada, proxima = hacer(v, respuesta, confianza, pistas, segundos, rendido, motivo=motivo,
                                         forzar=forzar, causa=self._causa_texto(causa), reclamo=reclamo,
                                         diagnostico=diagnostico, fallos=fallos)
            except _sesion.YaRegistrado:
                previa = [e for e in registro.leer() if e["ficha"] == v.ficha.id
                          and e.get("semilla") == v.semilla and registro.fecha(e) == self.hoy()]
                return {"ok": True, "ya_registrado": True, "entrada": previa[-1] if previa else None}
            return {"ok": True, "ya_registrado": False, "nota": entrada.get("nota"),
                    "correcto": entrada.get("correcto"), "pistas": pistas, "fallos": fallos,
                    "avisos": entrada.get("avisos", []), "segundos": segundos,
                    "proximo": proxima.isoformat(), "entrada": entrada}

    def ejemplo_cargado(self, tecnica):
        """El ejemplo de fichas/ejemplos.toml de esa tecnica, con `variante` y
        `marcado` (las formulas entre $...$, para la ventana), o None."""
        if self._ejemplos is None:
            self._ejemplos = cargar_ejemplos(fichas=self.fichas)
        return self._ejemplos.get(tecnica)

    @seguro
    def comprobar_ejemplo(self, tecnica, respuesta):
        """El resultado del ejemplo con huecos: se corrige, pero no se registra."""
        if self._ejemplos is None:
            self._ejemplos = cargar_ejemplos(fichas=self.fichas)
        r = _sesion.comprobar(self._ejemplos[tecnica]["variante"], respuesta)
        return {"ok": True, "correcto": r.correcto, "leido": r.leido, "error": r.error}

    @seguro
    def sin_saber_empezar(self, ficha, semilla):
        """«No se por donde empezar»: el ejemplo resuelto COMPLETO de la
        tecnica (o, si no tiene, las pistas 1 y 2). Cuenta como la pista 2: acertar
        despues vale como mucho 2, se pregunta la causa y la solucion queda disponible."""
        v = self._variante(ficha, semilla)
        dia = self._dia_de(v)
        marcar_en_curso(self.cache, dia, v.ficha.id, v.semilla)
        anotar(self.cache, "pistas", dia, v.ficha.id, v.semilla, lambda n: max(n, 2))
        if self._ejemplos is None:
            self._ejemplos = cargar_ejemplos(fichas=self.fichas)
        ej = self._ejemplos.get(v.ficha.tecnica)
        return {"ok": True, "ejemplo": ejemplo_json(ej, 0) if ej is not None else None,
                "pistas": [] if ej is not None else [v.pista(1), v.pista(2)],
                "pistas_vistas": self._pistas(dia, v), "solucion_disponible": True}

    @seguro
    def practicar(self, ficha, semilla, respuesta):
        """Reescribir de memoria la solucion ya vista: se corrige, pero no se
        anota ni se registra. Solo cuando el ejercicio ya esta registrado hoy, para
        que no sirva para tantear antes de registrar."""
        v = self._variante(ficha, semilla)
        if (v.ficha.id, v.semilla) not in hechas_hoy(self.hoy()):
            raise ValueError("primero se registra el ejercicio; despues se puede practicar")
        r = _sesion.comprobar(v, str(respuesta))
        return {"ok": True, "correcto": r.correcto, "leido": r.leido, "error": r.error}

    @seguro
    def sensacion(self, valor, texto=""):
        valor = int(valor)
        if not 1 <= valor <= 5:
            raise ValueError("la sensacion va de 1 a 5")
        return {"ok": True, "id": tutela.anotar("sensacion", valor=valor, texto=texto)["id"]}

    @seguro
    def queja(self, texto):
        if not str(texto).strip():
            raise ValueError("la queja esta vacia")
        return {"ok": True, "id": tutela.anotar("queja", texto=texto)["id"]}

    @staticmethod
    def _dia(dia):
        if dia is None:
            return Sesion.hoy()
        return date.fromisoformat(dia) if isinstance(dia, str) else dia

    @seguro
    def cerrar_local(self, dia=None):
        """Escribe el bloque del dia en el diario y devuelve el resumen, sin git.
        Se puede llamar varias veces (el bloque se reescribe)."""
        with Sesion._cerrojo:
            dia = self._dia(dia)
            mensaje, n = _sesion.cerrar_local(dia, self.fichas)
            return {"ok": True, "dia": dia.isoformat(), "ejercicios": n, "mensaje": mensaje}

    @seguro
    def sincronizar(self, timeout=60, dia=None):
        """El git de `cerrar` (commit, pull --rebase y push) con tope de tiempo y
        sin preguntar credenciales. No lanza: {ok, mensaje}."""
        dia = self._dia(dia)
        n = sum(1 for e in registro.leer() if registro.fecha(e) == dia)
        if not n:
            return {"ok": True, "mensaje": "git: hoy no hay intentos; no se sube nada."}
        entorno = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
        mensaje = _sesion._git(dia, n, timeout=timeout, entorno=entorno)
        ok = "subido" in mensaje or "no hay remoto" in mensaje or "no hay datos" in mensaje
        return {"ok": ok, "mensaje": mensaje}
