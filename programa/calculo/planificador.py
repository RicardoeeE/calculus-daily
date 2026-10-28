"""Repaso espaciado (FSRS), dominio por tecnica y cola del dia.

- Dominio de una tecnica: mediana de p > 0,7 (P(p > 0,7) >= 0,5) con p ~ Beta
  en los ultimos 8 intentos; un acierto con pista cuenta medio; hacen falta al
  menos 4 intentos y aciertos en 2 fichas distintas (o en todas si hay menos).
- Un escalon se abre cuando la mitad (redondeando hacia arriba) de las tecnicas
  del anterior esta dominada. El progreso es un hito: nunca retrocede.
- Las tecnicas de un examen se abren unos dias antes (fichas/calendario.toml).
- Fechas: FSRS trabaja con el mediodia local de cada dia, no con la hora exacta.
- El cupo se rellena con repasos de refuerzo y la sesion empieza por algo que sale.
- Repeticion implicita: acertar una tecnica que contiene a otra (fichas/grafo.toml)
  aplaza el repaso vencido de la contenida. Solo mueve fechas de FSRS.
- Prueba de nivel: intentos con motivo «nivel» que, si se aciertan sin pistas, cuentan
  como «competente» para abrir el siguiente escalon (nunca para «dominada»).
"""
import os
import random
import tomllib
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from math import ceil, exp, lgamma, log
from pathlib import Path

from fsrs import Card, Rating, Scheduler

from .fichas import CARPETA, ESCALONES, cargar_grafo, grupo
from .registro import fecha

# Retencion 0,90 y tope de 60 dias: con los parametros por defecto de FSRS
# (entrenados con tarjetas de memoria) 0,85 daba 4 y 31 dias tras los dos
# primeros aciertos, demasiado para procedimientos recien aprendidos.
PLANIFICADOR = Scheduler(
    desired_retention=0.90,
    learning_steps=(),
    relearning_steps=(),
    maximum_interval=60,
    enable_fuzzing=False,
)

GRUPOS = ("algebra", "parcial", "derivada", "integral")

# 5 ejercicios al dia. El algebra es el calentamiento (1-2 min).
# «parcial» agrupa parciales, EDOs exactas y EDOs de orden superior.
CUPO = {"algebra": 1, "parcial": 1, "derivada": 1, "integral": 2}
CUPO_MINIMO = {"algebra": 0, "parcial": 0, "derivada": 1, "integral": 1}

# Foco: mientras el grupo no se haya dominado nunca, 2 de los
# 5 son de ese grupo. Al dominarlo por primera vez se apaga para siempre.
FOCO = "parcial"
CUPO_FOCO = {"algebra": 1, "parcial": 2, "derivada": 0, "integral": 2}
CUPO_MINIMO_FOCO = {"algebra": 0, "parcial": 1, "derivada": 0, "integral": 1}

VENTANA = 8          # ultimos intentos por tecnica para medir dominio
UMBRAL_P = 0.7       # acierto autonomo que se considera dominio
CONFIANZA_P = 0.5    # P(p > UMBRAL_P) exigida: la mediana supera el umbral
MIN_INTENTOS = 4     # intentos minimos en la ventana
FICHAS_OK = 2        # fichas distintas acertadas (o todas, si la tecnica tiene menos)
ATASCO = 4           # fallos seguidos para apartar una ficha
PAUSA_ATASCO = 7     # dias que se aparta
# CALCULO_DIARIO_CALENDARIO permite usar otro calendario (las pruebas usan uno fijo).
CALENDARIO = Path(os.environ.get("CALCULO_DIARIO_CALENDARIO") or CARPETA / "calendario.toml")
MOTIVOS_EXTRA = ("examen", "simulacro", "nivel")   # sesiones extra: no gastan el cupo diario


def _mediodia(dia):
    """Mediodia local del dia, en UTC: FSRS cuenta dias, no horas."""
    return datetime.combine(dia, time(12)).astimezone().astimezone(timezone.utc)


def _momento(entrada):
    return _mediodia(fecha(entrada))


def _id_numerico(ficha_id):
    return zlib.crc32(ficha_id.encode())


def _ordenadas(entradas):
    return sorted(entradas, key=lambda e: e["ts"])


@dataclass
class Implicita:
    """Una revision virtual: `ficha` se da por repasada porque se acerto `origen`."""
    dia: date
    ficha: str
    origen: str


@lru_cache(maxsize=1)
def _grafo_defecto():
    return cargar_grafo()


def _reproducir(entradas, grafo=None, antes=None):
    """Reproduce el registro en orden: (ficha_id -> Card, [Implicita]).

    Repeticion implicita: cuando un intento real con nota >= 3 (y que no es de
    simulacro) es de una tecnica que contiene a otras (grafo), por cada contenida se toma
    la ficha YA vista cuyo repaso ya ha vencido en ese momento y con menor
    retenibilidad, y se le aplica una revision virtual «Good». Solo uno por contenida
    y por intento, un nivel, nunca crea tarjetas. Es derivado y determinista: el
    registro no se toca y los intentos virtuales no cuentan para dominio, progreso ni
    estadisticas; solo mueven la fecha de repaso.
    `grafo`: None = fichas/grafo.toml; {} = sin repeticion implicita.
    `antes(entrada, momento, tarjeta_previa)` se llama con cada intento real antes de aplicarlo."""
    grafo = _grafo_defecto() if grafo is None else grafo
    tarjetas, por_tecnica, implicitas = {}, {}, []
    for e in _ordenadas(entradas):
        momento = _momento(e)
        previa = tarjetas.get(e["ficha"])
        if antes is not None:
            antes(e, momento, previa)
        tarjeta = previa or Card(card_id=_id_numerico(e["ficha"]))
        tarjetas[e["ficha"]], _ = PLANIFICADOR.review_card(tarjeta, Rating(e["nota"]), review_datetime=momento)
        tecnica = e.get("tecnica")
        if tecnica:
            por_tecnica.setdefault(tecnica, set()).add(e["ficha"])
        if e["nota"] < 3 or e.get("motivo") == "simulacro":
            continue
        for contenida in grafo.get(tecnica, ()):
            vencidas = [(PLANIFICADOR.get_card_retrievability(tarjetas[fid], momento), fid)
                        for fid in por_tecnica.get(contenida, ()) if tarjetas[fid].due <= momento]
            if vencidas:
                fid = min(vencidas)[1]
                tarjetas[fid], _ = PLANIFICADOR.review_card(tarjetas[fid], Rating.Good, review_datetime=momento)
                implicitas.append(Implicita(fecha(e), fid, e["ficha"]))
    return tarjetas, implicitas


def estados(entradas, grafo=None):
    """ficha_id -> Card de FSRS, reproduciendo el registro en orden (con repeticion implicita)."""
    return _reproducir(entradas, grafo)[0]


def repasos_ahorrados(entradas, dia, dias=30, grafo=None):
    """Repasos que la repeticion implicita ha aplazado en los ultimos `dias` dias."""
    return sum(1 for i in _reproducir(entradas, grafo)[1] if 0 <= (dia - i.dia).days < dias)


def fecha_proxima(tarjeta):
    return tarjeta.due.astimezone().date()


def retenibilidad(tarjeta, dia):
    return PLANIFICADOR.get_card_retrievability(tarjeta, _mediodia(dia))


@lru_cache(maxsize=4096)
def prob_mayor(aciertos, fallos, umbral=UMBRAL_P):
    """P(p > umbral) con p ~ Beta(1 + aciertos, 1 + fallos) (prior uniforme).
    Admite medios aciertos: se integra la densidad numericamente."""
    a, b = 1 + aciertos, 1 + fallos
    lognorm = lgamma(a + b) - lgamma(a) - lgamma(b)
    pasos = 2000
    h = (1 - umbral) / pasos
    total = 0.0
    for i in range(pasos + 1):
        p = umbral + i * h
        if p <= 0 or p >= 1:
            d = 0.0 if (p >= 1 and b > 1) or (p <= 0 and a > 1) else exp(lognorm)
        else:
            d = exp(lognorm + (a - 1) * log(p) + (b - 1) * log(1 - p))
        total += d * (1 if i in (0, pasos) else (4 if i % 2 else 2))
    return min(1.0, max(0.0, total * h / 3))


def _valor_nota(nota):
    return 1.0 if nota >= 3 else (0.5 if nota == 2 else 0.0)


@dataclass
class Dominio:
    tecnica: str
    intentos: int
    aciertos: float
    fichas_ok: int
    fichas_pedidas: int
    p: float

    @property
    def dominada(self):
        return (self.intentos >= MIN_INTENTOS and self.p >= CONFIANZA_P
                and self.fichas_ok >= self.fichas_pedidas)


NIVELES = ("sin empezar", "familiar", "competente", "dominada")
COMPETENTE_P = 0.3      # P(p > UMBRAL_P) minima para «competente»
COMPETENTE_INTENTOS = 3


def nivel(d):
    """Nivel visible de una tecnica (estilo Khan Academy), a partir de su Dominio:
    sin empezar (ningun acierto), familiar (algun acierto), competente
    (P(p > 0,7) >= 0,3 y al menos 3 intentos) o dominada (la regla de siempre)."""
    if d.dominada:
        return "dominada"
    if d.intentos >= COMPETENTE_INTENTOS and d.p >= COMPETENTE_P and d.aciertos > 0:
        return "competente"
    if d.aciertos > 0:
        return "familiar"
    return "sin empezar"


def subidas_de_nivel(entradas, dia, fichas=None):
    """[(tecnica, nivel_antes, nivel_despues)] de las tecnicas practicadas hoy cuyo
    nivel ha subido respecto a las entradas anteriores a hoy. Si baja, no se dice."""
    antes = [e for e in entradas if fecha(e) < dia]
    hasta_hoy = [e for e in entradas if fecha(e) <= dia]
    tecnicas = sorted({e.get("tecnica") for e in entradas if fecha(e) == dia and e.get("tecnica")})
    subidas = []
    for t in tecnicas:
        a = nivel(dominio(antes, t, fichas))
        b = nivel(dominio(hasta_hoy, t, fichas))
        if NIVELES.index(b) > NIVELES.index(a):
            subidas.append((t, a, b))
    return subidas


def _dominio_de(ventana, tecnica, n_fichas):
    aciertos = sum(_valor_nota(e["nota"]) for e in ventana)
    fichas_ok = len({e["ficha"] for e in ventana if e["nota"] >= 3})
    pedidas = min(FICHAS_OK, max(1, n_fichas))
    return Dominio(tecnica, len(ventana), aciertos, fichas_ok, pedidas,
                   prob_mayor(aciertos, len(ventana) - aciertos))


def _fichas_por_tecnica(fichas):
    cuenta = {}
    for f in fichas.values():
        cuenta[f.tecnica] = cuenta.get(f.tecnica, 0) + 1
    return cuenta


def dominio(entradas, tecnica, fichas=None):
    n = _fichas_por_tecnica(fichas).get(tecnica, FICHAS_OK) if fichas else FICHAS_OK
    ventana = [e for e in _ordenadas(entradas) if e.get("tecnica") == tecnica][-VENTANA:]
    return _dominio_de(ventana, tecnica, n)


def grupo_de(entrada):
    """Grupo de cupo de un intento (las entradas antiguas no lo guardan)."""
    g = entrada.get("grupo") or grupo(entrada.get("tipo"))
    return g


def acierto_de_nivel(entrada):
    """Acierto de la prueba de nivel: sin pistas. Es lo unico que la prueba aporta al progreso."""
    return entrada.get("motivo") == "nivel" and bool(entrada.get("correcto")) and not entrada.get("pistas")


def _tecnicas_del_grupo(fichas, g):
    return {f.tecnica: ESCALONES[f.tipo][f.tecnica] for f in fichas.values() if f.grupo == g}


def _escalon_actual(tecnicas, dominadas):
    """Escalon abierto ahora: se sube cuando la mitad (hacia arriba) de las
    tecnicas del escalon actual esta dominada."""
    escalones = sorted(set(tecnicas.values()))
    if not escalones:
        return 1
    for i, e in enumerate(escalones):
        del_escalon = [t for t, x in tecnicas.items() if x == e]
        hechas = sum(1 for t in del_escalon if t in dominadas)
        if hechas < ceil(len(del_escalon) / 2) or i == len(escalones) - 1:
            return e
    return escalones[-1]


@dataclass
class Progreso:
    escalon: dict          # grupo -> escalon maximo alcanzado (hito)
    foco_apagado: bool     # el grupo de foco se domino alguna vez
    dominadas: set         # tecnicas dominadas ahora
    por_nivel: set = field(default_factory=set)   # tecnicas acertadas sin pistas en la prueba de nivel


def ruta_hitos(ruta_registro=None):
    """usuario/datos/progreso.jsonl, junto al registro (en las pruebas, junto al temporal)."""
    from . import registro
    return Path(ruta_registro or registro.RUTA).with_name("progreso.jsonl")


def leer_hitos(ruta=None):
    """grupo -> escalon maximo alcanzado alguna vez. Una linea por subida, solo se
    anade (merge=union entre equipos: se toma el maximo). Si no existe o esta roto,
    {} (se recalcula desde el registro)."""
    import json
    ruta = Path(ruta or ruta_hitos())
    hitos = {}
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hitos
    for linea in lineas:
        try:
            h = json.loads(linea)
            g, e = h["grupo"], int(h["escalon"])
        except (ValueError, KeyError, TypeError):
            continue
        if g in GRUPOS and e >= 1:
            hitos[g] = max(hitos.get(g, 1), e)
    return hitos


def guardar_hitos(escalon, ruta=None):
    """Anade una linea por cada grupo cuyo escalon supera lo guardado. Devuelve
    los hitos resultantes. Un error de disco no para la sesion."""
    from . import registro
    ruta = Path(ruta or ruta_hitos())
    hitos = leer_hitos(ruta)
    for g in GRUPOS:
        if escalon.get(g, 1) > hitos.get(g, 1):
            try:
                registro.anadir({"ts": registro.ahora().isoformat(), "grupo": g, "escalon": escalon[g]}, ruta)
                hitos[g] = escalon[g]
            except (OSError, registro.ErrorRegistro):
                pass
    return hitos


def progreso_al_dia(fichas, entradas, ruta=None):
    """`progreso` con los hitos guardados, y guarda los nuevos: lo usan la cola y el
    cierre, que es cuando se ve subir un escalon."""
    prog = progreso(fichas, entradas, leer_hitos(ruta))
    guardar_hitos(prog.escalon, ruta)
    return prog


def progreso(fichas, entradas, hitos=None):
    """Recorre el registro en orden y guarda el maximo alcanzado: el progreso
    no retrocede aunque un mal dia baje el acierto de la ventana. `hitos`
    (leer_hitos): el maximo guardado por grupo; asi tampoco retrocede si se
    anaden tecnicas a un escalon ya superado."""
    n_fichas = _fichas_por_tecnica(fichas)
    tecnicas = {g: _tecnicas_del_grupo(fichas, g) for g in GRUPOS}
    ventanas = {}
    dominadas = set()
    por_nivel = set()
    escalon = {g: max(_escalon_actual(tecnicas[g], set()), (hitos or {}).get(g, 1)) for g in GRUPOS}
    foco_tecnicas = set(tecnicas.get(FOCO, {}))
    foco_apagado = not foco_tecnicas
    for e in _ordenadas(entradas):
        t = e.get("tecnica")
        if t is None:
            continue
        v = ventanas.setdefault(t, deque(maxlen=VENTANA))
        v.append(e)
        if _dominio_de(list(v), t, n_fichas.get(t, FICHAS_OK)).dominada:
            dominadas.add(t)
        else:
            dominadas.discard(t)
        if acierto_de_nivel(e):
            por_nivel.add(t)  # «competente» para abrir escalones; nunca cuenta como «dominada»
        g = grupo_de(e)
        if g in tecnicas:
            escalon[g] = max(escalon[g], _escalon_actual(tecnicas[g], dominadas | por_nivel))
        if foco_tecnicas and foco_tecnicas <= dominadas:
            foco_apagado = True
    return Progreso(escalon, foco_apagado, set(dominadas), set(por_nivel))


def escalon_abierto(fichas, entradas, tipo):
    return progreso(fichas, entradas).escalon.get(tipo, 1)


def foco_activo(fichas, entradas, prog=None):
    if not FOCO:
        return False
    prog = prog or progreso(fichas, entradas)
    return not prog.foco_apagado


def cupos(fichas, entradas, minimo=False, prog=None):
    if foco_activo(fichas, entradas, prog):
        return dict(CUPO_MINIMO_FOCO if minimo else CUPO_FOCO)
    return dict(CUPO_MINIMO if minimo else CUPO)


def abiertas_por_examen(dia, ruta=None):
    """Tecnicas que un examen cercano abre aunque la escalera no haya llegado."""
    ruta = Path(ruta or CALENDARIO)
    if not ruta.exists():
        return set()
    with open(ruta, "rb") as f:
        datos = tomllib.load(f)
    abiertas = set()
    for ex in datos.get("examen", []):
        inicio = date.fromisoformat(ex["fecha"]) - timedelta(days=ex.get("dias_antes", 14))
        if dia >= inicio:
            abiertas.update(ex.get("tecnicas", []))
    return abiertas


def examenes(ruta=None):
    ruta = Path(ruta or CALENDARIO)
    if not ruta.exists():
        return []
    with open(ruta, "rb") as f:
        return [dict(ex, fecha=date.fromisoformat(ex["fecha"])) for ex in tomllib.load(f).get("examen", [])]


def elegir_examen(dia, nombre=None, ruta=None):
    """El examen pedido por nombre (basta un trozo: «parcial») o el proximo."""
    lista = sorted(examenes(ruta), key=lambda ex: ex["fecha"])
    if nombre:
        encontrados = [ex for ex in lista if nombre.lower() in ex["nombre"].lower()]
        return encontrados[0] if encontrados else None
    futuros = [ex for ex in lista if ex["fecha"] >= dia]
    return futuros[0] if futuros else None


def cola_examen(fichas, entradas, dia, examen, n=5):
    """Sesion extra para preparar un examen (modo examen, estilo mazo filtrado
    de Anki): solo tecnicas del examen, primero lo mas flojo (ya visto y con
    menos retenibilidad), despues fichas nuevas cortas, alternando tecnicas.
    No gasta el cupo diario; se registra con motivo «examen»."""
    tecnicas = examen.get("tecnicas", [])
    tarjetas = estados(entradas)
    hechas_hoy = {e["ficha"] for e in entradas if fecha(e) == dia}
    por_tecnica = {}
    for t in tecnicas:
        vistas = sorted((f for f in fichas.values() if f.tecnica == t and f.id in tarjetas and f.id not in hechas_hoy),
                        key=lambda f: retenibilidad(tarjetas[f.id], dia))
        nuevas = sorted((f for f in fichas.values() if f.tecnica == t and f.id not in tarjetas),
                        key=lambda f: f.larga)  # las largas al final
        if vistas or nuevas:
            por_tecnica[t] = vistas + nuevas
    elegidas = []
    while len(elegidas) < n and any(por_tecnica.values()):
        for t in list(por_tecnica):  # una de cada tecnica por vuelta: practica intercalada
            if not por_tecnica[t] or len(elegidas) >= n:
                continue
            f = por_tecnica[t].pop(0)
            if f.larga and any(x.larga for x in elegidas):
                continue  # como mucho una larga por sesion
            elegidas.append(f)
    return [Elemento(f, zlib.crc32(f"examen:{dia.isoformat()}:{f.id}".encode()), "examen") for f in elegidas]


def cola_simulacro(fichas, entradas, dia, examen, n=4):
    """Fichas de un simulacro cronometrado del examen: solo tecnicas del examen,
    al menos 2 largas si las hay (los problemas gordos del examen real) y el resto
    de tecnicas distintas. La semilla es propia («simulacro») y depende de cuantos
    simulacros se han registrado hoy, para poder repetir el simulacro el mismo dia.
    No gasta el cupo diario; se registra con motivo «simulacro»."""
    tecnicas = set(examen.get("tecnicas", []))
    hechos = sum(1 for e in entradas if fecha(e) == dia and e.get("motivo") == "simulacro")
    rng = random.Random(f"simulacro:{dia.isoformat()}:{examen.get('nombre', '')}:{hechos}")
    pool = sorted((f for f in fichas.values() if f.tecnica in tecnicas), key=lambda f: f.id)
    rng.shuffle(pool)
    largas = [f for f in pool if f.larga]
    cortas = [f for f in pool if not f.larga]
    elegidas, usadas = [], set()

    def tomar(candidatas, tope, distintas=True):
        for f in candidatas:
            if len(elegidas) >= min(n, tope):
                return
            if f in elegidas or (distintas and f.tecnica in usadas):
                continue
            elegidas.append(f)
            usadas.add(f.tecnica)

    tomar(largas, 2)                      # al menos 2 largas (si hay) de tecnicas distintas
    tomar(largas, 2, distintas=False)     # si no hay 2 tecnicas con larga, 2 de la misma
    tomar(cortas, n)                      # el resto: tecnicas distintas
    tomar(cortas, n, distintas=False)
    tomar(largas, n, distintas=False)
    rng.shuffle(elegidas)
    return [Elemento(f, zlib.crc32(f"simulacro:{dia.isoformat()}:{hechos}:{f.id}".encode()), "simulacro")
            for f in elegidas]


# ---------- Prueba de nivel ----------

GRUPOS_NIVEL = ("algebra", "derivada", "integral", "parcial")
NIVEL_N = 10            # ejercicios como maximo
NIVEL_LIMITE = 20       # solo se ofrece con menos intentos que estos (o con --forzar)


def nivel_disponible(entradas):
    """(si_se_ofrece, motivo). Los intentos de la propia prueba no cuentan, para que
    no se corte a mitad."""
    previos = sum(1 for e in entradas if e.get("motivo") != "nivel")
    if previos >= NIVEL_LIMITE:
        return False, f"Ya hay {previos} intentos en el registro (la prueba es para empezar, con menos de {NIVEL_LIMITE})"
    return True, ""


def peldanos_nivel(fichas, g):
    """Escalera de un grupo para la prueba: [(escalon, aciertos_necesarios, [tecnicas])].
    Se piden tantos aciertos como tecnicas hacen falta para abrir el siguiente escalon
    (la mitad, redondeando hacia arriba), cada uno en una tecnica distinta."""
    tecnicas = _tecnicas_del_grupo(fichas, g)
    peldanos = []
    for escalon in sorted(set(tecnicas.values())):
        del_escalon = sorted(t for t, x in tecnicas.items() if x == escalon)
        peldanos.append((escalon, ceil(len(del_escalon) / 2), del_escalon))
    return peldanos


def _estado_nivel(fichas, prueba, g):
    """(detenido, superadas, peldano_actual o None) de un grupo, a partir de los
    intentos de la prueba. Al primer fallo el grupo se detiene."""
    de_g = [e for e in prueba if grupo_de(e) == g]
    detenido = any(not acierto_de_nivel(e) for e in de_g)
    superadas = {e["tecnica"] for e in de_g if acierto_de_nivel(e)}
    actual = next((p for p in peldanos_nivel(fichas, g)
                   if sum(1 for t in p[2] if t in superadas) < p[1]), None)
    return detenido, superadas, actual, len(de_g)


def siguiente_nivel(fichas, entradas, dia, n=NIVEL_N):
    """Siguiente ejercicio de la prueba de nivel de `dia`, o None si ha terminado.

    Adaptativa y derivada del registro (los intentos de hoy con motivo «nivel»), asi
    que se puede parar y seguir, y por linea de comandos va de uno en uno. Empieza por el
    escalon 1 de cada grupo (algebra, derivadas, integrales, parciales) y reparte por
    turnos; un grupo sube de escalon cuando se superan sus peldanos y se detiene al
    primer fallo. Sin pistas. Termina a los `n` ejercicios o cuando ningun grupo puede seguir."""
    prueba = [e for e in _ordenadas(entradas) if fecha(e) == dia and e.get("motivo") == "nivel"]
    if len(prueba) >= n:
        return None
    candidatos = []
    for orden, g in enumerate(GRUPOS_NIVEL):
        detenido, superadas, actual, hechos = _estado_nivel(fichas, prueba, g)
        if not detenido and actual is not None:
            candidatos.append((hechos, orden, g, superadas, actual))
    if not candidatos:
        return None
    hechos, _, g, superadas, (escalon, _, tecnicas) = min(candidatos, key=lambda c: c[:2])
    rng = random.Random(f"nivel:{dia.isoformat()}:{g}:{escalon}:{hechos}")
    tecnica = rng.choice([t for t in tecnicas if t not in superadas])
    posibles = [f for f in fichas.values() if f.tecnica == tecnica and f.grupo == g]
    # lo mas sencillo: ni larga, ni con requisitos, ni de las que repiten la tecnica en otro tipo
    clave = lambda f: (f.larga, bool(f.requiere), f.tipo == "definida")
    mejor = min(clave(f) for f in posibles)
    ficha = rng.choice(sorted((f for f in posibles if clave(f) == mejor), key=lambda f: f.id))
    return Elemento(ficha, zlib.crc32(f"nivel:{dia.isoformat()}:{ficha.id}".encode()), "nivel")


def resumen_nivel(fichas, entradas, dia):
    """Resultado de la prueba de `dia`: por grupo, ejercicios, aciertos, tecnicas superadas,
    si se detuvo, y el escalon abierto antes y despues (el progreso es un hito)."""
    prueba = [e for e in _ordenadas(entradas) if fecha(e) == dia and e.get("motivo") == "nivel"]
    antes = progreso(fichas, [e for e in entradas if e.get("motivo") != "nivel" or fecha(e) != dia]).escalon
    despues = progreso(fichas, entradas).escalon
    grupos = {}
    for g in GRUPOS_NIVEL:
        de_g = [e for e in prueba if grupo_de(e) == g]
        if not de_g:
            continue
        detenido, superadas, _, _ = _estado_nivel(fichas, prueba, g)
        grupos[g] = {"ejercicios": len(de_g), "aciertos": sum(1 for e in de_g if acierto_de_nivel(e)),
                     "superadas": sorted(superadas), "detenido": detenido,
                     "escalon_antes": antes.get(g, 1), "escalon_despues": despues.get(g, 1)}
    return {"ejercicios": len(prueba), "grupos": grupos}


def atascadas(entradas, dia=None):
    """Fichas con ATASCO fallos seguidos: se apartan PAUSA_ATASCO dias (para
    repasar antes el algebra previa) y luego vuelven. Nunca se pierden."""
    por_ficha = {}
    for e in _ordenadas(entradas):
        por_ficha.setdefault(e["ficha"], []).append(e)
    resultado = set()
    for fid, lista in por_ficha.items():
        ultimas = lista[-ATASCO:]
        if len(ultimas) == ATASCO and all(e["nota"] == 1 for e in ultimas):
            if dia is None or (dia - fecha(ultimas[-1])).days < PAUSA_ATASCO:
                resultado.add(fid)
    return resultado


def semilla(dia, ficha_id):
    return zlib.crc32(f"{dia.isoformat()}:{ficha_id}".encode())


@dataclass
class Elemento:
    ficha: object
    semilla: int
    motivo: str   # "repaso", "nueva", "refuerzo" o "previa"


def _cumple_requisitos(ficha, aciertos_por_tecnica):
    return all(aciertos_por_tecnica.get(t, 0) >= 1 for t in ficha.requiere)


def cola(fichas, entradas, dia, minimo=False, calendario=None, hitos=None):
    """Ejercicios de hoy, nunca mas que el cupo:
    1. repasos vencidos (los mas olvidados primero);
    2. al menos una ficha nueva si el atraso es pequeno (primero las que abre
       un examen cercano, despues las del escalon actual);
    3. si sobra sitio, refuerzo de fichas ya vistas (las menos recordadas).
    El primer ejercicio es el mas seguro: un repaso ya acertado o lo mas facil."""
    tarjetas = estados(entradas)
    prog = progreso(fichas, entradas, hitos)
    hechas_hoy = {e["ficha"] for e in entradas if fecha(e) == dia}
    apartadas = atascadas(entradas, dia)
    examen = abiertas_por_examen(dia, calendario)
    aciertos = {}
    for e in entradas:
        if e["nota"] >= 3:
            aciertos[e.get("tecnica")] = aciertos.get(e.get("tecnica"), 0) + 1
    cupo = cupos(fichas, entradas, minimo, prog)
    # Un repaso vencido nunca se queda sin sitio: si su grupo no tiene plaza hoy
    # (p. ej. derivadas durante el foco), se le cede una del grupo con mas.
    for g in GRUPOS:
        if cupo[g] == 0 and any(f.grupo == g and fid in tarjetas and fid not in hechas_hoy
                                and fecha_proxima(tarjetas[fid]) <= dia for fid, f in fichas.items()):
            donante = max((x for x in GRUPOS if x != "algebra"), key=lambda x: cupo[x])
            if cupo[donante] > 1:
                cupo[donante] -= 1
                cupo[g] = 1
    elegidos = {}
    hay_larga = False
    for g in ("integral", "parcial", "derivada", "algebra"):
        # Lo practicado en modo examen o simulacro es extra: no gasta el cupo del dia.
        plazas = cupo[g] - sum(1 for e in entradas if fecha(e) == dia and grupo_de(e) == g
                               and e.get("motivo") not in MOTIVOS_EXTRA)
        if plazas <= 0:
            elegidos[g] = []
            continue
        disponibles = {fid: f for fid, f in fichas.items()
                       if f.grupo == g and fid not in hechas_hoy and fid not in apartadas}
        vencidas = sorted(
            (f for fid, f in disponibles.items() if fid in tarjetas and fecha_proxima(tarjetas[fid]) <= dia),
            key=lambda f: retenibilidad(tarjetas[f.id], dia),
        )
        if plazas >= 2:
            vencidas = _intercalar(vencidas)  # practica intercalada tambien en los repasos
        abierto = prog.escalon.get(g, 1)
        candidatas = [f for fid, f in disponibles.items()
                      if fid not in tarjetas and (f.escalon <= abierto or f.tecnica in examen)
                      and _cumple_requisitos(f, aciertos)]
        nuevas = _ordenar_nuevas(candidatas, abierto, examen)
        if vencidas or hay_larga:
            nuevas = [f for f in nuevas if not f.larga]  # una larga solo si no hay repasos
        reserva = 1 if plazas >= 2 else 0
        lista = [Elemento(f, 0, "repaso") for f in vencidas[:plazas - reserva]]
        atraso_ok = len(vencidas) <= 2 * plazas
        if nuevas and atraso_ok and len(lista) < plazas:
            lista.append(Elemento(nuevas.pop(0), 0, "nueva"))
        for f in vencidas[len([x for x in lista if x.motivo == "repaso"]):]:
            if len(lista) >= plazas:
                break
            lista.append(Elemento(f, 0, "repaso"))
        while len(lista) < plazas and nuevas and atraso_ok:
            lista.append(Elemento(nuevas.pop(0), 0, "nueva"))
        if len(lista) < plazas:
            ya = {x.ficha.id for x in lista}
            refuerzo = sorted((f for fid, f in disponibles.items() if fid in tarjetas and fid not in ya),
                              key=lambda f: retenibilidad(tarjetas[f.id], dia))
            lista += [Elemento(f, 0, "refuerzo") for f in refuerzo[:plazas - len(lista)]]
        elegidos[g] = lista
        hay_larga = hay_larga or any(x.ficha.larga for x in lista)
    # Ficha atascada: el calentamiento de algebra de hoy es su ficha previa.
    if elegidos["algebra"]:
        previa = _previa_de_atascadas(fichas, apartadas, hechas_hoy)
        if previa is not None:
            elegidos["algebra"] = [Elemento(previa, 0, "previa")]
    # Dia largo: una integral larga ocupa el dia de integrales.
    largas = [x for x in elegidos["integral"] if x.ficha.larga]
    if largas and not minimo:
        elegidos["integral"] = largas[:1]
    resultado = elegidos["algebra"] + elegidos["parcial"] + elegidos["derivada"] + elegidos["integral"]
    resultado = _primero_lo_seguro(resultado, tarjetas, entradas, dia)
    for x in resultado:
        x.semilla = semilla(dia, x.ficha.id)
    return resultado


def _intercalar(vencidas):
    """Reordena los repasos (ya por retenibilidad) para que los primeros sean de
    tecnicas distintas: la mas olvidada y, despues, la mas olvidada de otra
    tecnica. Solo se salta la prioridad lo imprescindible."""
    pendientes, orden, vistas = list(vencidas), [], set()
    while pendientes:
        f = next((x for x in pendientes if x.tecnica not in vistas), pendientes[0])
        pendientes.remove(f)
        orden.append(f)
        vistas.add(f.tecnica)
        if not any(x.tecnica not in vistas for x in pendientes):
            vistas = set()  # todas las tecnicas restantes ya salieron: nueva ronda
    return orden


def _previa_de_atascadas(fichas, apartadas, hechas_hoy):
    """Ficha de algebra `previa` de la primera ficha atascada que la tenga y que hoy
    aun no se haya hecho (en orden de id, para que sea estable)."""
    for fid in sorted(apartadas):
        f = fichas.get(fid)
        if f is not None and f.previa and f.previa in fichas and f.previa not in hechas_hoy:
            return fichas[f.previa]
    return None


def _ordenar_nuevas(candidatas, abierto, examen):
    """Orden de las fichas nuevas de un grupo:
    - primero la escalera (el escalon abierto mas alto, en el orden del temario);
    - como mucho una ficha que abra un examen, en segundo lugar;
    - sin repetir tecnica mientras haya otras."""
    escalera = sorted((f for f in candidatas if f.escalon <= abierto), key=lambda f: -f.escalon)
    por_examen = [f for f in candidatas if f.escalon > abierto]
    orden = escalera[:1] + por_examen[:1] + escalera[1:]
    resultado, vistas = [], set()
    for f in orden:  # primera pasada: una por tecnica
        if f.tecnica not in vistas:
            resultado.append(f)
            vistas.add(f.tecnica)
    resultado += [f for f in orden if f not in resultado]
    return resultado


def _primero_lo_seguro(resultado, tarjetas, entradas, dia):
    """Empieza por el ejercicio con mas probabilidad de salir."""
    if len(resultado) < 2:
        return resultado
    ultima_nota = {}
    for e in _ordenadas(entradas):
        ultima_nota[e["ficha"]] = e["nota"]

    def seguridad(x):
        f = x.ficha
        if f.id in tarjetas and ultima_nota.get(f.id, 0) >= 3:
            return (0, -retenibilidad(tarjetas[f.id], dia))
        if x.motivo == "nueva" and f.tipo != "algebra" and not f.larga:
            return (1, f.escalon)
        return (2, 0)

    primero = min(resultado, key=seguridad)
    if seguridad(primero)[0] == 2:
        return resultado
    return [primero] + [x for x in resultado if x is not primero]


MIN_CALIBRACION = 400   # repasos antes de fiarse de la calibracion
TRAMOS = [(0.0, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.01)]


def calibracion(entradas):
    """Compara la retenibilidad que FSRS predecia justo antes de cada repaso
    con lo que paso (recuerdo = nota >= 2, como en FSRS: con pista tambien es
    recordar algo; el dominio, en cambio, cuenta la nota 2 como medio acierto).

    Devuelve (n_repasos, [(tramo, n, predicho_medio, real)], desviacion_media)
    con la desviacion ponderada por n en puntos porcentuales."""
    pares = []

    def anotar(e, momento, previa):
        if previa is not None:
            pares.append((PLANIFICADOR.get_card_retrievability(previa, momento), e["nota"] >= 2))

    # Solo los repasos reales son muestras; el estado de la tarjeta si incluye la repeticion implicita.
    _reproducir(entradas, antes=anotar)
    filas = []
    for lo, hi in TRAMOS:
        grupo_ = [(r, ok) for r, ok in pares if lo <= r < hi]
        if grupo_:
            pred = sum(r for r, _ in grupo_) / len(grupo_)
            real = sum(ok for _, ok in grupo_) / len(grupo_)
            filas.append(((lo, min(hi, 1.0)), len(grupo_), pred, real))
    desviacion = (sum(n * abs(p - r) for _, n, p, r in filas) / len(pares) * 100) if pares else None
    return len(pares), filas, desviacion


def carga_prevista(fichas, entradas, desde, dias=7):
    """Repasos que venceran cada dia (sin contar fichas nuevas)."""
    tarjetas = estados(entradas)
    cuenta = {desde + timedelta(d): 0 for d in range(dias)}
    for fid, t in tarjetas.items():
        if fid in fichas:
            dia = max(fecha_proxima(t), desde)
            if dia in cuenta:
                cuenta[dia] += 1
    return cuenta
