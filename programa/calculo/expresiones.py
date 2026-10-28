"""Leer respuestas escritas a mano en texto y mostrarlas de forma legible.

Acepta la notacion habitual de clase:
^ o ** para potencias, multiplicacion implicita (2x, x sen x), sen/tg/arctg,
ln o log (neperiano), |x| para valor absoluto, √ y la constante e.
"""
import re

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

X = sp.Symbol("x", real=True)
Y = sp.Symbol("y", real=True)  # solo en derivadas parciales y EDOs exactas
# Constantes de la solucion general de una EDO de orden 2 (tipo edo_solucion).
C1 = sp.Symbol("C1", real=True)
C2 = sp.Symbol("C2", real=True)

_TRANSFORMACIONES = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# Nombres en espanol o de los apuntes -> nombres de sympy. Orden: los largos primero.
_NOMBRES = [
    ("arcsen", "asin"), ("arcsin", "asin"), ("arccos", "acos"),
    ("arctan", "atan"), ("arctg", "atan"), ("sen", "sin"), ("tg", "tan"),
    ("ln", "log"),
]

_FUNCIONES = "sin|cos|tan|sec|csc|cot|log|asin|acos|atan|sinh|cosh|tanh"
# Orden: primero los nombres largos (asin antes que sin).
_FUNC_ARG = "asin|acos|atan|sinh|cosh|tanh|sqrt|sin|cos|tan|sec|csc|cot|log"
_NATIVAS = "sinh|cosh|tanh|sin|cos|tan|sec|csc|cot|log|sqrt|exp"

# Constante de integracion: «+ C» o «- C» en cualquier sitio, «C +» al principio,
# «= C» al final (forma de las EDOs exactas). Tambien c, k, K y cte.
_NOMBRE_C = r"(?:C|c|K|k|cte|Cte)"
_C_SUMANDO = re.compile(rf"\s*[+-]\s*{_NOMBRE_C}(?![A-Za-z0-9_(^])")
_C_INICIO = re.compile(rf"^\s*{_NOMBRE_C}\s*\+")
_C_IGUAL = re.compile(rf"=\s*(?:{_NOMBRE_C}|0)\s*$")
_F_INICIO = re.compile(r"^\s*F\s*(?:\(\s*x\s*,\s*y\s*\))?\s*=")


class ErrorLectura(ValueError):
    """La respuesta no se ha podido interpretar como expresion."""


def _normalizar(texto):
    t = texto.strip()
    for a, b in (("−", "-"), ("·", "*"), ("×", "*"), ("÷", "/"), ("²", "^2"), ("³", "^3"),
                 ("π", " pi ")):
        t = t.replace(a, b)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)  # coma decimal: 2,5 -> 2.5
    # Con espacio delante para que «x√x» no se lea como el nombre «xsqrt».
    t = re.sub(r"√\s*\(", " sqrt(", t)
    t = re.sub(r"√\s*([A-Za-z0-9_.]+)", r" sqrt(\1)", t)
    for a, b in _NOMBRES:
        # Delante puede haber un numero, x o y («2sen x», «xsenx»), pero no otra
        # letra (asi «arcsen» no se parte). Se separa con un espacio: «2 sin».
        t = re.sub(rf"(?<![A-Za-wz]){a}", " " + b, t)
    # Nombres de sympy pegados a un numero, x, y o «)»: «xcosx» -> «x cosx».
    t = re.sub(rf"(?<=[0-9xy)])({_NATIVAS})", r" \1", t)
    # e^ sin parentesis: el exponente es el monomio entero. «e^2x» -> e^(2x),
    # «e^-4x» -> e^(-4x), «e^xy» -> e^(xy), «e^x^2» -> e^(x^2).
    t = re.sub(r"(?<![A-Za-wz])e\s*\^\s*(-?[0-9.]*[xy]{1,2}(?:\^[0-9]+)?)", r" e^(\1)", t)
    t = re.sub(r"(?<=[0-9xy)])e\s*\^", " e^", t)  # «xe^(2x)» -> «x e^(2x)»
    # |u| -> Abs(u), sin anidamiento (suficiente para respuestas de primitivas).
    # Se separa con un espacio para que «ln|x|» no se lea como el nombre «logAbs».
    t = re.sub(r"\|([^|]+)\|", r" Abs(\1)", t)
    # sen^2(x) o sen^2 x -> (sin(x))^2
    t = re.sub(rf"\b({_FUNCIONES})\s*\^\s*(\d+)\s*\(([^()]*)\)", r"(\1(\3))^\2", t)
    t = re.sub(rf"\b({_FUNCIONES})\s*\^\s*(\d+)\s*([0-9.]*[xy]{{1,2}}|[0-9.]+)", r"(\1(\3))^\2", t)
    # Argumento sin parentesis: solo el monomio que sigue. «sen x cos x» ->
    # sin(x) cos(x); «sen 2x» -> sin(2x); «ln x · x» -> log(x)·x; «sen x^2» -> sin(x^2).
    t = re.sub(rf"\b({_FUNC_ARG})\s*([0-9.]*[xy]{{1,2}}(?:\^[0-9]+)?|[0-9.]+(?![0-9.]*[xy(]))",
               r"\1(\2)", t)
    return t


def leer(texto, quitar_constante=False, variables="x", evaluar=True):
    """Convierte texto en expresion de sympy.

    Devuelve (expresion, tenia_constante). Con quitar_constante=True elimina
    la constante de integracion (+C en cualquier sitio, «= C» final, «F =»
    inicial) y lo indica en el segundo valor. Con evaluar=False, sympy no
    simplifica al leer (para ensenar un enunciado tal como esta escrito).
    """
    tenia_constante = False
    t = texto
    if quitar_constante:
        t = _F_INICIO.sub("", t)
        for patron in (_C_IGUAL, _C_INICIO, _C_SUMANDO):
            if patron.search(t):
                t = patron.sub("", t)
                tenia_constante = True
    t = _normalizar(t)
    if not t:
        raise ErrorLectura("respuesta vacia")
    simbolos = {"x": X, "e": sp.E, "E": sp.E, "pi": sp.pi, "Abs": sp.Abs, "sqrt": sp.sqrt}
    permitidos = {X}
    if "y" in variables:
        simbolos["y"] = Y
        permitidos.add(Y)
    if "C" in variables:  # «C1», «C_1», «c1»
        t = re.sub(r"\b[Cc]_?([12])\b", r"C\1", t)
        simbolos.update({"C1": C1, "C2": C2})
        permitidos.update({C1, C2})
    if "i" in variables:  # unidad imaginaria en raices complejas: «2+3i»
        simbolos["i"] = sp.I
    try:
        expr = parse_expr(t, local_dict=simbolos, transformations=_TRANSFORMACIONES, evaluate=evaluar)
    except Exception as exc:  # sympy lanza tipos muy variados
        raise ErrorLectura(f"no entiendo «{texto}»; prueba con parentesis, p. ej. sen(x)·cos(x)") from exc
    if not isinstance(expr, sp.Expr):
        raise ErrorLectura(f"«{texto}» no es una expresion")
    otros = expr.free_symbols - permitidos
    if otros:
        nombres = ", ".join(sorted(str(s) for s in otros))
        letras = " ni y" if Y in permitidos else ""
        raise ErrorLectura(f"aparecen letras que no son x{letras}: {nombres}")
    return expr, tenia_constante


def _abs_a_barras(s):
    """Abs(...) -> |...| respetando parentesis anidados."""
    salida = []
    i = 0
    while i < len(s):
        if s.startswith("Abs(", i):
            nivel = 1
            j = i + 4
            while j < len(s) and nivel:
                nivel += {"(": 1, ")": -1}.get(s[j], 0)
                j += 1
            salida.append("|" + _abs_a_barras(s[i + 4:j - 1]) + "|")
            i = j
        else:
            salida.append(s[i])
            i += 1
    return "".join(salida)


_NUM = r"(\d+(?:/\d+)?)"


def limpiar(texto):
    """Quita los parentesis de parametros sustituidos: «x + (-5)» -> «x - 5»,
    «e^((-1)x)» -> «e^(-x)», «x--2» -> «x+2»."""
    t = texto
    # Ninguna regla quita un parentesis seguido de «^»: «(-1)^2» no es «-1^2».
    pot = r"(?!\s*\^)"
    t = re.sub(rf"\+\s*\(-{_NUM}\){pot}", r"- \1", t)
    t = re.sub(rf"-\s*\(-{_NUM}\){pot}", r"+ \1", t)
    # Signo binario (tras numero, letra o parentesis): «x + (3)» -> «x + 3».
    # Si es unario («e^(-(3)x)») lo resuelven las reglas de abajo: «e^(-3x)».
    t = re.sub(rf"(?<=[\w)'])\s*([+-])\s*\({_NUM}\){pot}", r" \1 \2", t)
    # Solo se quitan parentesis que no siguen a un numero, letra o ")":
    # «2(3)» es una multiplicacion y debe quedarse como esta.
    libre = r"(?<![\w)'′″])"  # tampoco tras una prima: «y'(0)» se queda
    t = re.sub(libre + r"\((-?)1\)(?=[a-z(√])", r"\1", t)
    t = re.sub(libre + r"\((-?\d+)\)(?=[a-z(√])", r"\1", t)
    t = re.sub(libre + r"\((\d+)\)" + pot, r"\1", t)
    # Terminos que valen 0: «+ 0r», «- 0x», «(x - 0)».
    t = re.sub(r"\s*[+-]\s*0(?![\d./])\s*[a-z]'*(?![a-z(])", "", t)
    t = re.sub(r"\s*[+-]\s*0(?![\d./])(?=\s*\))", "", t)
    t = re.sub(r"\^1(?!\d|\.\d|/\d)", "", t)  # x^1 -> x, tambien a final de frase (pero x^1/2 se queda)
    # Terminos «0·letras» de las EDOs: «+ 0*x*yp» vale 0 y desaparece.
    t = re.sub(r"\s*[+-]\s*0\s*\*\s*[a-z]+(?:\^\d+)?(?:\s*\*\s*[a-z]+(?:\^\d+)?)*(?![\w(^*])", "", t)
    t = re.sub(r"(?<![\w.^/])1(?=[a-z√])", "", t)  # 1x y^3 -> x y^3
    # Coeficiente 1 delante de un producto: «1·e^(x)» -> «e^(x)», «-1·e^(-x)» -> «-e^(-x)»,
    # «1*y» -> «y» (EDOs). No si el 1 es un factor tras «·» o «/» («2·-1·x» lo arregla la ultima regla).
    t = re.sub(r"(?<![\w.)^/·*])(?<![·/*]-)1\s*[·*]\s*(?=[a-zA-Z(√])", "", t)
    t = re.sub(r"·1·(?=[\w(√])", "·", t)  # 2·1·x -> 2·x
    t = re.sub(r"(?<=[\w)])/1(?![\w(^]|\.\d|\s*\^)", "", t)  # e^(x)/1 -> e^(x)
    t = t.replace("--", "+").replace("+-", "-").replace("+ -", "- ")
    t = re.sub(r"(?<==)\s*\+\s*", " ", t)  # «h = + 2/2» -> «h = 2/2»
    t = re.sub(r"\(\s*\+\s*", "(", t)
    # Un numero negativo tras «·» o «/» lleva parentesis: «2·-1·x» -> «2·(-1)·x».
    t = re.sub(r"([·/])\s*-(\d+(?:[./]\d+)?)", r"\1(-\2)", t)
    return t


def mostrar(expr):
    """Expresion de sympy -> texto legible con la notacion de clase."""
    if isinstance(expr, sp.Basic) and expr.has(sp.Float):
        # 0.500000000000000 -> 0.5 (los decimales que teclea el alumno)
        expr = expr.xreplace({f: sp.Float(float(f), 6) for f in expr.atoms(sp.Float)})
        s = mostrar_sin_floats(expr)
        s = re.sub(r"(\d+\.\d*?[1-9])0+\b", r"\1", s)
        return re.sub(r"(\d+)\.0+\b", r"\1", s)
    return mostrar_sin_floats(expr)


def mostrar_sin_floats(expr):
    s = sp.sstr(expr)
    s = s.replace("**", "^")
    s = re.sub(r"\bexp\(", "e^(", s)
    s = re.sub(r"\bE\b", "e", s)
    s = re.sub(r"\bI\b", "i", s)  # unidad imaginaria
    for a, b in (("asin", "arcsen"), ("acos", "arccos"), ("atan", "arctan"),
                 ("sin", "sen"), ("log", "ln"), ("sqrt", "√")):
        s = re.sub(rf"\b{a}\(", f"{b}(", s)
    s = _abs_a_barras(s)
    s = re.sub(r"ln\(\|([^|]*)\|\)", r"ln|\1|", s)
    s = s.replace("*", "·")
    return s
