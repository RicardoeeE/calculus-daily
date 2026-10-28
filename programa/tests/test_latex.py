"""LaTeX con la notacion de clase (calculo/latex.py): printer, conversor y trozos."""
import re
import tomllib
import unittest

from calculo.expresiones import leer
from calculo.fichas import CARPETA, cargar, cargar_ejemplos
from calculo.huecos import recortar
from calculo.latex import NoEsFormula, clase_a_latex, enunciado_latex, latex, latex_lectura, sin_marcas, trozos
from calculo.verificar import leer_edo, leer_par, leer_primitiva, leer_raices, leer_valores

FICHAS = cargar()


def tex(texto, variables="x"):
    return latex(leer(texto, variables=variables)[0])


class TestImpresora(unittest.TestCase):
    def test_ln_con_barras(self):
        self.assertEqual(tex("ln|x|"), r"\ln\left|x\right|")
        self.assertEqual(tex("ln|x - 3|"), r"\ln\left|-3 + x\right|")   # el orden que deja sympy al leer
        self.assertEqual(tex("ln|x^2 + 1|"), r"\ln{\left(1 + x^{2} \right)}")   # sympy ya quita |·| si es > 0
        self.assertEqual(tex("ln(x)"), r"\ln{\left(x \right)}")

    def test_exponencial(self):
        self.assertEqual(tex("e^(-x^2/2)"), r"e^{- \frac{x^{2}}{2}}")

    def test_arctan_y_arcsen(self):
        t = tex("arctan((x-3)/2)")
        self.assertTrue(t.startswith(r"\arctan{\left("))
        self.assertNotIn("atan", t.replace(r"\arctan", ""))
        self.assertEqual(tex("arcsen(x)"), r"\operatorname{arcsen}{\left(x \right)}")

    def test_sen_y_tg(self):
        self.assertEqual(tex("sen(x)"), r"\operatorname{sen}{\left(x \right)}")
        self.assertEqual(tex("tg(x)"), r"\operatorname{tg}{\left(x \right)}")
        self.assertNotIn(r"\sin", tex("x sen(2x)"))

    def test_sen_al_cuadrado(self):
        self.assertEqual(tex("sen^2(x)"), r"\operatorname{sen}^{2}{\left(x \right)}")

    def test_x_elevado_a_x(self):
        # order="none": el orden es el que deja sympy al leer, sin reordenar mas.
        self.assertEqual(tex("x^x (ln(x)+1)"), r"x^{x} \left(1 + \ln{\left(x \right)}\right)")

    def test_con_y(self):
        t = tex("x y^2 + sen(y)", "xy")
        self.assertIn("y^{2}", t)
        self.assertIn(r"\operatorname{sen}{\left(y \right)}", t)

    def test_constantes_c1_c2(self):
        self.assertEqual(tex("C1 e^(2x) + C2 x e^(2x)", "xC"), r"C_{1} e^{2 x} + C_{2} x e^{2 x}")

    def test_decimales_recortados(self):
        self.assertEqual(tex("0,5x"), "0.5 x")


class TestLectura(unittest.TestCase):
    def test_primitiva_con_c(self):
        self.assertEqual(latex_lectura(leer_primitiva("ln|x| + C")), r"\ln\left|x\right| + C")
        self.assertEqual(latex_lectura(leer_primitiva("ln|x|")), r"\ln\left|x\right|")

    def test_valores_con_nombre(self):
        self.assertEqual(latex_lectura(leer_valores("3, 4", ["h", "k"])), "h = 3, k = 4")

    def test_par_de_parciales(self):
        t = latex_lectura(leer_par("2x, 2y"))
        self.assertEqual(t, r"\frac{\partial M}{\partial y} = 2 x, \frac{\partial N}{\partial x} = 2 y")

    def test_edo_y_raices(self):
        self.assertEqual(latex_lectura(leer_edo("y = C1 e^x + C2 e^(-x)")), r"y = C_{1} e^{x} + C_{2} e^{- x}")
        self.assertEqual(latex_lectura(leer_raices("2±3i")), r"2 + 3 i, 2 - 3 i")


class TestEnunciados(unittest.TestCase):
    def test_derivada(self):
        self.assertEqual(enunciado_latex(FICHAS["D03"].variante(1)),
                         r"\frac{d}{dx}\left[ e^{- \frac{x^{2}}{2}} \right]")

    def test_no_regala_la_pista(self):
        """1/(x^2√x) se ensena tal cual, no como x^(-5/2)."""
        t = enunciado_latex(FICHAS["P-XRAIZ"].variante(1))
        self.assertEqual(t, r"\int \frac{1}{x^{2} \sqrt{x}} \, dx")

    def test_definida_con_parentesis(self):
        t = enunciado_latex(FICHAS["DF-POLI"].variante(1))
        self.assertTrue(t.startswith(r"\int_{0}^{"))
        self.assertIn(r"\left(x^{2} + 2\right) \, dx", t)

    def test_parcial(self):
        t = enunciado_latex(FICHAS["PC-CERO"].variante(1))
        self.assertTrue(t.startswith(r"\frac{\partial}{\partial y}\left[ "))

    def test_sin_formula_none(self):
        self.assertIsNone(enunciado_latex(FICHAS["AL-CUAD"].variante(1)))

    def test_todas_las_fichas(self):
        """Ninguna ficha rompe; los tipos con formula siempre la tienen."""
        con_formula = {"integral", "definida", "derivada", "parcial", "exacta", "potencial", "raices"}
        for f in FICHAS.values():
            with self.subTest(ficha=f.id):
                t = enunciado_latex(f.variante(1))
                if f.tipo in con_formula:
                    self.assertIsInstance(t, str)
                    self.assertNotIn("operatorname{atan}", t)
                    self.assertNotIn(r"\sin", t)
                else:
                    self.assertIsNone(t)


# ---------- Notacion de clase -> LaTeX, tal cual ----------

def reconstruir(partes):
    """Texto de los trozos: lo de texto tal cual y, de las formulas, su fuente."""
    return "".join(p["texto"] if "texto" in p else p["fuente"] for p in partes)


class TestConversor(unittest.TestCase):
    def test_paso_de_fracciones_simples(self):
        """«1/((x - 1)(x + 1)) = A/(x - 1) + B/(x + 1)»: fracciones de verdad, sin reordenar."""
        self.assertEqual(clase_a_latex("1/((x - 1)(x + 1)) = A/(x - 1) + B/(x + 1)"),
                         r"\frac{1}{(x - 1) (x + 1)} = \frac{A}{x - 1} + \frac{B}{x + 1}")

    def test_casos(self):
        casos = {
            "∂M/∂y = 4xy": r"\frac{\partial M}{\partial y} = 4 x y",
            "∫ e^u du/2": r"\int \frac{e^{u} \, du}{2}",
            "y = C1 e^x + C2 e^(3x)": r"y = C_{1} e^{x} + C_{2} e^{3 x}",
            "sen^2(x) = (1 - cos(2x))/2": r"\operatorname{sen}^{2}(x) = \frac{1 - \cos(2 x)}{2}",
            "|x|": "|x|",
            "ln|x - 3|": r"\ln|x - 3|",                 # sin reordenar (sympy daba -3 + x)
            "√(x+1)": r"\sqrt{x + 1}",
            "x e^x/(x + 1)^2": r"\frac{x e^{x}}{(x + 1)^{2}}",
            "e^(-x^2/2)": r"e^{-\frac{x^{2}}{2}}",
            "y'' - 2y' + y": "y'' - 2 y' + y",
            "y_p = A e^(3x)": r"y_{p} = A e^{3 x}",
            "d/dx [ x^4 ]": r"\frac{d}{dx} [x^{4}]",
            "∂/∂y [ x y^3 ]": r"\frac{\partial}{\partial y} [x y^{3}]",
            "∫u dv = u·v - ∫v du": r"\int u \, dv = u \cdot v - \int v \, du",
            "3(x-2)": "3 (x - 2)",                       # sympy daba 3x - 6
            "arctan((x-3)/2)": r"\arctan\left(\frac{x - 3}{2}\right)",
            "2±3i": r"2 \pm 3 i",
            "F(x, y) = x^2 y^2 + φ(y)": r"F (x, y) = x^{2} y^{2} + \varphi (y)",
            "x → ∞": r"x \to \infty",
            "∫ de 0 a 1 de e^u du": r"\int_{0}^{1} e^{u} \, du",
            "ln x + 1": r"\ln x + 1",
            "cos 2x": r"\cos 2 x",
            "= 2xy^2 + 1": r"= 2 x y^{2} + 1",          # marcado tras un texto («M (...) = ...»)
        }
        for fuente, tex in casos.items():
            with self.subTest(fuente=fuente):
                self.assertEqual(clase_a_latex(fuente), tex)

    def test_lo_que_no_se_lee_lanza(self):
        for malo in ("", "(x + 1", "x +", "e^", "x ∈ R", "a" * 400):
            with self.subTest(malo=malo):
                with self.assertRaises(NoEsFormula):
                    clase_a_latex(malo)

    def test_estricto_no_lee_palabras(self):
        self.assertEqual(clase_a_latex("x en y"), "x e n y")      # marcado: el autor manda
        with self.assertRaises(NoEsFormula):
            clase_a_latex("x en y", estricto=True)


class TestTrozos(unittest.TestCase):
    def test_marcado(self):
        t = trozos("Separa: $1/((x - 1)(x + 1)) = A/(x - 1) + B/(x + 1)$.")
        self.assertEqual(t[0], {"texto": "Separa: "})
        self.assertIn(r"\frac{1}{(x - 1) (x + 1)}", t[1]["tex"])
        self.assertEqual(t[2], {"texto": "."})

    def test_marcado_ilegible_queda_monoespaciado(self):
        t = trozos("Mira $(x + $ y sigue")
        self.assertEqual(t[1], {"texto": "(x + ", "mono": True})
        self.assertEqual("".join(p["texto"] for p in t), "Mira (x +  y sigue")

    def test_sin_marcas(self):
        self.assertEqual(sin_marcas("Llama $u = x^2$."), "Llama u = x^2.")
        self.assertEqual(sin_marcas("cuesta 5$"), "cuesta 5$")   # sin pareja: no es una marca

    def test_deteccion_sin_marcar(self):
        t = trozos("Con u = x y dv = e^x dx: du = dx y v = e^x.")
        self.assertEqual([p["fuente"] for p in t if "tex" in p], ["u = x", "dv = e^x dx", "du = dx", "v = e^x"])
        t = trozos("Busca dos numeros que multipliquen -2 y sumen 1: son 2 y -1.")
        self.assertFalse(any("tex" in p for p in t))           # «y» es una palabra
        t = trozos("M = 1 + x y, N = x^2.")
        self.assertEqual(t[0]["fuente"], "M = 1 + x y, N = x^2")   # aqui «x y» es un producto
        t = trozos("Partes: u = x (se simplifica al derivar), dv = e^(3x) dx.")
        self.assertEqual([p["fuente"] for p in t if "tex" in p], ["u = x", "dv = e^(3x) dx"])
        t = trozos("k es lo que multiplica a x; n es todo lo que suma sin x.")
        self.assertFalse(any("tex" in p for p in t))           # «sin» es la preposicion
        t = trozos("Como el I04 (ficha PP-EXP-MY), sistema 2x2.")
        self.assertFalse(any("tex" in p for p in t))

    def test_nunca_se_pierde_texto(self):
        for texto in ("4·x^(4-1).", "a\nb", "<img src=x onerror=alert(1)>", "Solucion: h = 1, k = 9",
                      "  1. Deriva: 2x\nSolucion: x^2/2 + C", "(f/g)' = (f'g - fg')/g^2.", ""):
            with self.subTest(texto=texto):
                self.assertEqual(reconstruir(trozos(texto)), texto)


class TestEjemplos(unittest.TestCase):
    """Los 25 ejemplos de fichas/ejemplos.toml, con las formulas entre $...$."""
    @classmethod
    def setUpClass(cls):
        with open(CARPETA / "ejemplos.toml", "rb") as f:
            cls.crudos = tomllib.load(f)["ejemplo"]
        cls.ejemplos = cargar_ejemplos(fichas=FICHAS)

    def test_son_25_y_todos_marcados(self):
        self.assertEqual(len(self.crudos), 25)
        for d in self.crudos:
            with self.subTest(tecnica=d["tecnica"]):
                self.assertTrue(any("$" in p for p in d["pasos"]), "ningun paso con formula marcada")

    def test_toda_formula_marcada_convierte(self):
        for d in self.crudos:
            for texto in [d["idea"]] + d["pasos"]:
                with self.subTest(tecnica=d["tecnica"], texto=texto):
                    self.assertEqual(texto.count("$") % 2, 0)
                    partes = trozos(texto)
                    self.assertFalse([p for p in partes if p.get("mono")], "formula sin convertir")
                    self.assertEqual(reconstruir(partes), sin_marcas(texto))
                    for p in partes:
                        if "tex" not in p:
                            continue
                        division = re.sub(r"d/d[a-z]|∂\w?/∂\w", "", p["fuente"])
                        if "/" in division:
                            self.assertIn(r"\frac", p["tex"], p["fuente"])
                        self.assertNotIn("/", p["tex"])

    def test_terminal_y_json_sin_marcas(self):
        for d in self.crudos:
            ej = self.ejemplos[d["tecnica"]]
            with self.subTest(tecnica=d["tecnica"]):
                self.assertEqual(ej["pasos"], [sin_marcas(p) for p in d["pasos"]])
                self.assertEqual(ej["idea"], sin_marcas(d["idea"]))
                self.assertNotIn("$", "".join(ej["pasos"]) + ej["idea"])
                self.assertEqual(ej["marcado"]["pasos"], d["pasos"])

    def test_huecos_con_marcas(self):
        """Recortar los pasos marcados da los mismos huecos que los planos."""
        for ej in self.ejemplos.values():
            for n in (1, 2):
                planos, ocultos = recortar(ej["pasos"], n)
                marcados, ocultos_m = recortar(ej["marcado"]["pasos"], n)
                self.assertEqual([sin_marcas(p) for p in marcados], planos)
                self.assertEqual([sin_marcas(p) for p in ocultos_m], ocultos)


class TestCorpus(unittest.TestCase):
    """Pistas 1-3, errores tipicos, soluciones y enunciados sin formula propia de
    TODAS las fichas: ninguna excepcion, ningun texto perdido y casi todo lo que
    lleva ^, / o = sale en KaTeX."""
    def test_todas_las_fichas(self):
        con, total = 0, 0
        for f in FICHAS.values():
            for semilla in (1, 2):
                v = f.variante(semilla)
                textos = [v.solucion_texto] + [v.pista(n) for n in range(1, len(f.pistas) + 1)]
                textos += [e.get("mensaje", "") for e in f.errores]
                if enunciado_latex(v) is None:
                    textos.append(v.enunciado)
                for texto in textos:
                    with self.subTest(ficha=f.id, texto=texto):
                        partes = trozos(texto)
                        self.assertEqual(reconstruir(partes), texto)
                        if re.search(r"[\^/=]", texto):
                            total += 1
                            con += any("tex" in p for p in partes)
        self.assertGreater(total, 500)
        self.assertGreaterEqual(con / total, 0.95, f"solo {con} de {total} con formula")

    def test_pista_4(self):
        """El paso a paso (pasos.py) tambien se parte bien."""
        for fid in ("R-DOS", "D03", "PA-XEXP", "EX-POLI", "T2-GEN-REAL"):
            texto = FICHAS[fid].variante(1).pista(4)
            with self.subTest(ficha=fid):
                partes = trozos(texto)
                self.assertEqual(reconstruir(partes), texto)
                self.assertTrue(any("tex" in p for p in partes))


if __name__ == "__main__":
    unittest.main()
