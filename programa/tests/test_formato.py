"""Formato de lo que se ensena: nada de «2·-1·x», «e^(-x)/-1», «x^1/x» ni «+ -»."""
import unittest

from calculo.expresiones import limpiar
from calculo.fichas import cargar

FICHAS = cargar()
PROHIBIDO = ("·-", "/-", "+ -", "^1/", "= +")


def feos(texto):
    return [m for m in PROHIBIDO if m in texto]


class TestLimpiar(unittest.TestCase):
    def test_casos_conocidos(self):
        self.assertEqual(limpiar("du = 2·(-1)·x dx"), "du = 2·(-1)·x dx")
        self.assertEqual(limpiar("du = 2·-1·x dx"), "du = 2·(-1)·x dx")
        self.assertEqual(limpiar("v = e^(-x)/-1"), "v = e^(-x)/(-1)")
        self.assertEqual(limpiar("simplifica x^1/x"), "simplifica x/x")
        self.assertEqual(limpiar("h = -(-2)/2"), "h = 2/2")
        self.assertEqual(limpiar("x^1/2"), "x^1/2")      # exponente fraccionario: no se toca

    # Coeficientes 1 y -1, «/1», «^1» a final de frase y terminos «0·y'» de las EDOs.
    COEFICIENTES = [
        ("g' = 1·e^(x).", "g' = e^(x)."),
        ("g' = -1·e^(-x).", "g' = -e^(-x)."),
        ("Derivada de 1x^2: 2·1·x.", "Derivada de x^2: 2·x."),
        ("v = e^((1)x)/(1); queda", "v = e^(x); queda"),
        ("v = -cos((1)x)/(1): cuidado", "v = -cos(x): cuidado"),
        ("ypp + (-2)*yp + (1)*y", "ypp - 2*yp + y"),
        ("x^2*ypp + (0)*x*yp + (-6)*y", "x^2*ypp - 6*y"),
        ("donde estaba el 2^1.", "donde estaba el 2."),
        ("x^1.5", "x^1.5"),          # decimal: no se toca
        ("1/12 + x", "1/12 + x"),    # no es «/1»
        ("x + 1·2", "x + 1·2"),      # 1 por un numero: se queda
    ]

    def test_coeficientes_uno(self):
        for antes, despues in self.COEFICIENTES:
            self.assertEqual(limpiar(antes), despues, antes)

    def test_limpiar_no_cambia_el_valor(self):
        """Casos sueltos y TODAS las plantillas de las fichas: el texto limpio vale lo mismo."""
        import sympy as sp
        from calculo.expresiones import X, Y, leer
        from calculo.fichas import YP, YPP, _edo_sympy
        from calculo.verificar import comparar

        def valor(texto, edo=False):
            if edo:
                return sp.sympify(_edo_sympy(texto), locals={"ypp": YPP, "yp": YP, "y": Y, "x": X, "exp": sp.exp})
            return leer(texto, variables="xy")[0]

        casos = [(a, False) for a, _ in self.COEFICIENTES[:5] if "=" not in a and ":" not in a]
        casos += [("2·1·x + 1·e^(x) - 1·e^(-x) + e^(x)/1 + x^1", False), ("ypp + (-2)*yp + (1)*y", True),
                  ("x^2*ypp + (0)*x*yp + (-6)*y", True), ("(1/(3)^2) x", False)]
        for f in FICHAS.values():
            plantillas = {"integral": [f.enunciado], "derivada": [f.enunciado], "definida": [f.enunciado],
                          "parcial": [f.enunciado], "exacta": [f.m, f.n], "potencial": [f.m, f.n],
                          "edo_solucion": [f.rhs]}.get(f.tipo, [])
            for combinacion in f.combinaciones():
                p = f._con_derivados(combinacion)
                casos += [(t.format(**p), False) for t in plantillas if t]
                if f.tipo == "edo_solucion":
                    casos.append((f.edo.format(**p), True))
        for texto, edo in casos:
            with self.subTest(texto=texto):
                self.assertTrue(comparar(valor(limpiar(texto), edo), valor(texto, edo))[0], limpiar(texto))

    def test_variantes_de_ficha(self):
        v = FICHAS["S-LNX"].construir({"n": 1})
        self.assertEqual(v.enunciado, "∫ ln(x)/x dx")
        self.assertEqual(FICHAS["DPR-XEXP"].construir({"n": 1, "a": -1}).pista(3), "f = x, g = e^(-x), g' = -e^(-x).")
        self.assertEqual(FICHAS["DC-SEN"].construir({"a": 1}).pista(3), "Derivada de x^2: 2·x.")
        self.assertEqual(FICHAS["T2-GEN-DOBLE"].construir({"r": 1}).enunciado.split(".")[0], "y'' - 2y' + y = 0")


class TestRetoques(unittest.TestCase):
    def test_b25_ya_no_se_ofrece_y_al_log_hay_que_calcular(self):
        self.assertNotIn("B25", FICHAS)      # duplicaba S-COSSEN con n = 3
        self.assertIn("S-COSSEN", FICHAS)
        textos = {FICHAS["AL-LOG"].variante(s).solucion_texto for s in range(12)}
        self.assertGreater(len(textos), 3)   # k y n cambian; ya no se lee directo del enunciado
        v = FICHAS["AL-LOG"].construir({"a": 2, "b": 3, "c": -1})
        self.assertEqual(v.solucion_texto, "k = 2, n = 5")


class TestPistasSinFormatoFeo(unittest.TestCase):
    def test_pistas_1_a_3_y_enunciados_de_todas_las_combinaciones(self):
        problemas = []
        for f in FICHAS.values():
            for combinacion in f.combinaciones():
                v = f.construir(combinacion)
                textos = [v.enunciado] + [v.pista(n) for n in range(1, min(3, len(f.pistas)) + 1)]
                for t in textos:
                    if feos(t):
                        problemas.append((f.id, combinacion, feos(t), t))
        self.assertEqual(problemas, [])

    def test_pista_4_con_varias_semillas(self):
        problemas = []
        for f in FICHAS.values():
            for semilla in (0, 1):
                t = f.variante(semilla).pista(4)
                if feos(t):
                    problemas.append((f.id, semilla, feos(t), t))
        self.assertEqual(problemas, [])


class TestComoResponder(unittest.TestCase):
    def test_todo_tipo_no_obvio_tiene_ayuda(self):
        # integral y derivada se responden con una expresion en x: no necesitan ayuda.
        from practica import _AYUDA_TIPO
        tipos = {f.tipo for f in FICHAS.values()} - {"integral", "derivada"}
        self.assertEqual(tipos - set(_AYUDA_TIPO), set())


if __name__ == "__main__":
    unittest.main()
