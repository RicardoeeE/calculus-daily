"""Pasos automaticos para el nivel 4 de pista.

`pasos(variante)` devuelve frases cortas en español que llevan al resultado.
- integral: traduce el arbol de `sympy.integrals.manualintegrate.integral_steps`.
- derivada: por estructura (suma, producto, cociente, cadena).
- parcial: la otra letra es un numero y se deriva como en una variable.
Otros tipos devuelven [] (la pista 4 da solo el resultado).
La ultima frase siempre es «Resultado: <solucion de la ficha>».
"""
import sympy as sp
from sympy.integrals.manualintegrate import integral_steps

from .expresiones import X, Y, mostrar

MAX_PASOS = 8
_U = sp.Symbol("u")


def _m(expr):
    """Texto de clase; la variable interna de sympy (_u) se muestra como u."""
    if isinstance(expr, sp.Basic):
        return mostrar(expr).replace("_u", "u")
    return str(expr).replace("_u", "u")


def _p(expr):
    """Con parentesis si es suma/resta."""
    t = _m(expr)
    return f"({t})" if isinstance(expr, sp.Basic) and expr.is_Add else t


def _recortar(lineas):
    """lineas: lista de (profundidad, texto). Max ~8: si sobran, se quitan los anidados
    mas profundos primero."""
    prof = max((l[0] for l in lineas), default=0)
    while len(lineas) > MAX_PASOS and prof > 0:
        prof -= 1
        lineas = [l for l in lineas if l[0] <= prof]
    textos = [t for _, t in lineas]
    if len(textos) > MAX_PASOS:
        textos = textos[:MAX_PASOS - 1] + ["... (los pasos restantes siguen el mismo patron)"]
    return textos


# ---------------------------------------------------------------- integrales

def _integrar(regla, out, d=0):
    n = type(regla).__name__
    v = getattr(regla, "variable", None)
    dv_ = _m(v) if v is not None else "x"
    f = getattr(regla, "integrand", None)

    if n == "AlternativeRule":
        mejor = None
        for alt in regla.alternatives:
            tmp = []
            _integrar(alt, tmp, d)
            clave = (len(tmp), sp.count_ops(alt.u_func) if type(alt).__name__ == "URule" else 0)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, tmp)
        out.extend(mejor[1] if mejor else [])
    elif n == "ConstantRule":
        out.append((d, f"Constante: ∫ {_m(f)} d{dv_} = {_m(f)}·{dv_}"))
    elif n == "ConstantTimesRule":
        out.append((d, f"Saca la constante {_p(regla.constant)}: ∫ {_m(f)} d{dv_} = {_p(regla.constant)}·∫ {_m(regla.other)} d{dv_}"))
        _integrar(regla.substep, out, d + 1)
    elif n == "AddRule":
        out.append((d, f"Integra término a término: ∫ {_m(f)} d{dv_}"))
        for s in regla.substeps:
            _integrar(s, out, d + 1)
    elif n == "URule":
        uf = regla.u_func
        du = sp.diff(uf, v)
        out.append((d, f"Sustitución: u = {_m(uf)}, du = {_m(du)} d{dv_}"))
        out.append((d, f"Queda ∫ {_m(regla.substep.integrand)} du"))
        _integrar(regla.substep, out, d + 1)
        out.append((d, f"Deshaz el cambio: u = {_m(uf)}"))
    elif n == "PartsRule":
        u, dv = regla.u, regla.dv
        vv = sp.integrate(dv, v)
        du = sp.diff(u, v)
        out.append((d, f"Por partes: u = {_m(u)}, dv = {_m(dv)} d{dv_}"))
        out.append((d, f"Entonces du = {_m(du)} d{dv_} y v = {_m(vv)}"))
        out.append((d, f"∫u dv = u·v − ∫v du = {_m(u * vv)} − ∫ {_m(vv * du)} d{dv_}"))
        if regla.second_step is not None:
            _integrar(regla.second_step, out, d + 1)
    elif n == "CyclicPartsRule":
        usos = "; después ".join(f"u = {_m(r.u)}, dv = {_m(r.dv)} d{dv_}" for r in regla.parts_rules)
        out.append((d, f"Por partes dos veces ({usos}): la integral original I reaparece"))
        out.append((d, "Despeja I de la ecuación que sale (I = algo − k·I)"))
    elif n == "RewriteRule":
        out.append((d, f"Reescribe: {_m(f)} = {_m(regla.rewritten)}"))
        _integrar(regla.substep, out, d + 1)
    elif n == "ReciprocalRule":
        out.append((d, f"Logaritmo: ∫ 1/{_p(regla.base)} d{dv_} = ln|{_m(regla.base)}|"))
    elif n == "PowerRule" and f is not None:
        out.append((d, f"Potencia: ∫ {_m(f)} d{dv_} = {_m(sp.integrate(f, v))}"))
    elif n == "ExpRule":
        out.append((d, f"Exponencial: ∫ {_m(f)} d{dv_} = {_m(sp.integrate(f, v))}"))
    elif n == "ArctanRule":
        out.append((d, f"Arcotangente: ∫ {_m(f)} d{dv_} = {_m(sp.integrate(f, v))}"))
    elif n in ("SinRule", "CosRule") or n.endswith("TrigRule"):
        out.append((d, f"Trigonométrica inmediata: ∫ {_m(f)} d{dv_} = {_m(sp.integrate(f, v))}"))
    else:
        if n == "DontKnowRule":
            raise ValueError("sympy no sabe")
        sub = getattr(regla, "substep", None)
        out.append((d, f"Paso: {n.replace('Rule', '')} sobre {_m(f)}"))
        if sub is not None:
            _integrar(sub, out, d + 1)


LIMITE_S = 5.0  # alguna integral tarda 30 s en sympy: en una sesion, mejor solo el resultado


def _pasos_integral(v):
    """Con limite de tiempo: si sympy tarda mas de LIMITE_S, no hay pasos."""
    import threading
    resultado = []

    def trabajo():
        try:
            resultado.append(_pasos_integral_sin_limite(v))
        except Exception:
            resultado.append([])

    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    hilo.join(LIMITE_S)
    return resultado[0] if resultado else []


def _pasos_integral_sin_limite(v):
    f = v.funcion
    out = []
    if f.is_rational_function(X):
        ap = sp.apart(f, X)
        if ap.is_Add and ap != f:
            out.append((0, f"Fracciones simples: {_m(f)} = {_m(ap)}"))
            out.append((0, "Integra cada fracción por separado"))
            for t in ap.args:
                _integrar(integral_steps(t, X), out, 1)
            return _recortar(out)
    _integrar(integral_steps(f, X), out)
    return _recortar(out)


# ------------------------------------------------------------------ derivadas

def _simple(f, var):
    """Se deriva con la tabla, sin pasos."""
    if not f.has(var):
        return True
    if f == var:
        return True
    if f.is_Pow and f.base == var and not f.exp.has(var):
        return True
    if f.is_Mul:
        c, r = f.as_independent(var)
        if c != 1:
            return _simple(r, var)
    if f.is_Function and len(f.args) == 1 and f.args[0] == var:
        return True
    return False


def _externa(f, var):
    """(fuera(u), dentro) si f es una composicion; si no, None."""
    if f.is_Pow:
        b, e = f.args
        if e.has(var) and not b.has(var):
            return b ** _U, e
        if not e.has(var) and b != var:
            return _U ** e, b
    elif f.is_Function and len(f.args) == 1 and f.args[0] != var:
        return f.func(_U), f.args[0]
    return None


def _derivar(f, var, out, d=0):
    if _simple(f, var):
        return
    if f.is_Add:
        if d > 0 and all(_simple(t, var) for t in f.args):
            return
        out.append((d, "Suma: se deriva término a término: " + " + ".join(f"({_m(t)})'" for t in f.args)))
        for t in f.args:
            if d < 2:
                _derivar(t, var, out, d + 1)
        return
    if f.is_Mul:
        c, r = f.as_independent(var)
        if c != 1:
            out.append((d, f"La constante sale: ({_m(f)})' = {_p(c)}·({_m(r)})'"))
            if d < 2:
                _derivar(r, var, out, d + 1)
            return
        num, den = f.as_numer_denom()
        if den != 1 and den.has(var) and num.has(var):
            dn, dd = sp.diff(num, var), sp.diff(den, var)
            out.append((d, f"Cociente: (f/g)' = (f'g − f g')/g² con f = {_m(num)}, g = {_m(den)}"))
            out.append((d, f"f' = {_m(dn)}, g' = {_m(dd)}; queda ({_p(dn * den)} − {_p(num * dd)})/({_m(den)})²"))
            if d < 2:
                _derivar(num, var, out, d + 1)
                _derivar(den, var, out, d + 1)
            return
        a, b = f.args[0], sp.Mul(*f.args[1:])
        da, db = sp.diff(a, var), sp.diff(b, var)
        out.append((d, f"Producto: (f·g)' = f'·g + f·g' con f = {_m(a)}, g = {_m(b)}"))
        out.append((d, f"f' = {_m(da)}, g' = {_m(db)}; queda {_m(da * b)} + {_m(a * db)}"))
        if d < 2:
            _derivar(a, var, out, d + 1)
            _derivar(b, var, out, d + 1)
        return
    comp = _externa(f, var)
    if comp is not None:
        fuera, dentro = comp
        dfuera = sp.diff(fuera, _U)
        out.append((d, f"Cadena: fuera {_m(fuera)}, dentro u = {_m(dentro)}"))
        out.append((d, f"(fuera)'(dentro)·(dentro)' = ({_m(dfuera.subs(_U, dentro))})·({_m(sp.diff(dentro, var))})"))
        if d < 2:
            _derivar(dentro, var, out, d + 1)


def _lineas_derivada(g, var):
    out = []
    _derivar(g, var, out)
    if not out:
        out.append((0, f"Se deriva directamente con la tabla: ({_m(g)})' = {_m(sp.diff(g, var))}"))
    return out


def _pasos_derivada(v):
    return _recortar(_lineas_derivada(v.funcion, X))


def _pasos_parcial(v):
    resp = v.ficha.respecto
    var = Y if resp == "y" else X
    otra = "x" if resp == "y" else "y"
    out = [(0, f"Respecto a {resp}, {otra} es un número (constante)")]
    out += _lineas_derivada(v.funcion, var)
    return _recortar(out)


def pasos(variante):
    """Frases del paso a paso; [] si no hay (entonces solo se da el resultado)."""
    tipo = variante.ficha.tipo
    try:
        if tipo == "integral":
            lineas = _pasos_integral(variante)
        elif tipo == "derivada":
            lineas = _pasos_derivada(variante)
        elif tipo == "parcial":
            lineas = _pasos_parcial(variante)
        else:
            return []
    except Exception:
        return []
    if not lineas:
        return []
    return lineas + [f"Resultado: {variante.solucion_texto}"]
