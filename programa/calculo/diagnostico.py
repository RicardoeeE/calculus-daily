"""Diagnostico de una respuesta que no cuadra: que ha pasado, sin necesidad de
que nadie la revise. Son reglas sencillas y comprobables (factor de mas o de menos, signo,
regla de la cadena o del producto olvidada, letra equivocada...). Si ninguna
encaja, al menos se ensena lo que da la comprobacion («tu resultado derivado da…»).
"""
import random

import sympy as sp

from .expresiones import X, Y, ErrorLectura, leer, mostrar
from .verificar import comparar, partir

MAX_TEXTO = 70


def _valor(expr, punto):
    try:
        v = complex(expr.subs(punto).evalf(20))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if v != v or abs(v) == float("inf") or abs(v.imag) > 1e-9 * max(1, abs(v.real)):
        return None
    return v.real


def razon_constante(a, b, semilla=0):
    """Si a = k·b para una constante k (en puntos al azar), devuelve k."""
    rng = random.Random(semilla)
    simbolos = sorted(a.free_symbols | b.free_symbols | {X}, key=str)
    razones = []
    for _ in range(200):
        punto = {s: rng.uniform(0.2, 2.5) * rng.choice((1, -1)) for s in simbolos}
        va, vb = _valor(a, punto), _valor(b, punto)
        if va is None or vb is None or abs(vb) < 1e-8:
            continue
        razones.append(va / vb)
        if len(razones) >= 8:
            break
    if len(razones) < 4:
        return None
    k = razones[0]
    if all(abs(r - k) <= 1e-6 * max(1, abs(k)) for r in razones) and abs(k - 1) > 1e-6 and abs(k) > 1e-9:
        return sp.nsimplify(k, tolerance=1e-6, rational=True)
    return None


def _corto(expr):
    texto = mostrar(sp.simplify(expr))
    return texto if len(texto) <= MAX_TEXTO else None


def _mensaje_factor(k, que):
    if k == -1:
        return f"Solo falla el signo: {que} sale con el signo cambiado."
    return (f"Casi: {que} sale {mostrar(k)} veces lo que deberia. "
            f"Revisa la constante (divide tu resultado entre {mostrar(k)}).")


def _cadena_olvidada(funcion, candidata, correcta, semilla):
    """¿Falta multiplicar por la derivada de dentro?"""
    for sub in sp.preorder_traversal(funcion):
        if isinstance(sub, (sp.exp, sp.sin, sp.cos, sp.tan, sp.log, sp.atan, sp.asin)) or \
                (isinstance(sub, sp.Pow) and not sub.exp.free_symbols and sub.base.free_symbols):
            dentro = sub.args[0] if not isinstance(sub, sp.Pow) else sub.base
            dprima = sp.diff(dentro, X)
            if dprima.free_symbols or dprima not in (0, 1):
                k = razon_constante(correcta, candidata, semilla)
                if k is not None and comparar(sp.Integer(1) * k, dprima, semilla)[0]:
                    return dentro, dprima
                if comparar(candidata * dprima, correcta, semilla)[0]:
                    return dentro, dprima
    return None


def _producto_mal(funcion, candidata, semilla):
    """¿Ha derivado cada factor por separado (f'·g')?"""
    factores = [a for a in sp.Mul.make_args(funcion) if a.free_symbols]
    if len(factores) == 2:
        u, v = factores
        constante = sp.Mul(*[a for a in sp.Mul.make_args(funcion) if not a.free_symbols])
        if comparar(candidata, constante * sp.diff(u, X) * sp.diff(v, X), semilla)[0]:
            return True
    return False


def diagnosticar(variante, respuesta):
    """Lista de explicaciones (puede ser vacia). No lanza excepciones.
    Primero los errores tipicos que el autor escribio en la ficha (estilo STACK);
    si ninguno encaja, las reglas generales."""
    try:
        propios = errores_tipicos(variante, respuesta)
        if propios:
            return propios
        return [m for m in _diagnosticar(variante, respuesta) if m]
    except Exception:  # el diagnostico nunca debe romper la sesion
        return []


def _leer_respuesta(v, texto):
    """La respuesta (o la plantilla de error) como expresion comparable."""
    tipo = v.ficha.tipo
    if tipo == "integral":
        return sp.diff(leer(texto, quitar_constante=True)[0], X)  # se compara la derivada
    if tipo in ("definida", "potencial"):
        return leer(texto, quitar_constante=True, variables="xy")[0]
    if tipo == "edo_solucion":
        return leer(texto.split("=")[-1], variables="xC")[0]
    return leer(texto.split("=")[-1], variables="xyC")[0]


def coincide_error(v, respuesta, error):
    """¿La respuesta es ese error tipico? `respuesta` = esa respuesta exacta
    (en integrales, salvo constante); `forma` = cualquier multiplo de esa forma."""
    p = v.params
    s = v.semilla
    tipo = v.ficha.tipo
    if tipo == "raices":
        from .verificar import comprobar_raices
        plantilla = error["respuesta"].format(**p)
        raices = [leer(t, variables="xi")[0] for t in plantilla.split(",")]
        return comprobar_raices(respuesta, raices).correcto
    if tipo in ("algebra", "exacta"):
        nombres = list(v.solucion) if tipo == "algebra" else ["∂M/∂y", "∂N/∂x"]
        esperados = [leer(t, variables="xy")[0] for t in error["respuesta"].format(**p).split(";")]
        dados = [leer(t, variables="xy")[0] for t in partir(respuesta, nombres)]
        return all(comparar(d + 0 * X, e + 0 * X, s)[0] for d, e in zip(dados, esperados))
    candidata = _leer_respuesta(v, respuesta)
    if "forma" in error:
        forma = leer(error["forma"].format(**p), variables="xyC")[0]
        return razon_constante(candidata, forma, s) is not None or comparar(candidata, forma, s)[0]
    plantilla = _leer_respuesta(v, error["respuesta"].format(**p))
    return comparar(candidata + 0 * X, plantilla + 0 * X, s)[0]


def errores_tipicos(v, respuesta):
    from .expresiones import limpiar
    mensajes = []
    for error in v.ficha.errores:
        try:
            if coincide_error(v, respuesta, error):
                mensajes.append(limpiar(error["mensaje"].format(**v.params)))
        except (ErrorLectura, ValueError, KeyError, TypeError):
            continue
    return mensajes


def _diagnosticar(v, respuesta):
    tipo, s = v.ficha.tipo, v.semilla
    if tipo == "integral":
        try:
            F, _ = leer(respuesta, quitar_constante=True)
        except ErrorLectura:
            return []
        f = v.funcion
        if comparar(F, f, s)[0]:
            return ["Has copiado el integrando: falta integrar."]
        if comparar(F, sp.diff(f, X), s)[0]:
            return ["Has derivado en vez de integrar."]
        d = sp.diff(F, X)
        k = razon_constante(d, f, s)
        if k is not None:
            return [_mensaje_factor(k, "al derivar tu resultado, el integrando")]
        resto = d - f
        if not resto.free_symbols and resto != 0:
            return ["Al derivar tu resultado sobra una constante: ¿un termino de mas?"]
        texto = _corto(d)
        return [f"Comprueba derivando: tu resultado derivado da {texto}, y deberia dar {mostrar(f)}."] if texto else []
    if tipo == "derivada":
        try:
            c, _ = leer(respuesta)
        except ErrorLectura:
            return []
        f, g = v.funcion, sp.diff(v.funcion, X)
        # Primero la cadena: «e^(x^2+x)» como derivada de si misma es justo olvidarla.
        cadena = _cadena_olvidada(f, c, g, s)
        if cadena:
            dentro, dprima = cadena
            return [f"Falta la regla de la cadena: multiplica por la derivada de lo de dentro, "
                    f"({mostrar(dentro)})' = {mostrar(dprima)}."]
        if comparar(c, f, s)[0]:
            return ["Has copiado la funcion: falta derivar."]
        k = razon_constante(c, g, s)
        if k is not None:
            return [_mensaje_factor(k, "tu derivada")]
        if _producto_mal(f, c, s):
            return ["Has derivado cada factor por separado. El producto se deriva asi: (f·g)' = f'·g + f·g'."]
        return []
    if tipo == "parcial":
        try:
            c, _ = leer(respuesta, variables="xy")
        except ErrorLectura:
            return []
        var = Y if v.ficha.respecto == "y" else X
        otra = X if var == Y else Y
        g = sp.diff(v.funcion, var)
        if comparar(c, sp.diff(v.funcion, otra), s)[0]:
            return [f"Has derivado respecto a {otra}; aqui se deriva respecto a {var} ({otra} es un numero)."]
        k = razon_constante(c, g, s)
        if k is not None:
            return [_mensaje_factor(k, "tu derivada parcial")]
        return [f"Recuerda: respecto a {var}, cada {otra} es un numero. Pon {otra} = 2, deriva y vuelve a ponerla."]
    if tipo == "definida":
        try:
            c, _ = leer(respuesta, quitar_constante=True)
        except ErrorLectura:
            return []
        k = razon_constante(c + sp.Integer(0) * X, v.solucion + sp.Integer(0) * X, s) if c != 0 else None
        if k == -1:
            return ["Sale con el signo cambiado: ¿has restado F(a) - F(b) en vez de F(b) - F(a)?"]
        if k is not None:
            return [_mensaje_factor(k, "el valor")]
        return []
    if tipo == "algebra":
        try:
            textos = partir(respuesta, list(v.solucion))
            dados = [leer(t)[0] for t in textos]
        except ErrorLectura:
            return []
        mal = [n for (n, ok), d in zip(v.solucion.items(), dados) if not comparar(d + 0 * X, ok + 0 * X, s)[0]]
        signo = [n for (n, ok), d in zip(v.solucion.items(), dados)
                 if n in mal and comparar(-d + 0 * X, ok + 0 * X, s)[0]]
        mensajes = []
        if mal and len(mal) < len(v.solucion):
            bien = [n for n in v.solucion if n not in mal]
            mensajes.append(f"{', '.join(bien)} bien; revisa {', '.join(mal)}.")
        if signo:
            mensajes.append(f"En {', '.join(signo)} solo falla el signo.")
        return mensajes
    if tipo == "raices":
        try:
            dadas = [leer(t, variables="xi")[0] for t in respuesta.replace("±", ",").split(",") if t.strip()]
        except ErrorLectura:
            return []
        if dadas and all(any(comparar(-d + 0 * X, r + 0 * X, s)[0] for r in v.solucion) for d in dadas):
            return ["Signos cambiados: si (r - a) es un factor, la raiz es a, no -a."]
        return []
    if tipo == "edo_solucion":
        try:
            yv, _ = leer(respuesta.split("=")[-1], variables="xC")
        except ErrorLectura:
            return []
        resto = sp.simplify(v.ficha.operador(v.params)(yv))
        texto = _corto(resto)
        return [f"Al sustituir tu y en la EDO queda {texto}, y deberia quedar {mostrar(v.funcion)}."] if texto else []
    return []
