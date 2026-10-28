"""Fichas: familias de ejercicios con parametros, definidas en fichas/*.toml.

Cada vez que una ficha toca se genera una variante con una semilla. La clave
de cada variante se comprueba con sympy al generarla; la bateria de pruebas
comprueba todas las combinaciones de parametros.

Tipos:
- integral: primitiva (se comprueba derivando).
- derivada: se compara con la derivada exacta.
- definida: integral con limites (campo `limites`); la respuesta es un valor.
- algebra: preguntas de algebra previa que se responden con valores
  (campo `valores`); la ficha se valida con una `identidad`.
`derivados` permite calcular numeros a partir de los parametros
(p. ej. b = -2h para completar cuadrados).
"""
import itertools
import re
import random
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import sympy as sp

from .expresiones import C1, C2, X, Y, leer, limpiar, mostrar
from .rutas import FICHAS
from .latex import sin_marcas
from .verificar import comparar

CARPETA = FICHAS

# Orden de la escalera. Una tecnica se abre cuando las
# del escalon anterior estan dominadas.
_ESCALONES_INTEGRAL = {
    "tabla": 1, "lineal": 1, "logaritmo": 1,
    "sustitucion": 2,
    "partes": 3,
    "racionales": 4, "cuadrado": 4,
    "trigonometricas": 5,
    "irracionales": 6,
}
ESCALONES = {
    "integral": _ESCALONES_INTEGRAL,
    "definida": _ESCALONES_INTEGRAL,
    "derivada": {
        "potencia": 1, "cadena": 1, "producto": 1,
        "cociente": 2,
        "inversas": 3,
        "logaritmica": 4,
    },
    "algebra": {"algebra": 1},
}
# Derivadas parciales y EDOs exactas: un solo grupo con su escalera.
# Las EDOs de orden superior van al final de la misma escalera, pero lo
# abre antes el calendario de examenes (fichas/calendario.toml).
_ESCALONES_PARCIAL = {
    "constante": 1, "parcial_cadena": 2, "exactitud": 3, "potencial": 4,
    "comprobar_solucion": 5, "caracteristica": 5, "wronskiano": 6, "forma_yp": 6, "pvi": 6,
}
for _t in ("parcial", "exacta", "potencial", "raices", "edo_solucion", "calculo"):
    ESCALONES[_t] = _ESCALONES_PARCIAL

# Grupo de cupo: las definidas cuentan como integrales.
GRUPO = {"integral": "integral", "definida": "integral", "derivada": "derivada", "algebra": "algebra",
         "parcial": "parcial", "exacta": "parcial", "potencial": "parcial",
         "raices": "parcial", "edo_solucion": "parcial", "calculo": "parcial"}


def grupo(tipo):
    return GRUPO.get(tipo, tipo)


# En las EDOs del tipo edo_solucion se escribe ypp = y'', yp = y'. Se leen
# como simbolos auxiliares; Y hace de y.
YPP = sp.Symbol("ypp", real=True)
YP = sp.Symbol("yp", real=True)


def _edo_sympy(texto):
    """«y'' - 4y' + 13y» o «ypp - 4yp + 13y» -> texto con ypp, yp, y."""
    t = texto.replace("y''", " ypp ").replace("y'", " yp ")
    return t


def _edo_texto(texto):
    t = texto.replace("*", "")
    t = re.sub(r"[+-]\s*0\s*yp{0,2}\b", "", t)  # «+ 0yp» desaparece
    t = re.sub(r"(?<![\w.])1\s*(?=yp{0,2}\b)", "", t)  # «1y» -> «y» (y tambien «1yp», «1ypp»)
    t = re.sub(r"\s+", " ", t).strip()
    return t.replace("ypp", "y''").replace("yp", "y'")


class ErrorFicha(ValueError):
    """Ficha mal definida o con una clave que no cuadra."""


def _numero(texto):
    expr, _ = leer(texto)
    if expr.free_symbols:
        raise ErrorFicha(f"«{texto}» deberia ser un numero")
    return sp.nsimplify(expr)


def iguales_numericos(a, b):
    try:
        return abs(complex(sp.N(a - b, 30))) <= 1e-9 * max(1.0, abs(complex(sp.N(b, 30))))
    except (TypeError, ValueError):
        return False


@dataclass
class Variante:
    ficha: "Ficha"
    semilla: int
    params: dict          # parametros y derivados
    funcion: sp.Expr | None   # integrando o funcion a derivar (None en algebra)
    solucion: object      # primitiva, derivada, valor, o dict de valores (algebra)

    @property
    def expresion(self):
        """La funcion tal como la escribio el autor de la ficha (sin simplificar,
        que sympy a veces regala la pista: 1/(x√x) -> x^(-3/2))."""
        if self.ficha.mostrar == "desarrollado" and self.funcion is not None:
            return mostrar(sp.expand(self.funcion))
        return limpiar(self.ficha.enunciado.format(**self.params))

    @property
    def enunciado(self):
        tipo = self.ficha.tipo
        if tipo == "integral":
            return f"∫ {self.expresion} dx"
        if tipo == "definida":
            a, b = (limpiar(l.format(**self.params)).replace("oo", "∞") for l in self.ficha.limites)
            return f"∫ de {a} a {b} de  {self.expresion}  dx"
        if tipo == "algebra":
            return self.expresion
        if tipo == "parcial":
            return f"∂/∂{self.ficha.respecto} [ {self.expresion} ]"
        if tipo == "raices":
            pol = limpiar(self.ficha.enunciado.format(**self.params)).replace("x", "r")
            return f"Ecuacion caracteristica: {pol} = 0.  Escribe sus raices separadas por comas"
        if tipo == "edo_solucion":
            edo = _edo_texto(limpiar(self.ficha.edo.format(**self.params)))
            rhs = limpiar(self.ficha.rhs.format(**self.params))
            if self.ficha.constantes:
                return f"{edo} = {rhs}.  Escribe la solucion general y(x) (con C1 y C2)"
            return f"{edo} = {rhs}.  Escribe UNA solucion particular y_p(x)"
        if tipo == "calculo":
            return self.expresion
        if tipo in ("exacta", "potencial"):
            m = limpiar(self.ficha.m.format(**self.params))
            n = limpiar(self.ficha.n.format(**self.params))
            pregunta = ("Escribe ∂M/∂y, ∂N/∂x" if tipo == "exacta"
                        else "Es exacta: escribe la funcion potencial F(x, y)")
            return f"({m}) dx + ({n}) dy = 0.  {pregunta}"
        return f"d/dx [ {self.expresion} ]"

    def _texto_autor(self):
        if self.ficha.solucion is None:
            return None
        if not self.ficha.params:
            return self.ficha.solucion
        # Con parametros la plantilla puede quedar peor que sympy («(x + 1 - 1)e^x»):
        # se usa solo si no es mas larga que la forma de sympy.
        texto = limpiar(self.ficha.solucion.format(**self.params))
        return texto if len(texto) <= len(mostrar(self.solucion)) else None

    @property
    def solucion_texto(self):
        tipo = self.ficha.tipo
        if tipo == "algebra":
            return ", ".join(f"{n} = {mostrar(v)}" for n, v in self.solucion.items())
        if tipo == "exacta":
            my, nx = self.solucion
            veredicto = "son iguales: es exacta" if sp.simplify(my - nx) == 0 else "son distintas: no es exacta"
            return f"{mostrar(my)}, {mostrar(nx)}  ({veredicto})"
        if tipo == "potencial":
            return mostrar(self.solucion) + " + C"
        if tipo == "raices":
            return ", ".join(mostrar(r) for r in self.solucion)
        # El texto del autor (la forma de clase), con los numeros sustituidos si hay
        # parametros. Sin texto, la forma de sympy.
        if tipo in ("edo_solucion", "calculo"):
            return self._texto_autor() or mostrar(self.solucion)
        texto = self._texto_autor() or mostrar(self.solucion)
        return texto + " + C" if tipo == "integral" else texto

    @property
    def respuesta_modelo(self):
        """La solucion tal como habria que teclearla (sin el comentario de las exactas)."""
        return self.solucion_texto.split("  (")[0]

    def pista(self, nivel):
        """Nivel 1-3: textos de la ficha. Nivel 4: pasos (calculo/pasos.py) y solucion."""
        if nivel >= 4 or nivel > len(self.ficha.pistas):
            from .pasos import pasos
            paso_a_paso = pasos(self)[:-1]  # el ultimo es el resultado
            lineas = [f"  {i}. {t}" for i, t in enumerate(paso_a_paso, 1)]
            return "\n".join(lineas + [f"Solucion: {self.solucion_texto}"])
        return limpiar(self.ficha.pistas[nivel - 1].format(**self.params))


@dataclass
class Ficha:
    id: str
    tipo: str
    tecnica: str
    enunciado: str
    solucion: str | None
    fuente: str
    pistas: list
    params: dict = field(default_factory=dict)
    larga: bool = False
    mostrar: str = ""  # "desarrollado": ensenar la funcion expandida
    limites: list = field(default_factory=list)      # definida: [a, b]
    valores: dict = field(default_factory=dict)      # algebra: nombre -> expresion
    identidad: list = field(default_factory=list)    # algebra: [izquierda, derecha]
    derivados: dict = field(default_factory=dict)    # nombre -> expresion de params
    respecto: str = "x"                              # parcial: x o y
    m: str = ""                                      # exacta/potencial: M(x, y)
    n: str = ""                                      # exacta/potencial: N(x, y)
    requiere: list = field(default_factory=list)     # tecnicas con algun acierto antes
    edo: str = ""                                    # edo_solucion: «ypp + (a)yp + (b)y»
    rhs: str = "0"                                   # edo_solucion: lado derecho
    constantes: int = 0                              # edo_solucion: 2 = general, 0 = particular
    funciones: dict = field(default_factory=dict)    # calculo: nombre -> expresion en x
    calculo: str = ""                                # calculo: formula con diff(f, x)
    errores: list = field(default_factory=list)      # errores tipicos: [{respuesta|forma, mensaje}]
    previa: str = ""                                 # id de la ficha de algebra que prepara esta

    @property
    def grupo(self):
        return grupo(self.tipo)

    @property
    def escalon(self):
        return ESCALONES[self.tipo][self.tecnica]

    def combinaciones(self):
        nombres = sorted(self.params)
        for valores in itertools.product(*(self.params[n] for n in nombres)):
            yield dict(zip(nombres, valores))

    def _con_derivados(self, params):
        todos = dict(params)
        for nombre, texto in self.derivados.items():
            todos[nombre] = mostrar(_numero(texto.format(**todos)))
        return todos

    def construir(self, params, semilla=0):
        """Variante con esos parametros, con su clave comprobada."""
        params = self._con_derivados(params)
        if self.tipo == "algebra":
            return self._construir_algebra(params, semilla)
        if self.tipo in ("exacta", "potencial"):
            return self._construir_exacta(params, semilla)
        if self.tipo == "raices":
            return self._construir_raices(params, semilla)
        if self.tipo == "edo_solucion":
            return self._construir_edo(params, semilla)
        if self.tipo == "calculo":
            return self._construir_calculo(params, semilla)
        if self.tipo == "parcial":
            funcion, _ = leer(self.enunciado.format(**params), variables="xy")
            var = Y if self.respecto == "y" else X
            exacta = sp.diff(funcion, var)
            if self.solucion is not None:
                dada, _ = leer(self.solucion.format(**params), variables="xy")
                if not comparar(dada, exacta, semilla)[0]:
                    raise ErrorFicha(f"{self.id} {params}: la clave no cuadra")
            return Variante(self, semilla, params, funcion, exacta)
        funcion, _ = leer(self.enunciado.format(**params))
        if self.tipo == "definida":
            return self._construir_definida(params, funcion, semilla)
        exacta = sp.diff(funcion, X) if self.tipo == "derivada" else None
        if self.solucion is None:
            if exacta is None:
                raise ErrorFicha(f"{self.id}: una integral necesita solucion")
            solucion = exacta
        else:
            solucion, _ = leer(self.solucion.format(**params), quitar_constante=True)
        if self.tipo == "integral":
            ok, _ = comparar(sp.diff(solucion, X), funcion, semilla)
        else:
            ok, _ = comparar(solucion, exacta, semilla)
        if not ok:
            raise ErrorFicha(f"{self.id} {params}: la clave no cuadra")
        return Variante(self, semilla, params, funcion, solucion)

    def _construir_definida(self, params, funcion, semilla):
        a, b = (_numero(l.format(**params)) if l.strip() not in ("oo", "-oo")
                else (sp.oo if l.strip() == "oo" else -sp.oo) for l in self.limites)
        valor = _numero(self.solucion.format(**params))
        exacto = sp.integrate(funcion, (X, a, b))
        if exacto.has(sp.Integral):
            exacto = sp.Integral(funcion, (X, a, b)).evalf(30)
        if not iguales_numericos(valor, exacto):
            raise ErrorFicha(f"{self.id} {params}: la clave {valor} no cuadra con {exacto}")
        return Variante(self, semilla, params, funcion, valor)

    def _construir_raices(self, params, semilla):
        pol, _ = leer(self.enunciado.format(**params))
        raices = []
        for r, mult in sp.roots(sp.Poly(pol, X)).items():
            raices += [sp.nsimplify(r)] * mult
        if len(raices) != sp.degree(pol, X):
            raise ErrorFicha(f"{self.id} {params}: no salen todas las raices")
        return Variante(self, semilla, params, pol, raices)

    def operador(self, params):
        """La EDO como funcion: y -> L[y] (ypp, yp, y)."""
        edo = sp.sympify(_edo_sympy(self.edo.format(**params)),
                         locals={"ypp": YPP, "yp": YP, "y": Y, "x": X, "exp": sp.exp})
        return lambda f: edo.subs({YPP: sp.diff(f, X, 2), YP: sp.diff(f, X)}).subs(Y, f)

    def _construir_edo(self, params, semilla):
        rhs, _ = leer(self.rhs.format(**params))
        solucion, _ = leer(self.solucion.format(**params), variables="xC")
        resto = sp.expand(self.operador(params)(solucion) - rhs)
        if not comparar(resto, sp.Integer(0), semilla)[0]:
            raise ErrorFicha(f"{self.id} {params}: la solucion dada no cumple la EDO")
        return Variante(self, semilla, params, rhs, solucion)

    def _construir_calculo(self, params, semilla):
        locales = {"x": X, "diff": sp.diff, "exp": sp.exp, "sin": sp.sin, "cos": sp.cos}
        for nombre, texto in self.funciones.items():
            locales[nombre], _ = leer(texto.format(**params))
        valor = sp.simplify(sp.sympify(self.calculo.format(**params), locals=locales))
        if self.solucion is not None:
            dada, _ = leer(self.solucion.format(**params))
            if not comparar(dada, valor, semilla)[0]:
                raise ErrorFicha(f"{self.id} {params}: la clave no cuadra con el calculo")
        return Variante(self, semilla, params, None, valor)

    def _construir_exacta(self, params, semilla):
        m, _ = leer(self.m.format(**params), variables="xy")
        n, _ = leer(self.n.format(**params), variables="xy")
        my, nx = sp.diff(m, Y), sp.diff(n, X)
        if self.tipo == "exacta":
            return Variante(self, semilla, params, (m, n), (my, nx))
        if not comparar(my, nx, semilla)[0]:
            raise ErrorFicha(f"{self.id} {params}: no es exacta, no tiene potencial")
        f = sp.integrate(m, X)
        f = f + sp.integrate(sp.simplify(n - sp.diff(f, Y)), Y)
        if self.solucion is not None:
            f, _ = leer(self.solucion.format(**params), quitar_constante=True, variables="xy")
        if not (comparar(sp.diff(f, X), m, semilla)[0] and comparar(sp.diff(f, Y), n, semilla)[0]):
            raise ErrorFicha(f"{self.id} {params}: la funcion potencial no cuadra")
        return Variante(self, semilla, params, (m, n), f)

    def _construir_algebra(self, params, semilla):
        valores = {n: _numero(t.format(**params)) for n, t in self.valores.items()}
        if self.identidad:
            todos = {**params, **{n: mostrar(v) for n, v in valores.items()}}
            izq, _ = leer(self.identidad[0].format(**todos))
            der, _ = leer(self.identidad[1].format(**todos))
            ok, _ = comparar(izq, der, semilla)
            if not ok:
                raise ErrorFicha(f"{self.id} {params}: la identidad no se cumple con {valores}")
        return Variante(self, semilla, params, None, valores)

    def variante(self, semilla):
        rng = random.Random(f"{self.id}:{semilla}")
        params = {n: rng.choice(self.params[n]) for n in sorted(self.params)}
        return self.construir(params, semilla)


def cargar(carpeta=CARPETA):
    """Todas las fichas, indexadas por id."""
    fichas = {}
    # Orden de carga = orden en que salen las fichas nuevas dentro de un escalon:
    # primero el temario basico, despues las ampliaciones.
    prioridad = ["algebra", "derivadas", "integrales", "parciales", "edos", "definidas", "largas"]
    rutas = sorted(Path(carpeta).glob("*.toml"),
                   key=lambda r: (prioridad.index(r.stem) if r.stem in prioridad else len(prioridad), r.stem))
    for ruta in rutas:
        with open(ruta, "rb") as f:
            datos = tomllib.load(f)
        for d in datos.get("ficha", []):
            ficha = Ficha(
                id=d["id"], tipo=d["tipo"], tecnica=d["tecnica"],
                enunciado=d.get("enunciado", ""), solucion=d.get("solucion"),
                fuente=d.get("fuente", ""), pistas=d.get("pistas", []),
                params=d.get("params", {}), larga=d.get("larga", False),
                mostrar=d.get("mostrar", ""), limites=d.get("limites", []),
                valores=d.get("valores", {}), identidad=d.get("identidad", []),
                derivados=d.get("derivados", {}), respecto=d.get("respecto", "x"),
                m=d.get("m", ""), n=d.get("n", ""), requiere=d.get("requiere", []),
                edo=d.get("edo", ""), rhs=d.get("rhs", "0"), constantes=d.get("constantes", 0),
                funciones=d.get("funciones", {}), calculo=d.get("calculo", ""),
                errores=d.get("errores", []), previa=d.get("previa", ""),
            )
            if ficha.tipo not in ESCALONES or ficha.tecnica not in ESCALONES[ficha.tipo]:
                raise ErrorFicha(f"{ficha.id}: tipo o tecnica desconocidos ({ruta.name})")
            if ficha.tipo == "definida" and (len(ficha.limites) != 2 or ficha.solucion is None):
                raise ErrorFicha(f"{ficha.id}: una definida necesita 2 limites y solucion")
            if ficha.tipo in ("exacta", "potencial") and not (ficha.m and ficha.n):
                raise ErrorFicha(f"{ficha.id}: una ficha {ficha.tipo} necesita m y n")
            if ficha.tipo == "algebra" and not ficha.valores:
                raise ErrorFicha(f"{ficha.id}: una ficha de algebra necesita valores")
            if ficha.id in fichas:
                raise ErrorFicha(f"id repetido: {ficha.id}")
            fichas[ficha.id] = ficha
    for ficha in fichas.values():
        if ficha.previa and (ficha.previa not in fichas or fichas[ficha.previa].tipo != "algebra"):
            raise ErrorFicha(f"{ficha.id}: previa «{ficha.previa}» no es una ficha de algebra")
    return fichas


def cargar_grafo(carpeta=CARPETA, fichas=None):
    """Grafo de tecnicas de fichas/grafo.toml: tecnica -> tupla de las que contiene
    (un nivel). Valida que toda tecnica exista y que no haya ciclos. Sin fichero: {}."""
    ruta = Path(carpeta) / "grafo.toml"
    if not ruta.exists():
        return {}
    fichas = fichas if fichas is not None else cargar(carpeta)
    tecnicas = {f.tecnica for f in fichas.values()}
    with open(ruta, "rb") as f:
        datos = tomllib.load(f).get("contiene", {})
    grafo = {}
    for tecnica, contenidas in datos.items():
        if tecnica not in tecnicas:
            raise ErrorFicha(f"grafo: la tecnica «{tecnica}» no existe")
        if not isinstance(contenidas, list) or not all(isinstance(c, str) for c in contenidas):
            raise ErrorFicha(f"grafo: «{tecnica}» debe ser una lista de tecnicas")
        for c in contenidas:
            if c not in tecnicas:
                raise ErrorFicha(f"grafo: «{tecnica}» contiene «{c}», que no existe")
            if c == tecnica:
                raise ErrorFicha(f"grafo: «{tecnica}» se contiene a si misma")
        if len(set(contenidas)) != len(contenidas):
            raise ErrorFicha(f"grafo: «{tecnica}» repite alguna tecnica")
        grafo[tecnica] = tuple(contenidas)
    estado = {}  # 1 = en curso, 2 = hecho

    def visitar(t, camino):
        if estado.get(t) == 2:
            return
        if estado.get(t) == 1:
            raise ErrorFicha("grafo: ciclo " + " -> ".join(camino[camino.index(t):] + [t]))
        estado[t] = 1
        for c in grafo.get(t, ()):
            visitar(c, camino + [c])
        estado[t] = 2

    for t in grafo:
        visitar(t, [t])
    return grafo


def cargar_ejemplos(carpeta=CARPETA, fichas=None):
    """Ejemplos resueltos de fichas/ejemplos.toml: tecnica -> dict con la variante
    construida (enunciado y resultado salen de la ficha, con la clave ya
    comprobada), la idea y los pasos."""
    fichas = fichas if fichas is not None else cargar(carpeta)
    ruta = Path(carpeta) / "ejemplos.toml"
    if not ruta.exists():
        return {}
    with open(ruta, "rb") as f:
        datos = tomllib.load(f)
    ejemplos = {}
    for d in datos.get("ejemplo", []):
        tecnica, ficha_id = d.get("tecnica", ""), d.get("ficha", "")
        if ficha_id not in fichas:
            raise ErrorFicha(f"ejemplo de «{tecnica}»: la ficha {ficha_id} no existe")
        ficha = fichas[ficha_id]
        if ficha.tecnica != tecnica:
            raise ErrorFicha(f"ejemplo de «{tecnica}»: la ficha {ficha_id} es de la tecnica «{ficha.tecnica}»")
        pasos = d.get("pasos", [])
        if not pasos:
            raise ErrorFicha(f"ejemplo de «{tecnica}»: faltan los pasos")
        if tecnica in ejemplos:
            raise ErrorFicha(f"ejemplo repetido para la tecnica «{tecnica}»")
        v = ficha.construir(d.get("params", {}))
        # Las formulas van entre $...$; la terminal y la salida JSON usan
        # el texto sin marcas y la ventana, `marcado` (calculo/latex.py, trozos).
        idea = d.get("idea", "")
        ejemplos[tecnica] = {"tecnica": tecnica, "ficha": ficha_id, "variante": v,
                             "idea": sin_marcas(idea), "enunciado": v.enunciado,
                             "pasos": [sin_marcas(p) for p in pasos], "resultado": v.solucion_texto,
                             "marcado": {"idea": idea, "pasos": list(pasos)}}
    return ejemplos
