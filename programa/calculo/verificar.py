"""Comprobar respuestas de forma objetiva.

Integral: se deriva la respuesta y se compara con el integrando. Asi vale
cualquier primitiva correcta (difieren en una constante). Derivada: se compara
con la derivada exacta. Primero se intenta de forma simbolica y, si no basta,
en puntos al azar del dominio real.
"""
import random
import re
from dataclasses import dataclass, field

import sympy as sp

from .expresiones import C1, C2, X, Y, ErrorLectura, leer, mostrar

PUNTOS = 20
TOLERANCIA = 1e-7


@dataclass
class Resultado:
    correcto: bool
    avisos: list = field(default_factory=list)
    error: str | None = None  # la respuesta no se pudo leer
    leido: str | None = None  # como se ha interpretado la respuesta («He leido: ...»)


@dataclass
class Lectura:
    """Lo que se ha leido de una respuesta, sin corregir: las mismas funciones
    leer_* las usan comprobar_* y la vista previa (servicio.leer)."""
    exprs: list                 # expresiones de sympy
    leido: str                  # texto de «He leido: ...»
    nombres: list | None = None  # etiquetas si hay varios valores («h», «∂M/∂y»)
    con_c: bool = False         # llevaba constante de integracion
    prefijo: str = ""           # «y = » en las EDOs
    sufijo: str = ""            # « + C» en las primitivas


def _valor(expr, punto):
    """Valor numerico complejo de expr en el punto {simbolo: valor}, o None si
    no es finito."""
    try:
        v = complex(expr.subs(punto).evalf(30))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if v != v or abs(v) == float("inf"):  # NaN o infinito
        return None
    return v


def _es_real(v):
    return v is not None and abs(v.imag) <= TOLERANCIA * max(1.0, abs(v.real))


def _iguales(a, b):
    return abs(a - b) <= TOLERANCIA * max(1.0, abs(a), abs(b))


def _puntos(rng, simbolos):
    """Puntos {x: .., y: ..}: mezcla de valores pequenos, medianos y negativos;
    evita enteros exactos."""
    for _ in range(400):
        yield {s: rng.choice((rng.uniform(-4, 4), rng.uniform(0.05, 1.5), rng.uniform(-1.5, -0.05)))
               for s in simbolos}


def comparar(candidata, referencia, semilla=0, exigir_real=None):
    """True si las dos expresiones coinciden donde la referencia es real.

    Devuelve (coinciden, dominio_incompleto). dominio_incompleto indica que la
    candidata (o exigir_real, p. ej. la primitiva cuya derivada se compara) no
    es real en puntos donde la referencia si lo es: tipicamente falta un valor
    absoluto en un logaritmo.
    """
    rng = random.Random(semilla)
    simbolos = sorted({X} | candidata.free_symbols | referencia.free_symbols
                      | (exigir_real.free_symbols if exigir_real is not None else set()), key=str)
    # Comprobacion simbolica barata (simplify puede tardar minutos con raices y
    # logaritmos); lo demas se decide en puntos al azar.
    diferencia = candidata - referencia
    if diferencia == 0 or sp.expand(diferencia) == 0:
        if exigir_real is None:
            return True, False
        fuera = 0
        for x0, _ in zip(_puntos(rng, simbolos), range(PUNTOS * 3)):
            if _es_real(_valor(referencia, x0)) and not _es_real(_valor(exigir_real, x0)):
                fuera += 1
        return True, fuera > 0
    validos = fuera = 0
    for x0 in _puntos(rng, simbolos):
        r = _valor(referencia, x0)
        if not _es_real(r):
            continue
        c = _valor(candidata, x0)
        if not _es_real(c):
            fuera += 1
            continue
        # La derivada se compara igual; si la primitiva no es real aqui, se avisa
        # (falta |·| en un ln) pero no se suspende.
        if exigir_real is not None and not _es_real(_valor(exigir_real, x0)):
            fuera += 1
        if not _iguales(c.real, r.real):
            return False, False
        validos += 1
        if validos >= PUNTOS:
            break
    if validos == 0:
        return False, fuera > 0
    return True, fuera > 0


def leer_primitiva(respuesta):
    primitiva, con_c = leer(respuesta, quitar_constante=True)
    sufijo = " + C" if con_c else ""
    return Lectura([primitiva], mostrar(primitiva) + sufijo, con_c=con_c, sufijo=sufijo)


def leer_numero(respuesta):
    candidato, con_c = leer(respuesta, quitar_constante=True)
    if candidato.free_symbols:
        raise ErrorLectura("en una integral definida el resultado es un numero, sin x")
    return Lectura([candidato], mostrar(candidato), con_c=con_c)


def leer_una(respuesta, variables="x"):
    candidata, _ = leer(respuesta, variables=variables)
    return Lectura([candidata], mostrar(candidata))


def leer_potencial(respuesta):
    f, _ = leer(respuesta, quitar_constante=True, variables="xy")
    return Lectura([f], mostrar(f))


def leer_edo(respuesta):
    y, _ = leer(respuesta.split("=")[-1], variables="xC")
    return Lectura([y], "y = " + mostrar(y), prefijo="y = ")


def leer_expresion(respuesta):
    candidata, _ = leer(respuesta.split("=")[-1], variables="xC")
    return Lectura([candidata], mostrar(candidata))


def comprobar_integral(respuesta, integrando, semilla=0):
    try:
        lec = leer_primitiva(respuesta)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    primitiva, con_c = lec.exprs[0], lec.con_c
    derivada = sp.diff(primitiva, X)
    ok, dominio = comparar(derivada, integrando, semilla, exigir_real=primitiva)
    avisos = []
    if ok and not con_c:
        avisos.append("falta +C")
    if ok and dominio:
        avisos.append("vale solo en parte del dominio: ¿falta |·| dentro de un ln?")
    return Resultado(ok, avisos, leido=lec.leido)


def _valor_igual(candidato, valor):
    try:
        return abs(complex(sp.N(candidato - valor, 30))) <= 1e-9 * max(1.0, abs(complex(sp.N(valor, 30))))
    except (TypeError, ValueError):
        return False


def comprobar_valor(respuesta, valor):
    """Integral definida: la respuesta es un numero (puede ser 2 ln 3, π/4...)."""
    try:
        lec = leer_numero(respuesta)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    ok = _valor_igual(lec.exprs[0], valor)
    return Resultado(ok, ["en una definida no va +C"] if ok and lec.con_c else [], leido=lec.leido)


def _clave(nombre):
    """«∂M/∂y», «M_y», «dM/dy» -> «My»; «h» -> «h»."""
    return re.sub(r"[\s∂d_/']", "", nombre)


def partir(respuesta, nombres):
    """Separa una respuesta con varios valores, en el orden de `nombres`.

    Separadores: «;» o coma (la coma entre dos cifras es decimal: «0,5»). Si
    los valores llevan nombre («k = 9, h = 1»), se emparejan por nombre;
    si no, por orden. Devuelve lista de textos o lanza ErrorLectura.
    """
    if ";" in respuesta:
        trozos = respuesta.split(";")
    else:
        trozos = re.split(r"(?<!\d),|,(?!\d)", respuesta)
    trozos = [t.strip() for t in trozos if t.strip()]
    if len(trozos) != len(nombres):
        raise ErrorLectura(f"hacen falta {len(nombres)} valores ({', '.join(nombres)}), "
                           "separados por comas o por «;»")
    etiquetas, valores = [], []
    for t in trozos:
        if "=" in t:
            izq, der = t.rsplit("=", 1)
            etiquetas.append(_clave(izq))
            valores.append(der.strip())
        else:
            etiquetas.append(None)
            valores.append(t)
    claves = [_clave(n) for n in nombres]
    if all(etiquetas):
        orden = []
        for e in etiquetas:
            exactas = [i for i, c in enumerate(claves) if c == e]
            parecidas = [i for i, c in enumerate(claves) if c.lower() == e.lower()]
            encontradas = exactas or (parecidas if len(parecidas) == 1 else [])
            if not encontradas:
                raise ErrorLectura(f"no reconozco el nombre «{e}»; usa {', '.join(nombres)}")
            orden.append(encontradas[0])
        if sorted(orden) != list(range(len(nombres))):
            raise ErrorLectura("hay un nombre repetido")
        resultado = [None] * len(nombres)
        for i, v in zip(orden, valores):
            resultado[i] = v
        return resultado
    return valores


def leer_valores(respuesta, nombres):
    nombres = list(nombres)
    numeros = [leer(t)[0] for t in partir(respuesta, nombres)]
    leido = ", ".join(f"{n} = {mostrar(v)}" for n, v in zip(nombres, numeros))
    return Lectura(numeros, leido, nombres=nombres)


def comprobar_valores(respuesta, valores):
    """Algebra: «3, 4», «h = 3; k = 4» o «k = 4, h = 3»."""
    try:
        lec = leer_valores(respuesta, valores)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    return Resultado(all(_valor_igual(n, v) for n, v in zip(lec.exprs, valores.values())), leido=lec.leido)


def comprobar_derivada(respuesta, funcion, semilla=0):
    try:
        lec = leer_una(respuesta)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    ok, _ = comparar(lec.exprs[0], sp.diff(funcion, X), semilla)
    return Resultado(ok, leido=lec.leido)


def comprobar_parcial(respuesta, funcion, variable, semilla=0):
    """Derivada parcial respecto a `variable` (x o y): la otra letra es constante."""
    try:
        lec = leer_una(respuesta, variables="xy")
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    ok, _ = comparar(lec.exprs[0], sp.diff(funcion, variable), semilla)
    return Resultado(ok, leido=lec.leido)


NOMBRES_PAR = ("∂M/∂y", "∂N/∂x")


def leer_par(respuesta, nombres=NOMBRES_PAR):
    """Dos expresiones en x, y: «∂M/∂y, ∂N/∂x», o con nombres en cualquier orden.
    «3x^2 e^(x^3) = 3x^2 e^(x^3)» tambien vale (las dos partes de la igualdad)."""
    texto = respuesta
    if "," not in texto and ";" not in texto and texto.count("=") == 1:
        texto = texto.replace("=", ",")
    candidatas = [leer(t, variables="xy")[0] for t in partir(texto, list(nombres))]
    leido = ", ".join(f"{n} = {mostrar(c)}" for n, c in zip(nombres, candidatas))
    return Lectura(candidatas, leido, nombres=list(nombres))


def comprobar_par(respuesta, esperadas, semilla=0, nombres=NOMBRES_PAR):
    try:
        lec = leer_par(respuesta, nombres)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    return Resultado(all(comparar(c, e, semilla)[0] for c, e in zip(lec.exprs, esperadas)), leido=lec.leido)


def comprobar_potencial(respuesta, m, n, semilla=0):
    """Funcion potencial F(x, y) de M dx + N dy: F_x = M y F_y = N (salvo constante)."""
    try:
        f = leer_potencial(respuesta).exprs[0]
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    ok_x = comparar(sp.diff(f, X), m, semilla)[0]
    ok_y = comparar(sp.diff(f, Y), n, semilla)[0]
    if ok_x and not ok_y:
        return Resultado(False, ["∂F/∂x = M bien, pero ∂F/∂y no da N: revisa φ(y)"], leido=mostrar(f))
    if ok_y and not ok_x:
        return Resultado(False, ["∂F/∂y = N bien, pero ∂F/∂x no da M: revisa φ(x)"], leido=mostrar(f))
    return Resultado(ok_x and ok_y, leido=mostrar(f))


def leer_raices(respuesta):
    """Raices separadas por comas (o «;»); vale «2±3i» (se parte en dos) y «0,5» es decimal."""
    texto = respuesta.replace("+-", "±").replace("+/-", "±")
    trozos = []
    # Mismo criterio que `partir`: «;» si lo hay; si no, la coma entre dos cifras es decimal («0,5, 3»).
    for t in (texto.split(";") if ";" in texto else re.split(r"(?<!\d),|,(?!\d)", texto)):
        t = t.strip()
        if not t:
            continue
        t = t.split("=")[-1].strip()
        if "±" in t:
            a, b = t.split("±", 1)
            trozos += [f"({a or 0}) + ({b})", f"({a or 0}) - ({b})"]
        else:
            trozos.append(t)
    dadas = [leer(t, variables="xi")[0] for t in trozos]
    if any(d.free_symbols for d in dadas):
        raise ErrorLectura("las raices son numeros (sin x); la i es la unidad imaginaria")
    return Lectura(dadas, ", ".join(mostrar(d) for d in dadas))


def comprobar_raices(respuesta, raices):
    """Raices de la ecuacion caracteristica, en cualquier orden. Vale «2±3i»;
    una raiz doble puede escribirse una vez («2») o dos («2, 2»)."""
    try:
        lec = leer_raices(respuesta)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    dadas, leido = lec.exprs, lec.leido
    distintas = []
    for r in raices:
        if not any(_valor_igual(r, d) for d in distintas):
            distintas.append(r)
    sobran = [d for d in dadas if not any(_valor_igual(d, r) for r in distintas)]
    faltan = [r for r in distintas if not any(_valor_igual(d, r) for d in dadas)]
    if sobran or faltan:
        return Resultado(False, leido=leido)
    avisos = []
    if len(distintas) < len(raices):
        avisos.append("hay una raiz doble: en la solucion general lleva tambien x·e^(rx)")
    return Resultado(True, avisos, leido=leido)


def comprobar_edo(respuesta, operador, rhs, constantes, semilla=0):
    """Solucion de una EDO lineal: se sustituye en la ecuacion (con C1 y C2
    cualesquiera). Si es la general, las dos constantes deben ser independientes."""
    try:
        lec = leer_edo(respuesta)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    y, leido = lec.exprs[0], lec.leido
    tiene = [c for c in (C1, C2) if c in y.free_symbols]
    if constantes == 0 and tiene:
        return Resultado(False, ["aqui se pide una solucion particular, sin C1 ni C2"], leido=leido)
    if constantes and len(tiene) < constantes:
        return Resultado(False, ["la solucion general de orden 2 lleva dos constantes, C1 y C2"], leido=leido)
    ok, _ = comparar(sp.expand(operador(y) - rhs), sp.Integer(0), semilla)
    if not ok:
        return Resultado(False, leido=leido)
    if constantes:
        y1, y2 = sp.diff(y, C1), sp.diff(y, C2)
        w = y1 * sp.diff(y2, X) - sp.diff(y1, X) * y2
        if comparar(w, sp.Integer(0), semilla)[0]:
            return Resultado(False, ["las dos partes con C1 y C2 son proporcionales: falta otra solucion independiente"],
                             leido=leido)
    return Resultado(True, leido=leido)


def comprobar_expresion(respuesta, valor, semilla=0):
    """Resultado de un calculo (wronskiano, L[y]...): una expresion en x."""
    try:
        lec = leer_expresion(respuesta)
    except ErrorLectura as exc:
        return Resultado(False, error=str(exc))
    ok, _ = comparar(lec.exprs[0], valor, semilla)
    return Resultado(ok, leido=lec.leido)
