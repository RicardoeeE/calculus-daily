"""LaTeX con la notacion de clase, para la ventana (KaTeX).

Printer propio sobre el de sympy: sen, tg, arcsen, arctan, ln con |x|,
order="none" (no reordena mas de lo que sympy ya hizo al leer) y decimales
recortados como en `expresiones.mostrar`.
"""
import re

import sympy as sp
from sympy.printing.latex import LatexPrinter

from .expresiones import ErrorLectura, X, leer, limpiar


class Impresora(LatexPrinter):
    _NOMBRES = {
        "sin": r"\operatorname{sen}",
        "tan": r"\operatorname{tg}",
        "arcsin": r"\operatorname{arcsen}",
        "sinh": r"\operatorname{senh}",
    }

    def __init__(self, settings=None):
        base = {"order": "none", "ln_notation": True, "inv_trig_style": "full"}
        super().__init__({**base, **(settings or {})})

    def _hprint_Function(self, func):
        return self._NOMBRES.get(func) or super()._hprint_Function(func)

    def _print_log(self, expr, exp=None):
        arg = expr.args[0]
        if isinstance(arg, sp.Abs):
            tex = r"\ln\left|%s\right|" % self._print(arg.args[0])
            return tex if exp is None else r"\left(%s\right)^{%s}" % (tex, exp)
        return super()._print_log(expr, exp)


def latex(expr):
    """Expresion de sympy -> LaTeX con la notacion de clase."""
    if isinstance(expr, sp.Basic) and expr.has(sp.Float):
        expr = expr.xreplace({f: sp.Float(float(f), 6) for f in expr.atoms(sp.Float)})
        tex = Impresora().doprint(expr)
        tex = re.sub(r"(\d+\.\d*?[1-9])0+\b", r"\1", tex)
        return re.sub(r"(\d+)\.0+\b", r"\1", tex)
    return Impresora().doprint(expr)


def _nombre(n):
    """«∂M/∂y» -> \\frac{\\partial M}{\\partial y}; «h» -> h; «C1» -> C_{1}."""
    m = re.fullmatch(r"∂(\w)/∂(\w)", n)
    if m:
        return rf"\frac{{\partial {m.group(1)}}}{{\partial {m.group(2)}}}"
    m = re.fullmatch(r"([A-Za-z])(\d+)", n)
    if m:
        return f"{m.group(1)}_{{{m.group(2)}}}"
    return n if re.fullmatch(r"[A-Za-z]", n) else rf"\text{{{n}}}"


def latex_lectura(lectura):
    """LaTeX de una `verificar.Lectura` (lo mismo que dice «He leido», en formula)."""
    if lectura.nombres:
        cuerpo = ", ".join(f"{_nombre(n)} = {latex(e)}" for n, e in zip(lectura.nombres, lectura.exprs))
    else:
        cuerpo = ", ".join(latex(e) for e in lectura.exprs)
    prefijo = "y = " if lectura.prefijo else ""
    return prefijo + cuerpo + (" + C" if lectura.sufijo else "")


def _plano(e):
    """Arbol sin evaluar mas legible: sin factores 1, con el signo delante y
    sin productos anidados (el parser deja «-a» como (-1)·a)."""
    if not e.args:
        return e
    args = [_plano(a) for a in e.args]
    if isinstance(e, sp.Mul):
        factores = []
        for a in args:
            factores += list(a.args) if isinstance(a, sp.Mul) else [a]
        signo, resto = 1, []
        for a in factores:
            if a == -1:
                signo = -signo
            elif a != 1:
                resto.append(a)
        if not resto:
            return sp.Integer(signo)
        if signo < 0 and resto[0].is_Number:
            resto[0], signo = -resto[0], 1
        if signo < 0:
            resto.insert(0, sp.Integer(-1))
        return resto[0] if len(resto) == 1 else sp.Mul(*resto, evaluate=False)
    if isinstance(e, (sp.Add, sp.Pow)):
        return e.func(*args, evaluate=False)
    return e.func(*args)


def _tal_cual(texto, variables="x"):
    """LaTeX de un texto de enunciado sin que sympy lo simplifique (que a veces
    regala la pista: 1/(x√x) -> x^(-3/2))."""
    return latex(_plano(leer(texto, variables=variables, evaluar=False)[0]))


def _entre_parentesis(texto, variables="x"):
    expr = _plano(leer(texto, variables=variables, evaluar=False)[0])
    tex = latex(expr)
    return rf"\left({tex}\right)" if isinstance(expr, sp.Add) else tex


def enunciado_latex(variante):
    """LaTeX de la formula del enunciado, o None si el tipo no tiene una formula
    que se pueda leer (algebra, EDOs, calculos: se ensena el texto)."""
    f = variante.ficha
    try:
        if f.tipo == "integral":
            return rf"\int {_entre_parentesis(variante.expresion)} \, dx"
        if f.tipo == "definida":
            a, b = (_tal_cual(limpiar(l.format(**variante.params))) for l in f.limites)
            return rf"\int_{{{a}}}^{{{b}}} {_entre_parentesis(variante.expresion)} \, dx"
        if f.tipo == "derivada":
            return rf"\frac{{d}}{{dx}}\left[ {_tal_cual(variante.expresion)} \right]"
        if f.tipo == "parcial":
            return rf"\frac{{\partial}}{{\partial {f.respecto}}}\left[ {_tal_cual(variante.expresion, 'xy')} \right]"
        if f.tipo in ("exacta", "potencial"):
            m = _tal_cual(limpiar(f.m.format(**variante.params)), "xy")
            n = _tal_cual(limpiar(f.n.format(**variante.params)), "xy")
            return rf"\left({m}\right) dx + \left({n}\right) dy = 0"
        if f.tipo == "raices":
            pol = _plano(leer(limpiar(f.enunciado.format(**variante.params)), evaluar=False)[0])
            return latex(pol.xreplace({X: sp.Symbol("r")})) + " = 0"
    except (ErrorLectura, KeyError, IndexError, TypeError, ValueError):
        return None
    return None


# ---------- Notacion de clase -> LaTeX, tal cual ----------
#
# Conversor propio (sin sympy): lee lo que esta escrito con la notacion de clase
# (x^2, sen x, ln|x|, e^(2x), √(x+1), ∫ ... dx, d/dx, ∂M/∂y, y'', C1, y_p) y lo
# escribe en LaTeX SIN reordenar ni simplificar: KaTeX ensena lo mismo que el texto,
# con fracciones de verdad. Lo que no sabe leer lanza NoEsFormula y se queda en texto.

class NoEsFormula(ValueError):
    """El trozo no se puede pasar a LaTeX: se ensena como texto."""


FUNCIONES = {
    "sen": r"\operatorname{sen}", "sin": r"\sin", "cos": r"\cos", "tg": r"\operatorname{tg}", "tan": r"\tan",
    "sec": r"\sec", "csc": r"\csc", "cosec": r"\operatorname{cosec}", "cot": r"\cot", "cotg": r"\operatorname{cotg}",
    "ln": r"\ln", "log": r"\log", "exp": r"\exp", "arctan": r"\arctan", "arctg": r"\operatorname{arctg}",
    "arcsen": r"\operatorname{arcsen}", "arcsin": r"\arcsin", "arccos": r"\arccos",
    "senh": r"\operatorname{senh}", "sinh": r"\sinh", "cosh": r"\cosh", "tanh": r"\tanh",
}
_FUNC_ORDEN = sorted(FUNCIONES, key=len, reverse=True)
GRIEGAS = {"α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\varepsilon", "θ": r"\theta",
           "λ": r"\lambda", "μ": r"\mu", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "φ": r"\varphi",
           "ω": r"\omega", "π": r"\pi", "Δ": r"\Delta", "∞": r"\infty"}
DIFERENCIALES = set("xyztuvrs")
_RELACIONES = {"=": "=", "≠": r"\neq", "<": "<", ">": ">", "≤": r"\leq", "≥": r"\geq", "→": r"\to",
               "⇒": r"\Rightarrow", "≈": r"\approx"}
_SIGNOS = {"+": "+", "-": "-", "−": "-", "±": r"\pm", "∓": r"\mp"}
_POR = {"·": r"\cdot", "*": r"\cdot", "×": r"\times"}
_ABRE = {"(": (r"\left(", r"\right)", ")"), "[": (r"\left[", r"\right]", "]"), "{": (r"\left\{", r"\right\}", "}")}
_DIFERENCIAL = re.compile(r"d/d([a-z])(?![A-Za-z])")
_PARCIAL = re.compile(r"∂([A-Za-z]?)/∂([a-z])(?![A-Za-z])")
_INT_DE = re.compile(r"∫\s*de\s+(\S+?)\s+a\s+(\S+?)\s+de(?![A-Za-z])")
MAX_FORMULA = 300
_ALTO = re.compile(r"\\frac|\\int|\\sqrt|\\left")


class _Tok:
    __slots__ = ("tipo", "valor", "espacio")

    def __init__(self, tipo, valor, espacio):
        self.tipo, self.valor, self.espacio = tipo, valor, espacio


def _tokens(texto, estricto):
    """Fichas lexicas. `estricto` (texto sin marcar): una tira de letras que no es
    funcion ni xy, dx... es una palabra, no una formula."""
    sal, i, n, espacio = [], 0, len(texto), False

    def poner(tipo, valor):
        nonlocal espacio
        sal.append(_Tok(tipo, valor, espacio))
        espacio = False

    while i < n:
        c = texto[i]
        if c.isspace():
            espacio, i = True, i + 1
            continue
        m = _PARCIAL.match(texto, i)
        if m:
            poner("parcial", (m.group(1), m.group(2)))
            i = m.end()
            continue
        m = _DIFERENCIAL.match(texto, i)
        if m:
            poner("dop", m.group(1))
            i = m.end()
            continue
        m = re.compile(r"\d+(?:\.\d+)?").match(texto, i)
        if m:
            poner("num", m.group())
            i = m.end()
            continue
        m = re.compile(r"[A-Za-z]+").match(texto, i)
        if m:
            tira, i = m.group(), m.end()
            if len(tira) == 2 and tira[0] == "d" and tira[1] in DIFERENCIALES:
                poner("dif", tira[1])
                continue
            if estricto and not _tira_formula(tira):
                raise NoEsFormula(f"palabra: {tira}")
            j = 0
            while j < len(tira):
                f = next((f for f in _FUNC_ORDEN if tira.startswith(f, j)), None)
                if f:
                    poner("func", f)
                    j += len(f)
                    continue
                letra, j = tira[j], j + 1
                sub = None
                if j == len(tira):   # subindice: C1, y2, r1 (no e2), y_p, F_x, x_0
                    m2 = re.compile(r"\d+").match(texto, i) if letra != "e" else None
                    if m2 is None:
                        m2 = re.compile(r"_(\{[^{}]*\}|[A-Za-z0-9])").match(texto, i)
                    if m2:
                        sub, i = m2.group().lstrip("_").strip("{}"), m2.end()
                poner("var", (letra, sub))
            continue
        if c in GRIEGAS:
            poner("var", (GRIEGAS[c], None))
        elif c in "'′″":
            k = 0
            while i < n and texto[i] in "'′″":
                k += 2 if texto[i] == "″" else 1
                i += 1
            poner("prima", k)
            continue
        elif c in _SIGNOS:
            poner("signo", _SIGNOS[c])
        elif c in _POR:
            poner("por", _POR[c])
        elif c == "/":
            poner("div", c)
        elif c == "^":
            poner("pot", c)
        elif c == "_":
            poner("bajo", c)
        elif c in _RELACIONES:
            poner("rel", _RELACIONES[c])
        elif c == ",":
            poner("coma", c)
        elif c in _ABRE:
            poner("abre", c)
        elif c in ")]}":
            poner("cierra", c)
        elif c == "|":
            poner("barra", c)
        elif c == "√":
            poner("raiz", c)
        elif c == "∫":
            m = _INT_DE.match(texto, i)   # «∫ de 0 a 1 de ...» (como en los enunciados de las definidas)
            if m:
                poner("int", (clase_a_latex(m.group(1)), clase_a_latex(m.group(2))))
                i = m.end()
                continue
            poner("int", None)
        elif c == "°":
            poner("grado", c)
        else:
            raise NoEsFormula(f"caracter: {c!r}")
        i += 1
    return sal


_EMPIEZA = {"num", "var", "func", "abre", "raiz", "int", "dif", "dop", "parcial"}


class _Lector:
    """Descenso recursivo: lista > relacion > suma > termino > factor > potencia."""

    def __init__(self, toks, estricto=False):
        self.t, self.i, self.barras, self.estricto = toks, 0, 0, estricto

    def ver(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def tomar(self, tipo=None):
        t = self.ver()
        if t is None or (tipo and t.tipo != tipo):
            raise NoEsFormula(f"se esperaba {tipo or 'algo'}")
        self.i += 1
        return t

    def empieza(self, t):
        return t is not None and (t.tipo in _EMPIEZA or (t.tipo == "barra" and self.barras == 0))

    def todo(self):
        if not self.t:
            raise NoEsFormula("vacio")
        nodo = self.lista()
        if self.ver() is not None:
            raise NoEsFormula("sobra algo")
        return nodo

    def lista(self):
        elems = [self.relacion()]
        while self.ver() is not None and self.ver().tipo == "coma":
            self.tomar()
            elems.append(self.relacion())
        return elems[0] if len(elems) == 1 else ("lista", elems)

    def relacion(self):
        t = self.ver()
        # «$= 2xy^2 + 1$» (lo de la izquierda es texto): solo donde el autor lo marca
        partes = [None if t is not None and t.tipo == "rel" and not self.estricto else self.suma()]
        ops = []
        while self.ver() is not None and self.ver().tipo == "rel":
            ops.append(self.tomar().valor)
            partes.append(self.suma())
        return partes[0] if not ops else ("rel", partes, ops)

    def suma(self):
        signo = self.tomar().valor if self.ver() is not None and self.ver().tipo == "signo" else None
        partes = [(signo, self.termino())]
        while self.ver() is not None and self.ver().tipo == "signo":
            op = self.tomar().valor
            partes.append((op, self.termino()))
        return partes[0][1] if len(partes) == 1 and signo is None else ("suma", partes)

    def termino(self):
        factores, uniones = [self.factor()], []
        while True:
            t = self.ver()
            if t is None:
                break
            if t.tipo == "por":
                self.tomar()
                uniones.append(t.valor)
                factores.append(self.factor())
            elif t.tipo == "div":
                self.tomar()
                num = factores[0] if len(factores) == 1 else ("mul", factores, uniones)
                factores, uniones = [("frac", num, self.factor())], []
            elif self.empieza(t):
                uniones.append("")
                factores.append(self.factor())
            else:
                break
        return factores[0] if len(factores) == 1 else ("mul", factores, uniones)

    def factor(self):
        t = self.ver()
        if t is not None and t.tipo == "signo":
            self.tomar()
            return ("signo", t.valor, self.factor())
        if t is not None and t.tipo == "int":
            return self.integral()
        return self.potencia()

    def integral(self):
        limites = self.tomar("int").valor
        abajo = arriba = None
        if limites:
            abajo, arriba = ("hoja", limites[0]), ("hoja", limites[1])
        elif self.ver() is not None and self.ver().tipo == "bajo":
            self.tomar()
            abajo = self.exponente()
            self.tomar("pot")
            arriba = self.exponente()
        cuerpo = self.termino() if self.empieza(self.ver()) or (self.ver() and self.ver().tipo == "signo") else None
        return ("int", abajo, arriba, cuerpo)

    def potencia(self):
        base = self.postfijo(self.atomo())
        if self.ver() is not None and self.ver().tipo == "pot":
            self.tomar()
            base = self.postfijo(("pot", base, self.exponente()))
        return base

    def postfijo(self, nodo):
        while self.ver() is not None and not self.ver().espacio and self.ver().tipo in ("prima", "grado"):
            t = self.tomar()
            nodo = ("prima", nodo, t.valor) if t.tipo == "prima" else ("grado", nodo)
        return nodo

    def exponente(self):
        t = self.ver()
        if t is not None and t.tipo == "signo":
            self.tomar()
            return ("signo", t.valor, self.exponente())
        if t is None or t.tipo not in ("num", "var", "abre", "func", "raiz"):
            raise NoEsFormula("falta el exponente")
        return self.postfijo(self.atomo())

    def atomo(self):
        t = self.ver()
        if t is None:
            raise NoEsFormula("falta un termino")
        if t.tipo == "num":
            self.tomar()
            return ("hoja", t.valor)
        if t.tipo == "var":
            self.tomar()
            letra, sub = t.valor
            return ("hoja", letra + (f"_{{{sub}}}" if sub else ""))
        if t.tipo == "dif":
            self.tomar()
            return ("dif", t.valor)
        if t.tipo == "dop":
            self.tomar()
            return ("hoja", rf"\frac{{d}}{{d{t.valor}}}")
        if t.tipo == "parcial":
            self.tomar()
            arriba, abajo = t.valor
            return ("hoja", rf"\frac{{\partial {arriba}}}{{\partial {abajo}}}" if arriba
                    else rf"\frac{{\partial}}{{\partial {abajo}}}")
        if t.tipo == "func":
            return self.funcion()
        if t.tipo == "abre":
            return self.grupo()
        if t.tipo == "barra" and self.barras == 0:
            return self.valor_absoluto()
        if t.tipo == "raiz":
            self.tomar()
            if self.ver() is not None and self.ver().tipo == "abre":
                return ("raiz", self.grupo())
            if self.ver() is None or self.ver().tipo not in ("num", "var", "func"):
                raise NoEsFormula("raiz sin radicando")
            return ("raiz", self.postfijo(self.atomo()))
        if t.tipo == "int":
            return self.integral()
        raise NoEsFormula(f"no se esperaba {t.tipo}")

    def grupo(self):
        abre = self.tomar("abre").valor
        barras, self.barras = self.barras, 0
        dentro = self.lista()
        self.barras = barras
        if self.tomar("cierra").valor != _ABRE[abre][2]:
            raise NoEsFormula("parentesis cruzados")
        return ("grupo", abre, dentro)

    def valor_absoluto(self):
        self.tomar("barra")
        self.barras += 1
        dentro = self.suma()
        self.barras -= 1
        self.tomar("barra")
        return ("abs", dentro)

    def funcion(self):
        nombre = self.tomar("func").valor
        exp = None
        if self.ver() is not None and self.ver().tipo == "pot" and not self.ver().espacio:
            self.tomar()
            exp = self.exponente()
        t = self.ver()
        if t is None:
            return ("func", nombre, exp, None)
        if t.tipo == "abre" and t.valor == "(":
            return ("func", nombre, exp, self.grupo())
        if t.tipo == "barra" and self.barras == 0:
            return ("func", nombre, exp, self.valor_absoluto())
        if t.tipo in ("num", "var", "raiz", "func"):
            # sin parentesis: «sen x», «cos 2x», «ln 2»: lo que va pegado
            factores = [self.potencia()]
            while self.ver() is not None and not self.ver().espacio and self.ver().tipo in ("num", "var", "raiz"):
                factores.append(self.potencia())
            arg = factores[0] if len(factores) == 1 else ("mul", factores, [""] * (len(factores) - 1))
            return ("func", nombre, exp, arg)
        return ("func", nombre, exp, None)


def _sin_parentesis(n):
    return _tex(n[2]) if n[0] == "grupo" and n[1] == "(" else _tex(n)


def _tex(n, arriba=False):
    tipo = n[0]
    if tipo == "hoja":
        return n[1]
    if tipo == "dif":
        return "d" + n[1]
    if tipo == "lista":
        return (r",\; " if arriba else ", ").join(_tex(e) for e in n[1])
    if tipo == "rel":
        sal = _tex(n[1][0]) if n[1][0] is not None else ""
        for op, p in zip(n[2], n[1][1:]):
            sal += f" {op} {_tex(p)}" if sal else f"{op} {_tex(p)}"
        return sal
    if tipo == "suma":
        sal = ""
        for k, (op, t) in enumerate(n[1]):
            if k == 0:
                sal = (op if op else "") + _tex(t)
            else:
                sal += f" {op} {_tex(t)}"
        return sal
    if tipo == "mul":
        sal = _tex(n[1][0])
        for union, f in zip(n[2], n[1][1:]):
            siguiente = _tex(f)
            if union:
                sal += f" {union} "
            elif f[0] == "dif":
                sal += r" \, "
            elif siguiente[:1].isdigit():   # «2 3» no es 23
                sal += r" \cdot "
            else:
                sal += " "
            sal += siguiente
        return sal
    if tipo == "frac":
        return rf"\frac{{{_sin_parentesis(n[1])}}}{{{_sin_parentesis(n[2])}}}"
    if tipo == "signo":
        return n[1] + _tex(n[2])
    if tipo == "pot":
        base = _tex(n[1])
        if n[1][0] in ("prima", "pot", "signo", "frac", "grado"):
            base = "{" + base + "}"
        return f"{base}^{{{_sin_parentesis(n[2])}}}"
    if tipo == "prima":
        return _tex(n[1]) + "'" * n[2]
    if tipo == "grado":
        return _tex(n[1]) + r"^{\circ}"
    if tipo == "grupo":   # \left( solo si hace falta: tras una letra, \left( mete un espacio
        dentro = _tex(n[2])
        izq, der, _ = _ABRE[n[1]]
        if not _ALTO.search(dentro):
            izq, der = izq.replace(r"\left", ""), der.replace(r"\right", "")
        return f"{izq}{dentro}{der}"
    if tipo == "abs":
        dentro = _tex(n[1])
        return rf"\left|{dentro}\right|" if _ALTO.search(dentro) else f"|{dentro}|"
    if tipo == "raiz":
        return rf"\sqrt{{{_sin_parentesis(n[1])}}}"
    if tipo == "func":
        _, nombre, exp, arg = n
        sal = FUNCIONES[nombre] + (f"^{{{_sin_parentesis(exp)}}}" if exp is not None else "")
        if arg is None:
            return sal
        if arg[0] in ("grupo", "abs"):
            return sal + _tex(arg)
        return sal + " " + _tex(arg)
    if tipo == "int":
        _, abajo, arriba_, cuerpo = n
        sal = r"\int"
        if abajo is not None:
            sal += f"_{{{_sin_parentesis(abajo)}}}^{{{_sin_parentesis(arriba_)}}}"
        return sal + (" " + _tex(cuerpo) if cuerpo is not None else "")
    raise NoEsFormula(f"nodo desconocido: {tipo}")


def clase_a_latex(texto, estricto=False):
    """LaTeX de una formula escrita con la notacion de clase, tal cual (sin
    reordenar ni simplificar). Lanza NoEsFormula si no se sabe leer.
    `estricto`: para texto sin marcar (una palabra no es un producto de letras)."""
    texto = str(texto).strip()
    if not texto or len(texto) > MAX_FORMULA:
        raise NoEsFormula("vacia o demasiado larga")
    try:
        return _tex(_Lector(_tokens(texto, estricto), estricto).todo(), arriba=True)
    except RecursionError:
        raise NoEsFormula("demasiado anidada") from None


# ---------- Trozos de texto y de formula para la ventana ----------

_LETRA = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
_TIRA = re.compile(rf"[{_LETRA}]+")
_SIMBOLOS = set("+-−±∓·*×/^=≠<>≤≥→⇒≈()[]{}|√∫∂'′″°_,") | set(GRIEGAS)
_PARTICULAS = set("yeoau")       # «y», «e», «o», «a», «u»: palabras sueltas en castellano
_PEGA_ANTES = set("=+-−·*×/(±∫≠<>≤≥→")   # tras esto, la letra suelta es una variable
_PEGA_DESPUES = set("=)]|^'′″≠<>≤≥→")     # y delante de esto
_REL = re.compile(r"[=≠<>≤≥→]")
_FACTOR_ANTES = re.compile(r"(?:[A-Za-z]|\^\d+)$")
_FUNC_FINAL = re.compile(r"(?<![A-Za-z])(?:" + "|".join(_FUNC_ORDEN) + r")$")
_SENAL = re.compile(r"[=^/√∫∂±·*'′″→≤≥≠<>|]|\d[A-Za-zα-ω(√]|[A-Za-z]\d|[A-Za-z]_|[A-Za-zα-ωΔ]\(|\)\(|"
                    + "|".join(rf"(?<![A-Za-z]){f}(?![a-z])" for f in _FUNC_ORDEN))
_BORDE_IZQ = set("=≠<>≤≥→⇒·*×/^+,")
_BORDE_DER = set("=≠<>≤≥→⇒·*×/^+-−±,.")
# En texto sin marcar: «sin» es la preposicion; las tiras de letras que si son
# formula son pocas: funciones, dx, xy, hx, Bx, rx, fg...
_NO_FUNCION = {"sin"}
_TIRA_FORMULA = re.compile(r"[A-Z]?[a-z]?[xy]{1,2}|fg|gf")
_PALABRAS = re.compile(r"\d+x\d+|\b[A-Z]{1,3}\d*(?:-[A-Z0-9]+)+\b|\b[A-Z]\d{2,}\b")   # 2x2, PP-EXP-MY, I04


def _tira_formula(tira):
    if not tira.isascii() or tira in _NO_FUNCION:
        return False
    return (len(tira) == 1 or tira in FUNCIONES or bool(_TIRA_FORMULA.fullmatch(tira))
            or (len(tira) == 2 and tira[0] == "d" and tira[1] in DIFERENCIALES))


def _clases(texto):
    """Por caracter: 'm' (puede ser formula), 's' (espacio), 'w' (palabra o signo de
    texto) o 'f' (dentro de «∫ de 0 a 1 de»: formula, sin cortar en la «a»)."""
    cl = ["w"] * len(texto)
    for i, c in enumerate(texto):
        if c in " \t":
            cl[i] = "s"
        elif c.isdigit() or c in _SIMBOLOS:
            cl[i] = "m"
        elif c == "." and 0 < i < len(texto) - 1 and texto[i - 1].isdigit() and texto[i + 1].isdigit():
            cl[i] = "m"
    for m in _TIRA.finditer(texto):
        if _tira_formula(m.group()):
            for i in range(m.start(), m.end()):
                cl[i] = "m"
    for m in _PALABRAS.finditer(texto):
        for i in range(m.start(), m.end()):
            cl[i] = "w"
    for m in _INT_DE.finditer(texto):
        for i in range(m.start(), m.end()):
            cl[i] = "f"
    return cl


def _particula_es_palabra(izq, der):
    """¿La letra suelta entre `izq` y `der` es una palabra (y, e, o, a, u) y no una variable?"""
    antes, despues = izq[-1:], der[:1]
    if despues in _PEGA_DESPUES and despues or antes in _PEGA_ANTES and antes:
        return False   # «y = 2», «∫ u du», «(e - 1)»
    if _REL.search(izq) and _REL.search(der):
        return True    # dos igualdades unidas: «du = dx y v = e^x»
    funcion = bool(_FUNC_FINAL.search(izq))
    if not der:
        return not funcion   # «3/x y un...» es palabra; «¿derivada de ln y?», no
    if despues.isdigit() or despues == "(":
        return True    # «x y 1/x», «-2y y (-8)»
    if funcion and (despues == "," or despues.isalpha()):
        return True    # «potencia de sen y, multiplicando», «da ln y arctan»
    return not _FACTOR_ANTES.search(izq)   # «4x^2 y + 3y», «x y, N»: un producto


def _partir_particulas(texto, cl, a, b):
    """Corta [a, b) en las letras sueltas que son palabras («2 y -1», «x = 1 e y = 2»).
    Solo la «y» puede ser una variable tras otra letra; «a», «o», «u», «e» sueltas
    junto a letras son palabras."""
    piezas, ini = [], a
    for i in range(a, b):
        if texto[i] not in _PARTICULAS or cl[i] == "f":
            continue
        if (i > a and not texto[i - 1].isspace()) or (i + 1 < b and not texto[i + 1].isspace()):
            continue
        izq, der = texto[ini:i].rstrip(), texto[i + 1:b].lstrip()
        palabra = _particula_es_palabra(izq, der)
        if not palabra and texto[i] != "y" and not (izq[-1:] in _PEGA_ANTES and izq[-1:]) \
                and not (der[:1] in _PEGA_DESPUES and der[:1]):
            palabra = True
        if palabra:
            piezas.append((ini, i))
            ini = i + 1
    piezas.append((ini, b))
    return [(x, y) for x, y in piezas if y > x]


def _equilibrar(texto, a, b):
    """Recorta espacios, puntuacion y operadores de los bordes; un parentesis sin
    pareja corta el trozo ahi (lo de fuera queda como texto). None si no queda nada."""
    for _ in range(60):
        a0, b0 = a, b
        while a < b and (texto[a].isspace() or texto[a] in _BORDE_IZQ):
            a += 1
        while b > a and (texto[b - 1].isspace() or texto[b - 1] in _BORDE_DER):
            b -= 1
        s = texto[a:b]
        pila, cierra = [], None
        for k, c in enumerate(s):
            if c in "([{":
                pila.append(k)
            elif c in ")]}":
                if pila:
                    pila.pop()
                else:
                    cierra = k
                    break
        if cierra is not None:   # «...), dv = e^x»: se queda lo de despues
            if cierra == len(s) - 1:
                b -= 1
            else:
                a += cierra + 1
        elif pila:               # «u = x (se simplifica»: se queda lo de antes
            if pila[0] == 0:
                a += 1
            else:
                b = a + pila[0]
        elif s.count("|") % 2:
            if s.endswith("|"):
                b -= 1
            elif s.startswith("|"):
                a += 1
            else:
                return None
        if (a, b) == (a0, b0):
            return (a, b) if b > a else None
    return None


def _detectar(texto):
    """Formulas de un texto sin marcar: [(inicio, fin, tex)]."""
    cl = _clases(texto)
    hallados, i, n = [], 0, len(texto)
    while i < n:
        if cl[i] not in "mf":
            i += 1
            continue
        j = i
        while j < n and cl[j] in "msf":
            j += 1
        for a, b in _partir_particulas(texto, cl, i, j):
            ab = _equilibrar(texto, a, b)
            if ab is None:
                continue
            fuente = texto[ab[0]:ab[1]]
            if not _SENAL.search(fuente) or fuente in FUNCIONES:   # «tan» suelto es una palabra
                continue
            try:
                hallados.append((ab[0], ab[1], clase_a_latex(fuente, estricto=True)))
            except NoEsFormula:
                continue
        i = j
    return hallados


def _juntar(salida):
    """Une los trozos de texto seguidos."""
    limpia = []
    for t in salida:
        if "texto" in t and not t.get("mono") and limpia and "texto" in limpia[-1] and not limpia[-1].get("mono"):
            limpia[-1] = {"texto": limpia[-1]["texto"] + t["texto"]}
        elif t.get("texto", "x") != "" or t.get("mono"):
            limpia.append(t)
    return limpia


def _marcado(texto):
    """Texto con las formulas entre $...$ (ejemplos): solo eso va a LaTeX. Lo que no
    se sabe leer se queda como texto monoespaciado («mono»)."""
    salida = []
    for k, parte in enumerate(texto.split("$")):
        if k % 2 == 0:
            salida.append({"texto": parte})
            continue
        try:
            salida.append({"tex": clase_a_latex(parte), "fuente": parte})
        except NoEsFormula:
            salida.append({"texto": parte, "mono": True})
    return _juntar(salida)


def sin_marcas(texto):
    """El texto sin los $ de las formulas (terminal y salida JSON)."""
    texto = str(texto)
    return texto.replace("$", "") if texto.count("$") % 2 == 0 else texto


def trozos(texto, variables=None):
    """Texto del motor partido en trozos para la ventana: [{"texto"} | {"tex", "fuente"}].
    Con marcas $...$ (ejemplos), solo lo marcado es formula. Sin marcas (pistas,
    diagnostico, solucion, enunciados), se buscan los trozos que se leen como
    formula (con «=», fracciones, potencias, funciones...); lo demas es texto, que
    la ventana pone con textContent (nunca innerHTML). Concatenar los textos y las
    `fuente` devuelve el texto original sin los $. `variables` se ignora (
    el conversor no depende de la ficha)."""
    texto = str(texto)
    if "$" in texto and texto.count("$") % 2 == 0:
        return _marcado(texto)
    salida, pos = [], 0
    for a, b, tex in _detectar(texto):
        salida.append({"texto": texto[pos:a]})
        salida.append({"tex": tex, "fuente": texto[a:b]})
        pos = b
    salida.append({"texto": texto[pos:]})
    return _juntar(salida)
