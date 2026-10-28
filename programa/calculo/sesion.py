"""Registrar intentos, cerrar la sesion (diario + git) e informe semanal."""
import re
import subprocess
import time
import tomllib
from datetime import date, timedelta
from pathlib import Path

from . import registro
from .rutas import RAIZ, USUARIO
from .expresiones import X, Y
from .planificador import (
    CALENDARIO, FOCO, GRUPOS_NIVEL, MIN_CALIBRACION, abiertas_por_examen, calibracion, carga_prevista, dominio,
    estados, fecha_proxima, foco_activo, leer_hitos, nivel, progreso, progreso_al_dia, repasos_ahorrados,
    resumen_nivel, ruta_hitos, subidas_de_nivel,
)
from .fichas import ESCALONES
from .verificar import (
    comprobar_derivada, comprobar_edo, comprobar_expresion, comprobar_integral, comprobar_par,
    comprobar_parcial, comprobar_potencial, comprobar_raices, comprobar_valor, comprobar_valores,
    leer_edo, leer_expresion, leer_numero, leer_par, leer_potencial, leer_primitiva, leer_raices, leer_una,
    leer_valores,
)

DIARIO = USUARIO / "diario.md"
SIMULACROS = USUARIO / "simulacros"

# Confianza 1-5 -> probabilidad que el alumno se da a si mismo (para calibracion).
CONFIANZA_P = {1: 0.1, 2: 0.3, 3: 0.5, 4: 0.7, 5: 0.9}
MIN_DATOS = 5


class YaRegistrado(ValueError):
    """Ese ejercicio (ficha y semilla) ya se registro hoy."""


class RespuestaIlegible(ValueError):
    """La respuesta no se puede leer: no es un fallo, hay que escribirla de otra forma."""


def comprobar(variante, respuesta):
    tipo = variante.ficha.tipo
    if tipo == "definida":
        return comprobar_valor(respuesta, variante.solucion)
    if tipo == "algebra":
        return comprobar_valores(respuesta, variante.solucion)
    if tipo == "parcial":
        var = Y if variante.ficha.respecto == "y" else X
        return comprobar_parcial(respuesta, variante.funcion, var, variante.semilla)
    if tipo == "exacta":
        return comprobar_par(respuesta, list(variante.solucion), variante.semilla)
    if tipo == "potencial":
        return comprobar_potencial(respuesta, *variante.funcion, variante.semilla)
    if tipo == "raices":
        return comprobar_raices(respuesta, variante.solucion)
    if tipo == "edo_solucion":
        f = variante.ficha
        return comprobar_edo(respuesta, f.operador(variante.params), variante.funcion,
                             f.constantes, variante.semilla)
    if tipo == "calculo":
        return comprobar_expresion(respuesta, variante.solucion, variante.semilla)
    f = comprobar_integral if tipo == "integral" else comprobar_derivada
    return f(respuesta, variante.funcion, variante.semilla)


def lectura(variante, respuesta):
    """Solo leer (sin corregir), con la misma funcion leer_* que usa `comprobar`
    para ese tipo. Devuelve una verificar.Lectura o lanza ErrorLectura."""
    tipo = variante.ficha.tipo
    if tipo == "definida":
        return leer_numero(respuesta)
    if tipo == "algebra":
        return leer_valores(respuesta, variante.solucion)
    if tipo == "parcial":
        return leer_una(respuesta, variables="xy")
    if tipo == "exacta":
        return leer_par(respuesta)
    if tipo == "potencial":
        return leer_potencial(respuesta)
    if tipo == "raices":
        return leer_raices(respuesta)
    if tipo == "edo_solucion":
        return leer_edo(respuesta)
    if tipo == "calculo":
        return leer_expresion(respuesta)
    return leer_primitiva(respuesta) if tipo == "integral" else leer_una(respuesta)


def registrar(variante, respuesta, confianza, pistas, segundos=None, rendido=False,
              ruta=None, motivo="", forzar=False, causa=None, reclamo=False, diagnostico=None,
              fallos=0):
    """Comprueba de nuevo la respuesta (la nota sale de hechos), anade el intento
    y devuelve (entrada, proxima_fecha). Rechaza registrar dos veces el mismo
    ejercicio el mismo dia (salvo forzar=True), tambien si llegan dos a la vez.
    `fallos`: intentos que no cuadraron antes de este (acertar tras fallar vale 2)."""
    entradas = registro.leer(ruta)
    hoy = registro.ahora().date()

    def repetida(todas):
        return not forzar and any(e["ficha"] == variante.ficha.id and e.get("semilla") == variante.semilla
                                  and registro.fecha(e) == hoy for e in todas)

    pistas = max(0, min(4, pistas))
    if reclamo and (rendido or pistas >= 4):
        raise ValueError("no se puede reclamar un ejercicio en el que se vio la solucion (rendido o pista 4)")
    if repetida(entradas):
        raise YaRegistrado(f"{variante.ficha.id} ya esta registrado hoy")
    resultado = comprobar(variante, respuesta) if respuesta and not rendido else None
    if resultado is not None and resultado.error:
        raise RespuestaIlegible(f"no se lee la respuesta ({resultado.error}); escribela de otra forma "
                                "o registra con --rendido")
    correcto = bool(resultado and resultado.correcto)
    fallos = max(0, fallos)
    mediana = registro.mediana_segundos(entradas, variante.ficha.tecnica)
    entrada = {
        "ts": registro.ahora().isoformat(),
        "ficha": variante.ficha.id,
        "tipo": variante.ficha.tipo,
        "grupo": variante.ficha.grupo,
        "tecnica": variante.ficha.tecnica,
        "semilla": variante.semilla,
        "enunciado": variante.enunciado,
        "motivo": motivo,
        "nueva": all(e.get("enunciado") != variante.enunciado for e in entradas),
        "confianza": confianza,
        "respuesta": respuesta,
        "correcto": correcto,
        "avisos": resultado.avisos if resultado else [],
        "pistas": pistas,
        "segundos": segundos,
        "nota": registro.nota(correcto, pistas, confianza, segundos, mediana, fallos),
    }
    if fallos:
        entrada["fallos"] = fallos
    if forzar and any(e["ficha"] == variante.ficha.id and e.get("semilla") == variante.semilla
                      and registro.fecha(e) == hoy for e in entradas):
        entrada["forzado"] = True   # repetido a proposito: la revision de datos no lo da por duplicado
    if causa:
        entrada["causa"] = causa
    if diagnostico:
        entrada["diagnostico"] = diagnostico
    if reclamo and not correcto:
        # El alumno cree que su respuesta es correcta: no se castiga como fallo
        # (nota 2 provisional) y queda pendiente de revisar (`pendientes`).
        entrada["reclamo"] = True
        entrada["nota"] = max(entrada["nota"], 2)
    try:
        registro.anadir(entrada, ruta, repetida=repetida)
    except registro.YaExiste as exc:
        raise YaRegistrado(f"{variante.ficha.id} ya esta registrado hoy") from exc
    if entrada.get("reclamo"):
        from .tutela import anotar
        anotar("reclamo", ficha=variante.ficha.id, semilla=variante.semilla,
               enunciado=variante.enunciado, respuesta=respuesta)
    tarjeta = estados(entradas + [entrada])[variante.ficha.id]
    return entrada, fecha_proxima(tarjeta)


_RESULTADO = {1: "fallo o solucion vista", 2: "acierto con ayuda", 3: "acierto", 4: "acierto facil"}


def _bloque_diario(dia, hoy, tarjetas):
    lineas = [f"<!-- motor {dia.isoformat()} -->", f"## {dia.isoformat()} - Practica (motor)", ""]
    for e in hoy:
        proxima = fecha_proxima(tarjetas[e["ficha"]]).isoformat() if e["ficha"] in tarjetas else "-"
        avisos = f" | avisos: {', '.join(e['avisos'])}" if e.get("avisos") else ""
        lineas.append(
            f"- {e['ficha']} | {e['enunciado']} | confianza {e.get('confianza') or '-'} | "
            f"respuesta: {e.get('respuesta') or '-'} | pistas {e['pistas']} | "
            f"{_RESULTADO[e['nota']]} (nota {e['nota']}){avisos} | proximo {proxima}"
        )
    autonomos = sum(1 for e in hoy if e["nota"] >= 3)
    lineas += ["", f"Resumen: {_ejercicios(len(hoy))}, {autonomos} sin ayuda.",
               f"<!-- fin motor {dia.isoformat()} -->"]
    return "\n".join(lineas)


SIN_INTENTOS = "Hoy no hay intentos registrados: no se escribe nada."


def cerrar(dia, fichas, git=True, ruta=None, diario=None):
    """Escribe el resumen del dia en usuario/diario.md y hace commit y push.
    Se puede llamar varias veces: el bloque del dia se reescribe, no se duplica."""
    mensaje, n = cerrar_local(dia, fichas, ruta, diario)
    if git and n:
        mensaje += "\n" + _git(dia, n)
    from . import datos   # copia verificada al cerrar (solo si algo cambio)
    datos.al_cerrar(datos.carpeta_datos(ruta))
    return mensaje


def cerrar_local(dia, fichas, ruta=None, diario=None):
    """La parte de `cerrar` sin git: (mensaje, ejercicios del dia)."""
    entradas = registro.leer(ruta)
    hoy = [e for e in entradas if registro.fecha(e) == dia]
    if not hoy:
        return SIN_INTENTOS, 0
    bloque = _bloque_diario(dia, hoy, estados(entradas))
    progreso_al_dia(fichas, entradas, ruta_hitos(ruta))   # el escalon alcanzado queda guardado
    ruta_diario = Path(diario or DIARIO)
    ruta_diario.parent.mkdir(parents=True, exist_ok=True)
    texto = ruta_diario.read_text(encoding="utf-8") if ruta_diario.exists() else ""
    marca = re.compile(rf"<!-- motor {dia.isoformat()} -->.*?<!-- fin motor {dia.isoformat()} -->", re.S)
    if marca.search(texto):
        texto = marca.sub(lambda _: bloque, texto)
    else:
        texto = texto.rstrip("\n") + "\n\n" + bloque + "\n"
    ruta_diario.write_text(texto, encoding="utf-8")
    mensaje = resumen_dia(hoy, subidas_de_nivel(entradas, dia, fichas))
    if any(e.get("motivo") == "nivel" for e in hoy):
        ruta_nivel, _ = informe_nivel(dia, fichas, entradas)
        mensaje += f"\nPrueba de nivel: resumen en usuario/revisiones/{ruta_nivel.name}"
    return mensaje, len(hoy)


def _minutos(segundos):
    return f"{int(segundos) // 60}:{int(segundos) % 60:02d}"


def informe_simulacro(dia, examen, minutos, usados, resultados, carpeta=None):
    """Escribe usuario/simulacros/AAAA-MM-DD_<examen>.md y devuelve (ruta, texto).
    `resultados`: lista de dicts con ficha, tecnica, enunciado, respuesta (o None),
    estado («correcto», «incorrecto» o «sin responder»), solucion y diagnostico."""
    n = len(resultados)
    bien = sum(1 for r in resultados if r["estado"] == "correcto")
    nota10 = round(10 * bien / n, 1) if n else 0.0
    lineas = [f"# Simulacro {examen['nombre']} - {dia.isoformat()}", "",
              f"- **Nota:** {bien}/{n} ({str(nota10).replace('.', ',')} sobre 10)",
              f"- **Tiempo:** {_minutos(usados)} de {minutos}:00",
              "- Condiciones de examen: sin pistas ni correccion durante el simulacro.", ""]
    for i, r in enumerate(resultados, 1):
        lineas += [f"## {i}. {r['ficha']} ({r['tecnica']}): {r['estado']}", "",
                   f"- Enunciado: {r['enunciado']}",
                   f"- Tu respuesta: {r['respuesta'] or '-'}",
                   f"- Solucion: {r['solucion']}"]
        for d in r.get("diagnostico") or []:
            lineas.append(f"- El motor ve: {d}")
        lineas.append("")
    texto = "\n".join(lineas)
    carpeta = Path(carpeta or SIMULACROS)
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = re.sub(r"[^A-Za-z0-9]+", "-", examen["nombre"]).strip("-")
    ruta, k = carpeta / f"{dia.isoformat()}_{nombre}.md", 2
    while ruta.exists():  # otro simulacro el mismo dia: no se sobrescribe
        ruta, k = carpeta / f"{dia.isoformat()}_{nombre}_{k}.md", k + 1
    ruta.write_text(texto, encoding="utf-8")
    return ruta, texto


_NOMBRE_GRUPO = {"algebra": "Algebra", "derivada": "Derivadas", "integral": "Integrales", "parcial": "Parciales y EDOs"}


def informe_nivel(dia, fichas, entradas, carpeta=None):
    """Escribe usuario/revisiones/AAAA-MM-DD_nivel.md (se reescribe: sale del registro de
    ese dia) y devuelve (ruta, texto)."""
    from . import tutela
    res = resumen_nivel(fichas, entradas, dia)
    prueba = sorted((e for e in entradas if registro.fecha(e) == dia and e.get("motivo") == "nivel"),
                    key=lambda e: e["ts"])
    bien = sum(1 for e in prueba if e.get("correcto") and not e.get("pistas"))
    lineas = [f"# Prueba de nivel {dia.isoformat()}", "",
              f"- **Aciertos:** {bien}/{len(prueba)} (sin pistas; un acierto abre escalones, un fallo no baja nada)",
              "- Un acierto en la prueba cuenta como «competente» para abrir el siguiente escalon; "
              "«dominada» sigue pidiendo la regla de siempre.", "", "## Por grupo", "",
              "| Grupo | Ejercicios | Aciertos | Tecnicas superadas | Escalon abierto |", "|---|---|---|---|---|"]
    for g in GRUPOS_NIVEL:
        r = res["grupos"].get(g)
        if r:
            lineas.append(f"| {_NOMBRE_GRUPO[g]} | {r['ejercicios']} | {r['aciertos']} | "
                          f"{', '.join(r['superadas']) or '-'}{' (se detuvo)' if r['detenido'] else ''} | "
                          f"{r['escalon_antes']} → {r['escalon_despues']} |")
    lineas += ["", "## Ejercicios", ""]
    for i, e in enumerate(prueba, 1):
        ok = e.get("correcto") and not e.get("pistas")
        lineas += [f"{i}. {e['ficha']} ({e['tecnica']}): {'correcto' if ok else 'fallo'}",
                   f"   - Enunciado: {e['enunciado']}",
                   f"   - Tu respuesta: {e.get('respuesta') or '-'} (confianza {e.get('confianza') or '-'})"]
        ficha = fichas.get(e["ficha"])
        if ficha is not None and not ok:
            lineas.append(f"   - Solucion: {ficha.variante(e['semilla']).respuesta_modelo}")
    texto = "\n".join(lineas) + "\n"
    carpeta = Path(carpeta or tutela.REVISIONES)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{dia.isoformat()}_nivel.md"
    ruta.write_text(texto, encoding="utf-8")
    return ruta, texto


def resumen_dia(hoy, subidas=()):
    autonomos = sum(1 for e in hoy if e["nota"] >= 3)
    texto = f"Hoy: {_ejercicios(len(hoy))}, {autonomos} sin ayuda."
    con = [e for e in hoy if e.get("confianza")]
    if con:
        media = sum(e["confianza"] for e in con) / len(con)
        acierto = sum(1 for e in con if e["nota"] >= 3) / len(con)
        dicho = sum(CONFIANZA_P[e["confianza"]] for e in con) / len(con)
        texto += f" Confianza media {media:.1f}/5; acertaste el {acierto:.0%} sin ayuda"
        if acierto - dicho >= 0.2:
            texto += ": te infravaloras."
        elif dicho - acierto >= 0.2:
            texto += ": hoy esperabas mas; no pasa nada, eso es lo que se repasa."
        else:
            texto += "."
    for tecnica, antes, despues in subidas:
        texto += f"\nNivel: {tecnica}: {antes} → {despues}"
    return texto


_DATOS = ["usuario/datos/registro.jsonl", "usuario/diario.md", "usuario/datos/notas.jsonl",
          "usuario/datos/progreso.jsonl", "usuario/revisiones", "usuario/simulacros"]
_MARCAS_CONFLICTO = re.compile(r"^(<{7}|>{7}|={7})( |$)", re.M)
INDEX_LOCK_VIEJO = 10 * 60   # segundos: un .git/index.lock mas viejo es de un git que murio


def _ficheros_de_datos(raiz):
    """(nombre relativo, ruta) de cada fichero de _DATOS; las carpetas se recorren."""
    for nombre in _DATOS:
        ruta = raiz / nombre
        if ruta.is_dir():
            for f in sorted(ruta.rglob("*")):
                if f.is_file():
                    yield f.relative_to(raiz).as_posix(), f
        elif ruta.is_file():
            yield nombre, ruta


def _ejercicios(n):
    return f"{n} ejercicio" if n == 1 else f"{n} ejercicios"


# La ventana corre con pythonw (sin consola); sin esto cada git abriria una consola un instante.
_SIN_CONSOLA = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}


def _git(dia, n, timeout=None, entorno=None):
    """Commit solo de registro y diario; antes, comprobar que no hay un conflicto
    a medias; despues, traer lo de otros equipos (rebase) y subir.
    `timeout` (segundos por orden) y `entorno` los usa la ventana (servicio.sincronizar)."""
    def correr(*args):
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, env=entorno,
                              **_SIN_CONSOLA)
    try:
        return _git_pasos(dia, n, correr)
    except subprocess.TimeoutExpired:
        if (RAIZ / ".git" / "rebase-merge").exists() or (RAIZ / ".git" / "rebase-apply").exists():
            try:
                correr("rebase", "--abort")
            except (subprocess.TimeoutExpired, OSError):
                pass
        return (f"git: se agoto el tiempo ({timeout} s); los datos estan guardados en disco "
                "y se subiran en el proximo cierre.")


def _quitar_index_lock_viejo():
    """Un git que se colgo o se mato deja .git/index.lock y ningun otro git puede
    operar. Si tiene mas de INDEX_LOCK_VIEJO segundos, se borra."""
    marca = RAIZ / ".git" / "index.lock"
    try:
        if marca.is_file() and time.time() - marca.stat().st_mtime > INDEX_LOCK_VIEJO:
            marca.unlink()
    except OSError:
        pass


def _git_pasos(dia, n, correr):
    try:
        _quitar_index_lock_viejo()
        if (RAIZ / ".git" / "MERGE_HEAD").exists() or (RAIZ / ".git" / "rebase-merge").exists() \
                or (RAIZ / ".git" / "rebase-apply").exists() or correr("ls-files", "-u").stdout.strip():
            return "git: hay una fusion a medias; no se guarda nada en git. Hay que resolverla a mano (los datos estan en disco)."
        for nombre, ruta in _ficheros_de_datos(RAIZ):
            try:
                texto = ruta.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _MARCAS_CONFLICTO.search(texto):
                return f"git: {nombre} tiene marcas de conflicto; no se sube. Hay que resolverlo a mano."
        datos = [n for n in _DATOS if (RAIZ / n).exists()]
        if not datos:
            return "git: no hay datos que guardar."
        r = correr("add", "--", *datos)
        if r.returncode:
            return f"git: no se pudo hacer commit ({r.stderr.strip()[:200]}); los datos estan en disco."
        if not correr("diff", "--cached", "--quiet", "--", *datos).returncode:
            commit = "sin cambios nuevos"
        else:
            r = correr("commit", "-q", "-m", f"content: sesion {dia.isoformat()} ({_ejercicios(n)})", "--", *datos)
            if r.returncode:
                return f"git: no se pudo hacer commit ({r.stderr.strip()[:200]})"
            commit = "commit hecho"
        if correr("remote").stdout.strip() == "":
            return f"git: {commit}; no hay remoto configurado (no se sube)."
        # --autostash: un cambio sin commit en un fichero que no es de datos no para la subida.
        tirar = correr("pull", "--rebase", "--autostash", "-q")
        if tirar.returncode:
            red = _sin_red(tirar.stderr)
            if (RAIZ / ".git" / "rebase-merge").exists() or (RAIZ / ".git" / "rebase-apply").exists():
                correr("rebase", "--abort")
            if red:
                return f"git: {commit}. Sin red: se sube la proxima vez."
            suyos = set(correr("diff", "--name-only", "HEAD...@{u}").stdout.split())
            chocan = sorted(suyos & set(correr("diff", "--name-only", "@{u}...HEAD").stdout.split()))
            return (f"git: {commit}, pero lo de otro equipo choca con lo de aqui"
                    + (f" ({', '.join(chocan[:4])})" if chocan else "")
                    + ". Se deshizo el intento: el repositorio queda como estaba y los datos estan en disco. "
                    "Hay que juntarlos a mano.")
        push = correr("push", "-q")
        if push.returncode:
            if _sin_red(push.stderr):
                return f"git: {commit}. Sin red: se sube la proxima vez."
            return f"git: {commit}, pero el push fallo ({push.stderr.strip()[:160]}). Se reintenta al proximo cierre."
        return f"git: {commit} y subido."
    except FileNotFoundError:
        return "git: no esta instalado o no esta en el PATH; los datos se guardan solo en disco."


_SIN_RED = re.compile(r"could not resolve host|unable to access|could not read from remote|connection|timed out|"
                      r"network|no route|failed to connect", re.I)


def _sin_red(stderr):
    return bool(_SIN_RED.search(stderr or ""))


def proximos_examenes(dia, ruta=None):
    ruta = Path(ruta or CALENDARIO)
    if not ruta.exists():
        return []
    with open(ruta, "rb") as f:
        datos = tomllib.load(f)
    lista = []
    for ex in datos.get("examen", []):
        fecha = date.fromisoformat(ex["fecha"])
        if fecha >= dia:
            lista.append((fecha, ex["nombre"]))
    return sorted(lista)


_TITULOS = (("integral", "INTEGRALES"), ("parcial", "PARCIALES Y EDOS"), ("derivada", "DERIVADAS"),
            ("algebra", "ALGEBRA"))


def informe(dia, fichas, ruta=None):
    entradas = registro.leer(ruta)
    prog = progreso(fichas, entradas, leer_hitos(ruta_hitos(ruta)))
    examen = abiertas_por_examen(dia)
    salida = [f"Informe a {dia.isoformat()}", ""]
    semana = [e for e in entradas if 0 <= (dia - registro.fecha(e)).days < 7]
    dias = len({registro.fecha(e) for e in semana})
    salida.append(f"Ultimos 7 dias: {dias} dias practicados, {len(semana)} ejercicios.")
    for fecha, nombre in proximos_examenes(dia)[:3]:
        salida.append(f"Examen: {nombre}, el {fecha.strftime('%d/%m')} (faltan {(fecha - dia).days} dias)")
    if FOCO:
        estado = "activo: 2 de cada 5 son parciales o EDOs" if foco_activo(fichas, entradas, prog) \
            else "apagado (ya dominado)"
        salida.append(f"Foco en parciales y EDOs: {estado}")
    salida.append("")
    for g, titulo in _TITULOS:
        abierto = prog.escalon.get(g, 1)
        salida.append(f"{titulo} (escalon abierto: {abierto})")
        tecnicas = {}
        for f in fichas.values():
            if f.grupo == g:
                tecnicas.setdefault(f.tecnica, ESCALONES[f.tipo][f.tecnica])
        for tecnica, esc in sorted(tecnicas.items(), key=lambda kv: (kv[1], kv[0])):
            if esc > abierto and tecnica not in examen:
                continue
            d = dominio(entradas, tecnica, fichas)
            if d.intentos == 0:
                estado = "sin intentos"
            elif d.intentos < MIN_DATOS:
                estado = f"{d.aciertos:g}/{d.intentos} sin ayuda (pocos datos)"
            else:
                estado = (f"{d.aciertos:g}/{d.intentos} sin ayuda, P(p > 0,7) = {d.p:.2f}, "
                          f"{d.fichas_ok}/{d.fichas_pedidas} fichas distintas acertadas")
            etiqueta = nivel(d)
            if tecnica in prog.por_nivel and etiqueta in ("sin empezar", "familiar"):
                etiqueta = "competente (prueba de nivel)"
            marca = " ✓ dominada" if d.dominada else ""
            por_examen = " (abierta por examen)" if esc > abierto else ""
            mediana = registro.mediana_segundos(entradas, tecnica)
            tiempo = f", mediana {mediana:.0f} s" if mediana else ""
            salida.append(f"  - {tecnica} [{etiqueta}]: {estado}{tiempo}{marca}{por_examen}")
        salida.append("")
    con = [e for e in entradas if e.get("confianza")]
    salida.append("CONFIANZA (lo que dices frente a lo que aciertas sin ayuda)")
    if len(con) < MIN_DATOS:
        salida.append("  pocos datos")
    else:
        for c in range(1, 6):
            grupo_c = [e for e in con if e["confianza"] == c]
            if grupo_c:
                acierto = sum(1 for e in grupo_c if e["nota"] >= 3) / len(grupo_c)
                aviso = " (pocos datos)" if len(grupo_c) < MIN_DATOS else ""
                salida.append(f"  confianza {c}: {len(grupo_c)} intentos, acierto {acierto:.0%}{aviso}")
        brier = sum((CONFIANZA_P[e["confianza"]] - (e["nota"] >= 3)) ** 2 for e in con) / len(con)
        salida.append(f"  Brier = {brier:.2f} (0 = calibracion perfecta; 0,25 = como tirar una moneda)")
    salida.append("")
    tarjetas = estados(entradas)
    vencidas = sorted((fecha_proxima(t), fid) for fid, t in tarjetas.items()
                      if fid in fichas and fecha_proxima(t) <= dia)
    salida.append(f"PENDIENTES HOY: {len(vencidas)} repasos vencidos"
                  + (": " + ", ".join(f"{fid} (desde {f.isoformat()})" for f, fid in vencidas)
                     if vencidas else ""))
    prevista = carga_prevista(fichas, entradas, dia + timedelta(1))
    salida.append("Repasos previstos: " + ", ".join(f"{d.strftime('%d/%m')}: {n}" for d, n in prevista.items()))
    salida.append(f"Repeticion implicita: {repasos_ahorrados(entradas, dia)} repasos aplazados en los ultimos 30 dias "
                  "(acertar una tecnica da por repasada la que contiene)")
    salida.append("")
    salida.extend(texto_calibracion(entradas))
    return "\n".join(salida)


def texto_calibracion(entradas):
    """¿Acierta FSRS cuando predice que te acordaras?"""
    n, filas, desviacion = calibracion(entradas)
    lineas = ["CALIBRACION DE FSRS (prediccion frente a lo que pasa; recordar = nota 2 o mas)"]
    if n < MIN_CALIBRACION:
        lineas.append(f"  {n} repasos; hacen falta {MIN_CALIBRACION} (unos 6-8 meses) para fiarse. "
                      "No hay que hacer nada.")
        return lineas
    for (lo, hi), k, pred, real in filas:
        lineas.append(f"  R entre {lo:.2f} y {hi:.2f}: {k} repasos, predicho {pred:.0%}, real {real:.0%}")
    lineas.append(f"  Desviacion media: {desviacion:.1f} puntos")
    if desviacion > 10:
        lineas.append("  AVISO: desviacion > 10 puntos. Toca ajustar la retencion objetivo (docs/DESIGN.md).")
    return lineas
