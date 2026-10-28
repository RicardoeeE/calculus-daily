"""Practica diaria de derivadas, integrales y EDOs.

Uso en la terminal:
  python practica.py hoy [--minimo] [--sin-git]   sesion interactiva (5 ejercicios; minimo: 2)
  python practica.py ventana [--minimo]   la misma sesion en una ventana (sale con 3 si no se puede abrir)
  pythonw practica.py ventana --respaldo-terminal   (Practicar.bat) sin consola; si no abre, Terminal.bat
  python practica.py informe            progreso, examenes, confianza y repasos previstos
  python practica.py doctor [--rapido]  comprueba instalacion, fichas, registro, git y datos
  python practica.py datos [--recuperar] [--copiar]   tus datos: intentos, copias y si falta algo
  python practica.py queja "texto"      anotar una queja o comentario
  python practica.py sensacion N ["..."]  como te has sentido (1-5)
  python practica.py revision           revision de la semana (se genera sola los lunes)
  python practica.py examen [--nombre Parcial] [--n 5]   sesion extra del proximo examen (no gasta el cupo)
  python practica.py simulacro [--nombre Parcial] [--n 4] [--minutos 40]   simulacro cronometrado, sin pistas
  python practica.py nivel [--n 10] [--forzar]   prueba de nivel adaptativa (solo con menos de 20 intentos)

Modo revisor (salida JSON, un paso cada vez; para scripts o para quien acompane la sesion):
  python practica.py cola [--minimo]
  python practica.py simulacro --cola [--nombre Parcial] [--n 4] [--minutos 40]   (JSON; se registra con motivo «simulacro»)
  python practica.py nivel --cola [--forzar]   (JSON: el SIGUIENTE ejercicio de la prueba de nivel; [] al acabar; motivo «nivel»)
  python practica.py comprobar ID SEMILLA "respuesta"
  python practica.py pista ID SEMILLA NIVEL          (1-4; el motor anota las pistas vistas)
  python practica.py registrar ID SEMILLA --confianza N [--respuesta "..."] [--rendido] [--segundos S]
  python practica.py cerrar [--sin-git]
  python practica.py pendientes         quejas y reclamaciones sin resolver
  python practica.py resolver ID "texto" [--rechazar | --aceptar]   (reclamaciones: corrige la nota provisional 2)
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import date
from math import ceil
from pathlib import Path

from calculo import registro, rutas

try:
    from calculo.fichas import cargar
    from calculo.planificador import (
        NIVEL_N, cola_examen, cola_simulacro, elegir_examen, nivel_disponible, resumen_nivel, siguiente_nivel,
    )
    from calculo.sesion import YaRegistrado, cerrar, comprobar, informe, informe_simulacro, registrar
    from calculo.diagnostico import diagnosticar
    from calculo import servicio, tutela
    from calculo.servicio import AYUDA_TIPO as _AYUDA_TIPO, ETIQUETAS as _ETIQUETAS
    from calculo.servicio import ejemplo_con_huecos
    from calculo.huecos import recortar
    from calculo.ver import ver_ficha
    _FALTA = None
except ImportError as exc:  # falta sympy o fsrs: `doctor` lo explica
    _FALTA = exc

CACHE = rutas.CACHE
# Campos del JSON de `cola`, en este orden.
_CAMPOS_COLA = ("ficha", "semilla", "motivo", "tipo", "tecnica", "larga", "enunciado", "como_responder", "fuente",
                "ejemplo")


def _servicio(fichas=None, seguro=False):
    """La sesion del motor (calculo/servicio.py) sobre la .cache de aqui. La
    terminal ve las excepciones reales (seguro=False). `registrar` y los ejemplos
    se buscan en este modulo al llamarlos, para que las pruebas puedan simularlos."""
    return servicio.Sesion(fichas, cache=CACHE, seguro=seguro,
                           registrar=lambda *a, **k: registrar(*a, **k),
                           ejemplo=lambda *a, **k: ejemplo_con_huecos(*a, **k))


def _ruta_cache(nombre):
    return servicio.ruta_cache(CACHE, nombre)


def cola_de_hoy(fichas, dia, minimo=False):
    """La cola del dia, fijada en .cache (ver servicio.cola_guardada)."""
    return servicio.cola_guardada(CACHE, fichas, dia, minimo)


def anotar_pista(dia, ficha_id, semilla, nivel):
    """El motor recuerda la pista mas alta pedida, para que la nota no dependa
    de lo que se declare al registrar."""
    servicio.anotar(CACHE, "pistas", dia, ficha_id, semilla, lambda n: max(n, nivel))


def pistas_anotadas(dia, ficha_id, semilla):
    return servicio.leer_anotacion(CACHE, "pistas", dia, ficha_id, semilla)


def anotar_fallo(dia, ficha_id, semilla):
    """Cada `comprobar` que no cuadra cuenta: acertar despues vale como mucho 2."""
    servicio.anotar(CACHE, "fallos", dia, ficha_id, semilla, lambda n: n + 1)


def fallos_anotados(dia, ficha_id, semilla):
    return servicio.leer_anotacion(CACHE, "fallos", dia, ficha_id, semilla)


def motivo_en_cola(dia, ficha_id, semilla):
    return servicio.motivo_en_cola(CACHE, dia, ficha_id, semilla)


def _variante(fichas, ficha_id, semilla):
    if ficha_id not in fichas:
        sys.exit(f"No existe la ficha {ficha_id}")
    try:
        return fichas[ficha_id].variante(int(semilla))
    except ValueError:
        sys.exit(f"La semilla debe ser un numero entero (se ha recibido «{semilla}»)")


def _pedir_confianza():
    while True:
        t = input("  Confianza 1-5 (¿la sacas?): ").strip()
        if t in {"1", "2", "3", "4", "5"}:
            return int(t)
        if t == "q":
            raise KeyboardInterrupt
        print("  Escribe un numero del 1 al 5 (o q para parar).")


def sesion_examen(fichas, dia, nombre=None, n=5, git=True):
    """Modo examen: sesion extra con las tecnicas del proximo examen."""
    ex = elegir_examen(dia, nombre)
    if ex is None:
        print("No hay ningun examen proximo en fichas/calendario.toml.")
        return
    lista = cola_examen(fichas, registro.leer(), dia, ex, n)
    faltan = (ex["fecha"] - dia).days
    print(f"Modo examen: {ex['nombre']} ({ex['fecha'].strftime('%d/%m')}, faltan {faltan} dias).")
    print(f"{len(lista)} ejercicios extra de: {', '.join(ex.get('tecnicas', []))}. No gastan el cupo de hoy.")
    print("Escribe  p  pista,  s  ver la solucion,  v  ver la grafica,  r  reclamar,  q  parar.\n")
    hechos, vistas, s = [], set(), _servicio(fichas)
    try:
        for i, x in enumerate(lista, 1):
            _un_ejercicio(fichas, {"ficha": x.ficha.id, "semilla": x.semilla, "motivo": "examen"}, i, len(lista),
                          vistas, s)
            hechos.append(x.ficha)
    except (KeyboardInterrupt, EOFError):
        print("\nSesion parada. Lo hecho queda guardado.")
    if hechos:
        hoy = [e for e in registro.leer() if registro.fecha(e) == date.today() and e.get("motivo") == "examen"]
        print("Preparacion por tecnica (esta sesion):")
        for t in sorted({f.tecnica for f in hechos}):
            de_t = [e for e in hoy if e.get("tecnica") == t]
            print(f"  - {t}: {sum(1 for e in de_t if e['nota'] >= 3)}/{len(de_t)} sin ayuda")
        print(cerrar(date.today(), fichas, git=git))


def _hecho_hoy(dia):
    return {(e["ficha"], e.get("semilla")) for e in registro.leer() if registro.fecha(e) == dia}


def cola_simulacro_json(fichas, dia, nombre=None, n=4, minutos=40):
    """Modo revisor: los ejercicios del simulacro, fijados en .cache para que
    `registrar` les ponga el motivo «simulacro». Si aun quedan ejercicios sin
    registrar del simulacro ya pedido hoy, se devuelve ese mismo."""
    ex = elegir_examen(dia, nombre)
    if ex is None:
        return []
    ruta = _ruta_cache(f"simulacro-{dia.isoformat()}.json")
    hechas = _hecho_hoy(dia)
    guardada = registro.leer_json(ruta, [])
    if not any((g["ficha"], g["semilla"]) not in hechas and g["ficha"] in fichas for g in guardada):
        guardada = [{"ficha": x.ficha.id, "semilla": x.semilla}
                    for x in cola_simulacro(fichas, registro.leer(), dia, ex, n)]
        registro.escribir_json(ruta, guardada)
    salida = []
    for g in guardada:
        if (g["ficha"], g["semilla"]) in hechas or g["ficha"] not in fichas:
            continue
        v = _variante(fichas, g["ficha"], g["semilla"])
        salida.append({**g, "motivo": "simulacro", "examen": ex["nombre"], "minutos": minutos,
                       "tecnica": v.ficha.tecnica, "larga": v.ficha.larga, "enunciado": v.enunciado,
                       "como_responder": _AYUDA_TIPO.get(v.ficha.tipo, "")})
    return salida


def sesion_simulacro(fichas, dia, nombre=None, n=4, minutos=40, git=True):
    """Simulacro cronometrado: condiciones de examen. Sin pistas ni correccion
    durante la prueba; una sola respuesta por ejercicio; si se acaba el tiempo,
    los que falten quedan sin responder (no se registran). Al final se corrige
    todo y se guarda un informe en usuario/simulacros/."""
    ex = elegir_examen(dia, nombre)
    if ex is None:
        print("No hay ningun examen proximo en fichas/calendario.toml.")
        return
    lista = cola_simulacro(fichas, registro.leer(), dia, ex, n)
    if not lista:
        print("No hay fichas de las tecnicas de ese examen.")
        return
    total = len(lista)
    print(f"Simulacro: {ex['nombre']} ({ex['fecha'].strftime('%d/%m')}). {total} ejercicios, {minutos} minutos.")
    print("Condiciones de examen: sin pistas ni correccion hasta el final. Una sola respuesta por ejercicio.")
    print("Enter vacio = dejar en blanco el ejercicio,  q = entregar ya. No gasta el cupo de hoy.\n")
    try:
        if input("Pulsa Enter para empezar el cronometro (q para salir): ").strip() == "q":
            return
    except (KeyboardInterrupt, EOFError):
        return
    limite = minutos * 60
    inicio = time.monotonic()
    resultados, entregado = [], False
    for i, x in enumerate(lista, 1):
        v = x.ficha.variante(x.semilla)
        r = {"ficha": x.ficha.id, "tecnica": x.ficha.tecnica, "enunciado": v.enunciado, "respuesta": None,
             "estado": "sin responder", "solucion": v.respuesta_modelo, "diagnostico": []}
        resultados.append(r)
        if entregado:
            continue
        restante = limite - (time.monotonic() - inicio)
        if restante <= 0:
            print(f"Se acabo el tiempo: del ejercicio {i} al {total} quedan sin responder.")
            entregado = True
            continue
        print(f"[{i}/{total}] Quedan {ceil(restante / 60)} min.  {v.enunciado}")
        if v.ficha.tipo in _AYUDA_TIPO:
            print(f"  ({_AYUDA_TIPO[v.ficha.tipo]})")
        desde = time.monotonic()
        try:
            while True:
                t = input("  Resultado: ").strip()
                lectura = comprobar(v, t) if t and t != "q" else None
                if lectura is None or not lectura.error:
                    break
                # Como en la prueba de nivel: no se corrige, pero lo ilegible se reescribe.
                print(f"  No lo leo: {lectura.error}.")
        except (KeyboardInterrupt, EOFError):
            entregado = True
            continue
        hasta = time.monotonic()
        if hasta - inicio > limite:
            print("  Se acabo el tiempo antes de entregar esta respuesta: no cuenta.")
            entregado = True
            continue
        if t == "q":
            entregado = True
            continue
        if not t:
            continue
        try:
            entrada, _ = registrar(v, t, None, 0, round(hasta - desde), motivo="simulacro")
        except YaRegistrado:
            continue
        diag = [] if entrada["correcto"] else diagnosticar(v, t)
        r.update(respuesta=t, estado="correcto" if entrada["correcto"] else "incorrecto", diagnostico=diag)
    usados = min(time.monotonic() - inicio, limite)
    print(f"\nSimulacro entregado. Tiempo usado: {int(usados) // 60}:{int(usados) % 60:02d} de {minutos}:00.\n")
    for i, r in enumerate(resultados, 1):
        print(f"{i}. {r['ficha']} ({r['tecnica']}): {r['estado'].upper()}")
        print(f"   {r['enunciado']}")
        if r["respuesta"]:
            print(f"   Tu respuesta: {r['respuesta']}")
        print(f"   Solucion: {r['solucion']}")
        for d in r["diagnostico"]:
            print(f"   El motor ve: {d}")
    bien = sum(1 for r in resultados if r["estado"] == "correcto")
    print(f"\nNota: {bien}/{total} ({10 * bien / total:.1f} sobre 10)".replace(".", ",", 1))
    ruta, _ = informe_simulacro(dia, ex, minutos, usados, resultados)
    print(f"Informe guardado en usuario/simulacros/{ruta.name}")
    if any(r["estado"] != "sin responder" for r in resultados):
        print(cerrar(date.today(), fichas, git=git))


def _de_nivel_hoy(dia):
    return [e for e in registro.leer() if registro.fecha(e) == dia and e.get("motivo") == "nivel"]


def cola_nivel_json(fichas, dia, n=NIVEL_N, forzar=False):
    """Modo revisor: el SIGUIENTE ejercicio de la prueba de nivel (es adaptativa, asi que
    va de uno en uno), fijado en .cache para que `registrar` le ponga el motivo «nivel».
    Lista vacia si la prueba no se ofrece o ya ha terminado. Sin pistas ni ejemplo."""
    ok, motivo = nivel_disponible(registro.leer())
    if not ok and not forzar:
        print(motivo + ". Usa --forzar para hacerla igualmente.", file=sys.stderr)
        return []
    x = siguiente_nivel(fichas, registro.leer(), dia, n)
    if x is None:
        return []
    ruta = _ruta_cache(f"nivel-{dia.isoformat()}.json")
    guardada = registro.leer_json(ruta, [])
    item = {"ficha": x.ficha.id, "semilla": x.semilla}
    if item not in guardada:
        guardada.append(item)
        registro.escribir_json(ruta, guardada)
    v = x.ficha.variante(x.semilla)
    return [{**item, "motivo": "nivel", "tecnica": x.ficha.tecnica, "grupo": x.ficha.grupo,
             "escalon": x.ficha.escalon, "numero": len(_de_nivel_hoy(dia)) + 1, "maximo": n,
             "enunciado": v.enunciado, "como_responder": _AYUDA_TIPO.get(x.ficha.tipo, "")}]


def sesion_nivel(fichas, dia, n=NIVEL_N, forzar=False, git=True):
    """Prueba de nivel: hasta `n` ejercicios adaptativos (escalon 1 de cada grupo; si se
    acierta sin pistas sube, al primer fallo el grupo se detiene). Sin pistas ni
    correccion durante la prueba; confianza como en `hoy`. Los intentos se registran
    con motivo «nivel» y no gastan el cupo. Se puede parar con q y seguir el mismo dia."""
    ok, motivo = nivel_disponible(registro.leer())
    if not ok and not forzar:
        print(f"{motivo}. Si quieres hacerla igualmente: programa\\practica.py nivel --forzar")
        return
    print(f"Prueba de nivel: hasta {n} ejercicios para colocar tu escalera. Sin pistas ni correccion hasta el final.")
    print("Escribe solo el resultado. Enter vacio = «no lo se» (cuenta como fallo y ese grupo para);  q = parar.\n")
    try:
        while True:
            x = siguiente_nivel(fichas, registro.leer(), dia, n)
            if x is None:
                break
            v = x.ficha.variante(x.semilla)
            print(f"[{len(_de_nivel_hoy(dia)) + 1}/hasta {n}] ({x.ficha.grupo}, escalon {x.ficha.escalon}, {x.ficha.tecnica})  {v.enunciado}")
            if x.ficha.tipo in _AYUDA_TIPO:
                print(f"  ({_AYUDA_TIPO[x.ficha.tipo]})")
            confianza = _pedir_confianza()
            inicio = time.monotonic()
            while True:
                t = input("  Resultado (Enter = no lo se): ").strip()
                if t == "q":
                    raise KeyboardInterrupt
                r = comprobar(v, t) if t else None
                if r is not None and r.error:  # no se corrige, pero un resultado ilegible se reescribe
                    print(f"  No lo leo: {r.error}.")
                    continue
                break
            try:
                registrar(v, t or None, confianza, 0, round(time.monotonic() - inicio), rendido=not t, motivo="nivel")
            except YaRegistrado:
                break
    except (KeyboardInterrupt, EOFError):
        print("\nPrueba parada. Lo hecho queda guardado; puedes seguirla hoy con el mismo comando.")
    hechos = _de_nivel_hoy(dia)
    if not hechos:
        print("Hoy no hay ejercicios de la prueba de nivel.")
        return
    print("\nCorreccion:")
    for i, e in enumerate(hechos, 1):
        v = fichas[e["ficha"]].variante(e["semilla"]) if e["ficha"] in fichas else None
        bien = e.get("correcto") and not e.get("pistas")
        print(f"{i}. {e['ficha']} ({e['tecnica']}): {'CORRECTO' if bien else 'FALLO'}")
        print(f"   {e['enunciado']}")
        if e.get("respuesta"):
            print(f"   Tu respuesta: {e['respuesta']}")
        if v is not None and not bien:
            print(f"   Solucion: {v.respuesta_modelo}")
            for d in diagnosticar(v, e["respuesta"]) if e.get("respuesta") else []:
                print(f"   El motor ve: {d}")
    nombres = {"algebra": "Algebra", "derivada": "Derivadas", "integral": "Integrales", "parcial": "Parciales y EDOs"}
    print("\nTu escalera:")
    for g, r in resumen_nivel(fichas, registro.leer(), dia)["grupos"].items():
        print(f"  - {nombres[g]}: {r['aciertos']}/{r['ejercicios']}, escalon abierto {r['escalon_antes']} -> {r['escalon_despues']}"
              + (" (aqui se detuvo)" if r["detenido"] else ""))
    print(cerrar(date.today(), fichas, git=git))


def _revision_si_toca(fichas, dia):
    """Una vez por semana, la revision se genera sola al empezar."""
    if tutela.toca_revision(dia, registro.leer()):
        texto = tutela.revision(dia, fichas)
        print(f"Revision de la semana guardada en usuario/revisiones/{dia.isoformat()}.md. Lo importante:")
        recomendaciones = texto.split("## 6. Recomendaciones (automaticas)")[1].split("##")[0]
        for linea in [x for x in recomendaciones.splitlines() if x.startswith("- ")][:3]:
            print("  " + linea)
        print()


def _sensacion_final(s):
    """Al terminar: como te has sentido y si hay alguna queja (todo opcional)."""
    try:
        t = input("¿Como te has sentido hoy? 1 fatal, 2 mal, 3 normal, 4 bien, 5 genial (Enter = saltar): ").strip()
        texto = input("¿Algun comentario o queja? (Enter = nada): ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    if t in {"1", "2", "3", "4", "5"}:
        s.sensacion(int(t), texto)
    elif texto:
        s.queja(texto)


def sesion_interactiva(fichas, dia, minimo, git=True):
    _revision_si_toca(fichas, dia)
    s = _servicio(fichas)
    pendientes = s.cola(minimo)["ejercicios"]
    if not pendientes:
        print("Hoy ya esta todo hecho (o no hay nada que tocar). Buen trabajo.")
        return
    total = len(pendientes)
    print(f"Hoy: {total} ejercicios. Resuelve en papel y escribe solo el resultado.")
    print("Escribe  p  pista,  s  ver la solucion,  v  ver la grafica,  r  «mi respuesta estaba bien» (reclamar),  q  parar.\n")
    hechos, vistas = 0, set()
    try:
        for i, item in enumerate(pendientes, 1):
            _un_ejercicio(fichas, item, i, total, vistas, s)
            hechos += 1
    except (KeyboardInterrupt, EOFError):
        print("\nSesion parada. Lo hecho queda guardado.")
    if hechos:
        _sensacion_final(s)
    # Si la sesion cruza la medianoche, se cierran los dos dias.
    for d in sorted({dia, date.today()}):
        print(cerrar(d, fichas, git=git))


def ejemplo_nuevo(fichas, ficha_id, entradas=None):
    """El ejemplo resuelto completo de la tecnica de esta ficha, solo si esa tecnica nunca
    se ha practicado; si no, None."""
    ej, huecos = ejemplo_con_huecos(fichas, ficha_id, entradas)
    return ej if huecos == 0 else None


def _pausa():
    try:
        if input("  (Enter para seguir con el ejercicio) ").strip() == "q":
            raise KeyboardInterrupt
    except EOFError:
        pass
    print()


def _ensenar_ejemplo(ej, nueva=True):
    if nueva:
        print(f"Tecnica nueva: {ej['tecnica']}. Antes, un ejemplo resuelto:")
    else:  # tras un fallo o una rendicion, el ejemplo completo otra vez
        print(f"Antes, el ejemplo resuelto de {ej['tecnica']} completo (la ultima vez costo):")
    if ej["idea"]:
        print(f"  Cuando se usa: {ej['idea']}")
    print(f"  {ej['enunciado']}")
    for n, paso in enumerate(ej["pasos"], 1):
        print(f"  {n}. {paso}")
    print(f"  Resultado: {ej['resultado']}")
    _pausa()


def _ensenar_huecos(ej, huecos, s):
    """Ejemplo con los ultimos pasos ocultos: se escribe el resultado, no se registra."""
    pasos, ocultos = recortar(ej["pasos"], huecos)
    print(f"Ejemplo con huecos ({ej['tecnica']}): completa el final, sin nota ni registro.")
    if ej["idea"]:
        print(f"  Cuando se usa: {ej['idea']}")
    print(f"  {ej['enunciado']}")
    for n, paso in enumerate(pasos, 1):
        print(f"  Paso {n}: {paso}")
    try:
        t = input("  Resultado del ejemplo (Enter para seguir si no lo sabes): ").strip()
    except EOFError:
        t = ""
    if t == "q":
        raise KeyboardInterrupt
    if t:
        r = s.comprobar_ejemplo(ej["tecnica"], t)
        print("  Bien." if r["correcto"] else "  No coincide; mira los pasos de abajo.")
    for n, paso in enumerate(ocultos, len(pasos) - len(ocultos) + 1):
        print(f"  Paso {n}: {paso}")
    print(f"  Resultado: {ej['resultado']}")
    _pausa()


def _con_ejemplo(fichas, items):
    """Para la salida JSON: el campo `ejemplo` solo en el primer ejercicio de cada
    tecnica que aun lo necesita (completo o con huecos)."""
    servicio.con_ejemplo(fichas, items, lambda *a, **k: ejemplo_con_huecos(*a, **k))


def _un_ejercicio(fichas, item, i, total, vistas=None, s=None):
    """Un ejercicio en la terminal: solo entrada y salida; la logica es de servicio.Sesion."""
    s = s or _servicio(fichas)
    v = _variante(fichas, item["ficha"], item["semilla"])
    ficha, semilla = v.ficha.id, v.semilla
    vistas = set() if vistas is None else vistas
    ej, huecos = s._ejemplo_de(ficha)
    if ej is not None and ej["tecnica"] not in vistas:
        vistas.add(ej["tecnica"])
        if huecos == 0:
            _ensenar_ejemplo(ej, nueva=not any(e.get("tecnica") == ej["tecnica"] for e in registro.leer()))
        else:
            _ensenar_huecos(ej, huecos, s)
    d = s.ejercicio(ficha, semilla)
    print(f"[{i}/{total}] ({_ETIQUETAS.get(item['motivo'], item['motivo'])}, {d['tecnica']})  {d['enunciado']}")
    if d["como_responder"]:
        print(f"  ({d['como_responder']})")
    confianza = _pedir_confianza()
    s.mostrar(ficha, semilla)   # el reloj empieza aqui, como antes
    pistas, respuesta, rendido, reclamo, fallos = 0, None, False, False, 0
    ultima, diagnosticos = None, []
    while True:
        t = input("  Resultado: ").strip()
        if t == "q":
            raise KeyboardInterrupt
        if t == "r":
            if ultima is None:
                print("  Primero escribe tu resultado; despues, si crees que estaba bien, pulsa r.")
                continue
            respuesta, reclamo = ultima, True
            print("  Anotado como reclamacion: queda pendiente de revisar. No cuenta como fallo.")
            break
        if t == "v":  # ver la grafica con math-plotter; no cuenta como pista
            print("  " + ver_ficha(v))
            continue
        if t == "p":
            pistas += 1
            print("  Pista:", s.pista(ficha, semilla, min(pistas, 4))["texto"])
            if pistas >= 4:
                rendido = True
                break
            continue
        if t == "s":
            pistas, rendido = 4, True
            print("  ", s.solucion(ficha, semilla)["texto"])
            break
        if not t:
            continue
        r = s.comprobar(ficha, semilla, t)
        if r["error"]:
            print(f"  No lo leo: {r['error']}.")
            continue
        if r["leido"]:
            print(f"  He leido: {r['leido']}")
        if r["correcto"]:
            respuesta = t
            for aviso in r["avisos"]:
                print("  Ojo:", aviso)
            print("  Correcto.")
            break
        for aviso in r["avisos"]:
            print("  Ojo:", aviso)
        ultima, fallos = t, fallos + 1
        nuevos = r["diagnostico"]
        for d_ in nuevos:
            print("  El motor ve:", d_)
        diagnosticos += [d_ for d_ in nuevos if d_ not in diagnosticos]
        if fallos == 1:
            print("  No cuadra. Corrige y vuelve a escribir, pide pista (p), o r si crees que estaba bien.")
            print("  (Si aciertas ahora, cuenta como «costo»: lo veras antes en el repaso.)")
        else:
            print("  No cuadra. Mejor pide una pista (p) antes de seguir probando, o r si crees que estaba bien.")
    causa = None
    if s.causa_necesaria(ficha, semilla, rendido=rendido, pistas=pistas, reclamo=reclamo)["necesaria"]:
        causa = _pedir_causa()
    for intento in range(3):   # si el disco falla, se dice claro y se reintenta
        try:
            r = s.registrar(ficha, semilla, confianza, respuesta, rendido, causa, reclamo, pistas=pistas,
                            fallos=fallos, motivo=item["motivo"], diagnostico=diagnosticos)
            break
        except registro.ErrorRegistro as exc:
            print(f"  NO se ha guardado este ejercicio: {exc}.")
            if intento == 2:
                print("  Sigo con el siguiente; revisa programa\\practica.py doctor.\n")
                return
            try:
                input("  Pulsa Enter para reintentar... ")
            except (EOFError, KeyboardInterrupt):
                return
    if r["ya_registrado"]:
        print("  Este ejercicio ya estaba registrado hoy: no se cuenta otra vez.\n")
        return
    print(f"  Proximo repaso: {date.fromisoformat(r['proximo']).strftime('%d/%m')}\n")


def _pedir_causa():
    """Una tecla para saber que ha pasado: alimenta la revision semanal."""
    opciones = "  ".join(f"{k} {v}" for k, v in tutela.CAUSAS.items() if k != "5")
    try:
        t = input(f"  ¿Que ha pasado? {opciones}  (Enter = saltar): ").strip()
    except (KeyboardInterrupt, EOFError):
        return None
    return tutela.CAUSAS.get(t) if t != "5" else None


def _ventana(a):
    """Codigo de salida de la ventana: SIN_VENTANA (3) si no se puede abrir.
    Con --respaldo-terminal (Practicar.bat la lanza con pythonw, sin consola),
    si no abre o se cae se abre la sesion en la terminal, en una consola nueva."""
    codigo = 3
    if _FALTA is not None:
        print(f"Falta algo por instalar ({_FALTA}). Sigo en la terminal.")
    else:
        try:
            from calculo import ventana
        except Exception as exc:
            print(f"No se puede abrir la ventana ({exc}). Sigo en la terminal.")
        else:
            codigo = ventana.abrir(minimo=a.minimo, prueba=a.prueba, captura=a.captura)
    if codigo == 3 and a.respaldo_terminal and not a.prueba:
        _abrir_terminal(a.minimo)
    return codigo


def _abrir_terminal(minimo=False):
    """Respaldo de la ventana: Terminal.bat en una consola nueva. Este
    proceso (pythonw) termina despues, asi que nunca hay dos sesiones a la vez."""
    bat = rutas.RAIZ / "otras-opciones" / "Terminal.bat"
    try:
        subprocess.Popen(["cmd.exe", "/c", str(bat)] + (["--minimo"] if minimo else []), cwd=str(bat.parent),
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), close_fds=True)
        print("Respaldo: sesion abierta en la terminal (otras-opciones\\Terminal.bat).")
    except OSError as exc:
        print(f"Respaldo: no se pudo abrir Terminal.bat ({exc}).")


class _AlLog:
    """stdout/stderr con pythonw: no hay consola (sys.stdout es None); lo
    que se imprimiria va a .cache/servicio.log, abriendo y cerrando en cada
    escritura para no bloquear la rotacion del log."""
    encoding = "utf-8"

    def __init__(self, ruta):
        self.ruta = Path(ruta)

    def write(self, texto):
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ruta, "a", encoding="utf-8") as f:
                f.write(texto)
        except OSError:
            pass
        return len(texto)

    def flush(self):
        pass

    def isatty(self):
        return False


def _sin_consola():
    if sys.stdout is None or sys.stderr is None:
        log = _AlLog(CACHE / "servicio.log")
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log


def _datos_al_empezar(interactivo=True):
    """Revision y copia de usuario/datos al empezar (calculo/datos.py). En la
    terminal se pregunta antes de recuperar; en modo revisor (`cola`), a stderr."""
    from calculo import datos

    def preguntar(texto):
        print(texto)
        try:
            return input("  (s/n): ").strip().lower().startswith("s")
        except (EOFError, KeyboardInterrupt):
            return False
    avisos = datos.al_arrancar(preguntar=preguntar if interactivo else None, cache=CACHE)
    for aviso in avisos:
        print("Datos:", aviso, file=sys.stdout if interactivo else sys.stderr)
    if avisos and interactivo:
        print()


def _orden_datos(a):
    from calculo import datos
    if a.recuperar:
        hecho = datos.recuperar()
        print("Recuperadas: " + ", ".join(f"{k} lineas en {n}" for n, k in hecho.items()) if hecho
              else "No falta nada respecto a la ultima copia: no hay nada que recuperar.")
    if a.copiar:
        r = datos.copiar("a mano", forzar=True)
        print(f"Copia hecha en {r['carpeta']}." if r["hecha"] else f"No se hizo la copia: {r['motivo']}.")
    lineas, bien = [], True
    for ok, texto in datos.resumen():
        bien &= ok is not False
        lineas.append(("[OK ] " if ok else "[MAL] " if ok is False else "[OJO] ") + texto.removeprefix("datos: "))
    print("Tus datos:\n" + "\n".join(lineas))
    print("Tus datos estan bien." if bien else "Hay algo marcado MAL: mira la linea.")
    return 0 if bien else 1


def main(argv=None):
    _sin_consola()
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Practica diaria de derivadas, integrales y EDOs")
    sub = p.add_subparsers(dest="orden", required=True)
    for nombre in ("hoy", "cola"):
        s = sub.add_parser(nombre)
        s.add_argument("--minimo", action="store_true", help="dia minimo: 2 ejercicios")
        s.add_argument("--sin-git", action="store_true", help="no hacer commit al cerrar")
    s = sub.add_parser("comprobar")
    s.add_argument("ficha"); s.add_argument("semilla"); s.add_argument("respuesta")
    s = sub.add_parser("pista")
    s.add_argument("ficha"); s.add_argument("semilla"); s.add_argument("nivel", type=int, choices=range(1, 5))
    s = sub.add_parser("registrar")
    s.add_argument("ficha"); s.add_argument("semilla")
    s.add_argument("--confianza", type=int, required=True, choices=range(1, 6))
    s.add_argument("--pistas", type=int, default=0, choices=range(0, 5),
                   help="pistas dadas fuera del motor; se suma la mas alta anotada por `pista`")
    s.add_argument("--fallos", type=int, default=0,
                   help="intentos fallidos fuera del motor; se suma lo anotado por `comprobar`")
    s.add_argument("--respuesta")
    s.add_argument("--rendido", action="store_true")
    s.add_argument("--segundos", type=int)
    s.add_argument("--forzar", action="store_true", help="registrar aunque ya este registrado hoy")
    s.add_argument("--causa", choices=["1", "2", "3", "4"], help="que ha pasado (ver tutela.CAUSAS)")
    s.add_argument("--reclamo", action="store_true", help="el alumno cree que su respuesta es correcta")
    s = sub.add_parser("cerrar")
    s.add_argument("--sin-git", action="store_true")
    sub.add_parser("informe")
    s = sub.add_parser("doctor")
    s.add_argument("--rapido", action="store_true", help="sin red ni git (lo usa Practicar.bat)")
    s = sub.add_parser("datos", help="tus datos: intentos, copias y si falta algo (lenguaje llano)")
    s.add_argument("--recuperar", action="store_true", help="juntar las lineas que faltan de la ultima copia")
    s.add_argument("--copiar", action="store_true", help="hacer ya una copia (acepta lo actual como bueno)")
    s = sub.add_parser("ventana", help="la sesion de hoy en una ventana (codigo 3 si no se puede abrir)")
    s.add_argument("--minimo", action="store_true", help="dia minimo: 2 ejercicios")
    s.add_argument("--prueba", action="store_true", help="humo: recorrido automatico con datos temporales")
    s.add_argument("--captura", help="con --prueba: guardar una captura PNG de la ventana")
    s.add_argument("--respaldo-terminal", action="store_true",
                   help="si la ventana no abre o se cae, abrir Terminal.bat en una consola nueva")
    s = sub.add_parser("examen", help="modo examen: sesion extra del proximo examen")
    s.add_argument("--nombre", help="trozo del nombre del examen (p. ej. «Parcial 1»); por defecto, el proximo")
    s.add_argument("--n", type=int, default=5, help="numero de ejercicios (5 por defecto)")
    s.add_argument("--cola", action="store_true", help="solo listar (JSON, modo revisor)")
    s.add_argument("--sin-git", action="store_true")
    s = sub.add_parser("simulacro", help="simulacro cronometrado del proximo examen (sin pistas)")
    s.add_argument("--nombre", help="trozo del nombre del examen (p. ej. «Parcial 1»); por defecto, el proximo")
    s.add_argument("--n", type=int, default=4, help="numero de ejercicios (4 por defecto)")
    s.add_argument("--minutos", type=int, default=40, help="duracion (40 por defecto)")
    s.add_argument("--cola", action="store_true", help="solo listar (JSON, modo revisor)")
    s.add_argument("--sin-git", action="store_true")
    s = sub.add_parser("nivel", help="prueba de nivel adaptativa (hasta 10 ejercicios, sin pistas)")
    s.add_argument("--n", type=int, default=NIVEL_N, help="ejercicios como maximo (10 por defecto)")
    s.add_argument("--forzar", action="store_true", help="ofrecerla aunque ya haya 20 intentos o mas")
    s.add_argument("--cola", action="store_true", help="solo el siguiente ejercicio (JSON, modo revisor)")
    s.add_argument("--sin-git", action="store_true")
    s = sub.add_parser("queja", help="anotar una queja o comentario")
    s.add_argument("texto")
    s = sub.add_parser("sensacion", help="como te has sentido hoy (1-5)")
    s.add_argument("valor", type=int, choices=range(1, 6)); s.add_argument("texto", nargs="?", default="")
    sub.add_parser("pendientes", help="quejas y reclamaciones sin resolver")
    s = sub.add_parser("resolver", help="cerrar una queja o reclamacion")
    s.add_argument("id"); s.add_argument("texto")
    decision = s.add_mutually_exclusive_group()
    decision.add_argument("--rechazar", action="store_true",
                          help="reclamacion: la respuesta estaba mal (el intento pasa a nota 1)")
    decision.add_argument("--aceptar", action="store_true",
                          help="reclamacion: la respuesta estaba bien (el intento pasa a nota 3)")
    sub.add_parser("racha", help="JSON: si hoy ya esta hecho y dias seguidos (para el recordatorio)")
    s = sub.add_parser("revision", help="revision de la semana")
    s.add_argument("--sin-guardar", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["comprobar"] and len(argv) >= 4 and "--" not in argv:
        argv.insert(3, "--")  # una respuesta como «-x e^x» no es una opcion
    for i, t in enumerate(argv[:-1]):
        if t == "--respuesta" and argv[i + 1].startswith("-"):
            argv[i:i + 2] = [f"--respuesta={argv[i + 1]}"]  # idem en registrar
            break
    a = p.parse_args(argv)

    if a.orden == "doctor":
        from calculo.doctor import informe_doctor
        ok, texto = informe_doctor(rapido=a.rapido)
        print(texto)
        sys.exit(0 if ok else 1)

    if a.orden == "racha":  # lo usa el recordatorio (herramientas/recordatorio.ps1)
        from calculo.registro import leer, racha
        hecho, dias = racha(leer(), date.today())
        print(json.dumps({"hecho_hoy": hecho, "racha": dias}))
        return

    if a.orden == "ventana":
        sys.exit(_ventana(a))

    if a.orden == "datos":
        sys.exit(_orden_datos(a))

    if _FALTA is not None:
        sys.exit(f"Falta algo por instalar ({_FALTA}). Ejecuta: python programa\\practica.py doctor")
    fichas = cargar()
    dia = date.today()
    if a.orden in ("hoy", "examen", "simulacro", "nivel", "cola"):
        _datos_al_empezar(interactivo=a.orden != "cola" and not getattr(a, "cola", False))
    if a.orden == "hoy":
        sesion_interactiva(fichas, dia, a.minimo, git=not a.sin_git)
    elif a.orden == "cola":
        salida = []
        for e in _servicio(fichas).cola(a.minimo)["ejercicios"]:
            salida.append({k: e[k] for k in _CAMPOS_COLA if k in e})
        print(json.dumps(salida, ensure_ascii=False, indent=1))
    elif a.orden == "comprobar":
        v = _variante(fichas, a.ficha, a.semilla)
        r = _servicio(fichas).comprobar(v.ficha.id, v.semilla, a.respuesta)
        print(json.dumps({k: r[k] for k in ("correcto", "leido", "avisos", "error", "diagnostico")},
                         ensure_ascii=False))
    elif a.orden == "pista":
        v = _variante(fichas, a.ficha, a.semilla)
        print(_servicio(fichas).pista(v.ficha.id, v.semilla, a.nivel)["texto"])
    elif a.orden == "registrar":
        v = _variante(fichas, a.ficha, a.semilla)
        if not a.respuesta and not a.rendido:
            sys.exit("Falta --respuesta (o --rendido si se vio la solucion)")
        try:
            r = _servicio(fichas).registrar(v.ficha.id, v.semilla, a.confianza, a.respuesta, a.rendido, a.causa,
                                            a.reclamo, pistas=a.pistas, fallos=a.fallos, segundos=a.segundos,
                                            forzar=a.forzar)
        except ValueError as exc:   # respuesta ilegible, reclamo con rendido...: no se registra nada
            sys.exit(f"No se registra: {exc}")
        if r["ya_registrado"]:
            sys.exit(f"{v.ficha.id} ya esta registrado hoy. No se registra otra vez "
                     "(usa --forzar si de verdad es un segundo intento).")
        print(json.dumps({k: r[k] for k in ("nota", "correcto", "pistas", "fallos", "avisos", "proximo")},
                         ensure_ascii=False))
    elif a.orden == "cerrar":
        print(cerrar(dia, fichas, git=not a.sin_git))
    elif a.orden == "informe":
        print(informe(dia, fichas))
    elif a.orden == "examen":
        if a.cola:
            ex = elegir_examen(dia, a.nombre)
            lista = cola_examen(fichas, registro.leer(), dia, ex, a.n) if ex else []
            salida = [{"ficha": x.ficha.id, "semilla": x.semilla, "motivo": "examen",
                       "tecnica": x.ficha.tecnica, "enunciado": x.ficha.variante(x.semilla).enunciado,
                       "como_responder": _AYUDA_TIPO.get(x.ficha.tipo, "")} for x in lista]
            _con_ejemplo(fichas, [({"ficha": x.ficha.id}, o) for x, o in zip(lista, salida)])
            print(json.dumps(salida, ensure_ascii=False, indent=1))
        else:
            sesion_examen(fichas, dia, a.nombre, a.n, git=not a.sin_git)
    elif a.orden == "simulacro":
        if a.cola:
            print(json.dumps(cola_simulacro_json(fichas, dia, a.nombre, a.n, a.minutos), ensure_ascii=False, indent=1))
        else:
            sesion_simulacro(fichas, dia, a.nombre, a.n, a.minutos, git=not a.sin_git)
    elif a.orden == "nivel":
        if a.cola:
            print(json.dumps(cola_nivel_json(fichas, dia, a.n, a.forzar), ensure_ascii=False, indent=1))
        else:
            sesion_nivel(fichas, dia, a.n, a.forzar, git=not a.sin_git)
    elif a.orden == "queja":
        print("Anotado:", tutela.anotar("queja", texto=a.texto)["id"])
    elif a.orden == "sensacion":
        print("Anotado:", tutela.anotar("sensacion", valor=a.valor, texto=a.texto)["id"])
    elif a.orden == "pendientes":
        print(json.dumps(tutela.pendientes(), ensure_ascii=False, indent=1))
    elif a.orden == "resolver":
        try:
            r = tutela.resolver(a.id, a.texto, rechazar=a.rechazar, aceptar=a.aceptar)
        except (KeyError, ValueError) as exc:
            sys.exit(str(exc).strip("'\""))
        print("Resuelto:", r["resuelve"] + (f" (reclamacion {r['decision']})" if r.get("decision") else ""))
    elif a.orden == "revision":
        print(tutela.revision(dia, fichas, escribir=not a.sin_guardar))


if __name__ == "__main__":
    main()
