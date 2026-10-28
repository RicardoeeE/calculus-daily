"""Revision semanal: sensaciones, quejas, reclamaciones y resumen de la semana.

Todo queda en `usuario/datos/notas.jsonl` (solo se anade) y en
`usuario/revisiones/AAAA-MM-DD.md`. Quien revise (el propio alumno o un profesor)
empieza por `pendientes` (quejas y reclamaciones sin resolver) y las cierra con
`resolver`.
"""
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from . import registro
from .rutas import DATOS, USUARIO

NOTAS = DATOS / "notas.jsonl"
REVISIONES = USUARIO / "revisiones"

# Causa que declara el alumno cuando falla o se rinde (una tecla).
CAUSAS = {
    "1": "no sabia por donde empezar",
    "2": "elegi la tecnica pero me lie en un paso",
    "3": "algebra o una cuenta",
    "4": "signo o constante",
    "5": "creo que estaba bien (reclamacion)",
}
SENSACIONES = {1: "fatal", 2: "mal", 3: "normal", 4: "bien", 5: "genial"}


def leer_notas(ruta=None):
    ruta = Path(ruta or NOTAS)
    if not ruta.exists():
        return []
    notas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            notas.append(json.loads(linea))
        except ValueError:
            continue
    return notas


def anotar(tipo, ruta=None, **campos):
    """tipo: sensacion, queja, reclamo o resolucion. Devuelve la nota con su id."""
    ahora = registro.ahora()
    nota = {"id": f"{tipo[0].upper()}-{ahora.strftime('%Y%m%d-%H%M%S')}", "ts": ahora.isoformat(),
            "tipo": tipo, **campos}
    existentes = {n["id"] for n in leer_notas(ruta)}
    base, i = nota["id"], 1
    while nota["id"] in existentes:
        i += 1
        nota["id"] = f"{base}-{i}"
    registro.anadir(nota, Path(ruta or NOTAS))
    return nota


def pendientes(ruta=None, notas=None):
    """Quejas y reclamaciones sin resolver, de la mas antigua a la mas nueva."""
    notas = leer_notas(ruta) if notas is None else notas
    resueltas = {n.get("resuelve") for n in notas if n["tipo"] == "resolucion"}
    return [n for n in notas if n["tipo"] in ("queja", "reclamo") and n["id"] not in resueltas]


def resolver(id_, texto, ruta=None, rechazar=False, aceptar=False, ruta_registro=None):
    """Cierra una queja o reclamacion. En una reclamacion, `rechazar` (la respuesta
    estaba mal) o `aceptar` (estaba bien) anaden al registro una entrada correctora
    (motivo «correccion», nota 1 o 3) que sustituye la nota provisional 2 del
    intento reclamado: registro.leer la aplica, asi que FSRS, el dominio y los
    informes la ven. Sin ninguno de los dos, solo se cierra (la nota 2 se queda)."""
    if rechazar and aceptar:
        raise ValueError("o --rechazar o --aceptar, no los dos")
    nota = next((n for n in pendientes(ruta) if n["id"] == id_), None)
    if nota is None:
        raise KeyError(f"no hay ninguna queja o reclamacion pendiente con id {id_}")
    campos = {"resuelve": id_, "texto": texto}
    if rechazar or aceptar:
        if nota["tipo"] != "reclamo":
            raise ValueError("--rechazar y --aceptar son solo para reclamaciones")
        original = registro.reclamado(nota["ficha"], nota.get("semilla"), ruta_registro)
        if original is None:
            raise KeyError(f"no encuentro en el registro el intento reclamado de {nota['ficha']}")
        registro.anadir(registro.correccion(original, aceptar, texto), ruta_registro)
        campos["decision"] = "aceptada" if aceptar else "rechazada"
    return anotar("resolucion", ruta, **campos)


# ---------- Revision semanal ----------

def ultima_revision(carpeta=None):
    carpeta = Path(carpeta or REVISIONES)
    fechas = []
    for r in carpeta.glob("*.md") if carpeta.exists() else []:
        try:
            fechas.append(date.fromisoformat(r.stem))
        except ValueError:
            continue
    return max(fechas) if fechas else None


def toca_revision(dia, entradas, carpeta=None):
    """Una vez por semana, si desde la anterior hay al menos 3 dias practicados."""
    ultima = ultima_revision(carpeta)
    if ultima and (dia - ultima).days < 7:
        return False
    desde = ultima or date.min
    dias = {registro.fecha(e) for e in entradas if desde < registro.fecha(e) < dia}
    return len(dias) >= 3


def _porcentaje(a, b):
    return f"{a / b:.0%}" if b else "-"


def revision(dia, fichas, entradas=None, notas=None, carpeta=None, escribir=True):
    """Genera la revision semanal de los ultimos 7 dias (o desde la anterior)."""
    from .planificador import dominio, leer_hitos, progreso  # evita ciclos al importar
    entradas = registro.leer() if entradas is None else entradas
    notas = leer_notas() if notas is None else notas
    carpeta = Path(carpeta or REVISIONES)
    ultima = ultima_revision(carpeta)
    desde = ultima if ultima and ultima < dia else dia - timedelta(days=7)
    periodo = [e for e in entradas if desde <= registro.fecha(e) <= dia]
    anterior = [e for e in entradas if desde - timedelta(days=7) <= registro.fecha(e) < desde]
    n_ses = [n for n in notas if n["tipo"] == "sensacion" and desde.isoformat() <= n["ts"][:10] <= dia.isoformat()]
    l = [f"# Revision semanal {dia.isoformat()}", "",
         f"Periodo: {desde.isoformat()} a {dia.isoformat()}. Generada por el motor.", ""]

    dias = len({registro.fecha(e) for e in periodo})
    auto = sum(1 for e in periodo if e["nota"] >= 3)
    auto_ant = sum(1 for e in anterior if e["nota"] >= 3)
    l += ["## 1. Resumen", "",
          "| Que | Este periodo | Periodo anterior |", "|---|---|---|",
          f"| Dias practicados | {dias} | {len({registro.fecha(e) for e in anterior})} |",
          f"| Ejercicios | {len(periodo)} | {len(anterior)} |",
          f"| Sin ayuda | {_porcentaje(auto, len(periodo))} | {_porcentaje(auto_ant, len(anterior))} |", ""]

    l += ["## 2. Por tecnica", "", "| Tecnica | Intentos | Sin ayuda | Dominada |", "|---|---|---|---|"]
    por_tecnica = Counter(e.get("tecnica") for e in periodo)
    for t, n in por_tecnica.most_common():
        a = sum(1 for e in periodo if e.get("tecnica") == t and e["nota"] >= 3)
        l.append(f"| {t} | {n} | {a} | {'si' if dominio(entradas, t, fichas).dominada else 'no'} |")
    prog = progreso(fichas, entradas, leer_hitos())
    l += ["", "Escalones alcanzados: " + ", ".join(f"{g} {e}" for g, e in prog.escalon.items()), ""]

    fallos = [e for e in periodo if e["nota"] <= 2]
    causas = Counter(e.get("causa") for e in fallos if e.get("causa"))
    diagnosticos = Counter(d.split(":")[0] for e in fallos for d in e.get("diagnostico", []))
    l += ["## 3. Fallos y por que", ""]
    if not fallos:
        l.append("Sin fallos en el periodo.")
    else:
        l.append(f"{len(fallos)} ejercicios con fallo o ayuda.")
        if causas:
            l += ["", "Causas declaradas:"] + [f"- {c}: {n}" for c, n in causas.most_common()]
        if diagnosticos:
            l += ["", "Lo que detecto el motor:"] + [f"- {d}: {n}" for d, n in diagnosticos.most_common(6)]
        duras = Counter(e["ficha"] for e in fallos).most_common(3)
        l += ["", "Fichas que mas cuestan: " + ", ".join(f"{f} ({n})" for f, n in duras)]
    l.append("")

    l += ["## 4. Sensaciones", ""]
    if n_ses:
        media = sum(n["valor"] for n in n_ses) / len(n_ses)
        l.append(f"Media {media:.1f}/5 en {len(n_ses)} sesiones ({SENSACIONES[round(media)]}).")
        comentarios = [n for n in n_ses if n.get("texto")]
        l += [f"- {n['ts'][:10]}: «{n['texto']}»" for n in comentarios]
    else:
        l.append("Sin sensaciones registradas.")
    con = [e for e in periodo if e.get("confianza")]
    if con:
        dicho = sum(e["confianza"] for e in con) / len(con)
        acierto = sum(1 for e in con if e["nota"] >= 3) / len(con)
        l.append(f"Confianza media {dicho:.1f}/5 y acierto sin ayuda {acierto:.0%}.")
    l.append("")

    pend = [n for n in pendientes(notas=notas) if n["ts"][:10] <= dia.isoformat()]
    l += ["## 5. Quejas y reclamaciones pendientes", ""]
    if pend:
        l += [f"- {n['id']} ({n['tipo']}): {n.get('texto') or n.get('respuesta', '')}"
              + (f" — ficha {n['ficha']}, respuesta «{n.get('respuesta')}»" if n["tipo"] == "reclamo" else "")
              for n in pend]
    else:
        l.append("Ninguna.")
    l.append("")

    l += ["## 6. Recomendaciones (automaticas)", ""] + [f"- {r}" for r in _recomendaciones(
        periodo, dias, causas, n_ses, pend, auto)] + [""]
    l += ["## 7. Para quien revise", "",
          "- Empezar por `python programa\\practica.py pendientes` y cerrar cada una con `resolver`.",
          "- Una reclamacion es una respuesta que el alumno cree correcta: comprobarla a mano. Si el lector la leyo mal, arreglarlo y anadir una prueba.",
          "- Repasar los fallos de la seccion 3 que repiten causa.", ""]
    texto = "\n".join(l)
    if escribir:
        carpeta.mkdir(exist_ok=True)
        (carpeta / f"{dia.isoformat()}.md").write_text(texto, encoding="utf-8")
    return texto


def _recomendaciones(periodo, dias, causas, sensaciones, pend, autonomos):
    r = []
    if dias <= 2:
        r.append("Pocos dias de practica: mejor el dia minimo (`--minimo`, 2 ejercicios) que saltarse el dia.")
    if sensaciones and sum(n["valor"] for n in sensaciones) / len(sensaciones) <= 2:
        r.append("Las sensaciones van bajas: unos dias de dia minimo y empezar por repasos que ya salen.")
    if causas.get(CAUSAS["3"], 0) + causas.get(CAUSAS["4"], 0) >= 3:
        r.append("Muchos fallos de algebra, signo o constante: antes de dar el resultado, derivarlo para comprobar.")
    if causas.get(CAUSAS["1"], 0) >= 3:
        r.append("Varias veces sin saber empezar: repasar la hoja de reconocimiento (programa/docs/hoja-reconocer.md) antes de cada integral y pedir la pista 1.")
    if periodo and autonomos / len(periodo) >= 0.8:
        r.append("Mas del 80 % sin ayuda: vas bien. El motor abrira las siguientes tecnicas solo.")
    if pend:
        r.append(f"Hay {len(pend)} quejas o reclamaciones sin resolver: `practica.py pendientes` las lista.")
    return r or ["Seguir igual: el ritmo y el acierto estan bien."]
