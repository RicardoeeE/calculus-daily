"""Ver la ficha con math-plotter (proyecto hermano, opcional).

En la sesion, la tecla `v` lanza `math_plotter_pro.py --funcion "..."` en un
proceso aparte (no bloquea la sesion) con la funcion de la ficha:
- integral indefinida: dibuja el integrando;
- definida: el integrando con `--area a b` (si los limites son finitos);
- derivada y parcial: la funcion con `--derivada` (en una parcial, la otra
  letra vale 2, como en «la otra letra es un numero; pon x = 2»);
- raices: el polinomio caracteristico.
No cuenta como pista. Los repos no se unen: si math-plotter no esta, solo avisa.
"""
import os
import subprocess
import sys
from pathlib import Path

import sympy as sp

from .expresiones import X, Y
from .fichas import _numero
from .rutas import RAIZ

POR_DEFECTO = RAIZ.parent / "math-plotter"
SIN_PLOTTER = "Para ver graficas instala math-plotter junto a calculo-diario"
SIN_GRAFICA = "Esta ficha no tiene una grafica sencilla que ensenar."
OTRA_LETRA = 2   # valor de la letra que no se deriva en una parcial


def carpeta_plotter():
    """MATH_PLOTTER (variable de entorno) o `..\\math-plotter` junto a este repo."""
    return Path(os.environ.get("MATH_PLOTTER") or POR_DEFECTO)


def python_plotter(carpeta):
    for relativa in (("Scripts", "python.exe"), ("bin", "python")):
        ruta = carpeta / ".venv" / Path(*relativa)
        if ruta.exists():
            return ruta
    return None


def _texto(expr):
    """Expresion de sympy -> sintaxis que entiende el parser de math-plotter
    (sin, cos, exp, log, sqrt, Abs, ** ...)."""
    return sp.sstr(expr)


def _limite(texto, params):
    from .expresiones import limpiar
    t = limpiar(texto.format(**params)).strip()
    if t in ("oo", "-oo"):
        return sp.oo if t == "oo" else -sp.oo
    return _numero(t)


def argumentos(variante):
    """Lista de argumentos para math_plotter_pro.py, o None si la ficha no tiene
    una grafica sencilla."""
    f = variante.ficha
    funcion = variante.funcion
    if f.tipo not in ("integral", "definida", "derivada", "parcial", "raices") or funcion is None:
        return None
    derivada = f.tipo in ("derivada", "parcial")
    if f.tipo == "parcial":
        var, otra = (Y, X) if f.respecto == "y" else (X, Y)
        funcion = funcion.subs(otra, OTRA_LETRA)
        if var is Y:
            funcion = funcion.subs(Y, X)
    desde, hasta, area = -5.0, 5.0, None
    if f.tipo == "definida":
        a, b = (_limite(l, variante.params) for l in f.limites)
        if a.is_finite and b.is_finite:
            a, b = float(sp.N(a)), float(sp.N(b))
            margen = max(0.5, (b - a) * 0.25)
            desde, hasta, area = a - margen, b + margen, (a, b)
        elif a.is_finite:
            desde, hasta = float(sp.N(a)) - 1, float(sp.N(a)) + 10
        elif b.is_finite:
            desde, hasta = float(sp.N(b)) - 10, float(sp.N(b)) + 1
    args = ["--funcion", _texto(funcion), "--desde", f"{desde:g}", "--hasta", f"{hasta:g}"]
    if derivada:
        args.append("--derivada")
    if area:
        args += ["--area", f"{area[0]:g}", f"{area[1]:g}"]
    return args


def comando(variante, carpeta=None):
    """(comando, mensaje): el comando para lanzar math-plotter, o None y por que no."""
    carpeta = Path(carpeta) if carpeta else carpeta_plotter()
    script = carpeta / "math_plotter_pro.py"
    if not script.exists():
        return None, SIN_PLOTTER
    python = python_plotter(carpeta)
    if python is None:
        return None, "math-plotter no tiene entorno todavia: haz doble clic en su Graficar.bat una vez."
    args = argumentos(variante)
    if args is None:
        return None, SIN_GRAFICA
    return [str(python), str(script), *args], ""


def ver_ficha(variante, carpeta=None):
    """Lanza la grafica en un proceso aparte y devuelve el mensaje para el alumno."""
    cmd, mensaje = comando(variante, carpeta)
    if cmd is None:
        return mensaje
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        subprocess.Popen(cmd, cwd=str(Path(cmd[1]).parent), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
    except OSError as exc:
        return f"No se pudo abrir math-plotter ({exc})."
    return "Abriendo la grafica en otra ventana (sigue con tu resultado)."
