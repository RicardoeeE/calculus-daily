"""Bateria del verificador: primitivas tipicas, formas equivalentes y errores tipicos."""
import unittest

import sympy as sp

from calculo.expresiones import X, leer, mostrar
from calculo.verificar import comprobar_derivada, comprobar_integral

x = X
sen, cos, tan, sec, log, sqrt, exp, atan = sp.sin, sp.cos, sp.tan, sp.sec, sp.log, sp.sqrt, sp.exp, sp.atan

# 34 integrandos de primitivas tipicas (sustitucion, partes, racionales,
# trigonometricas, irracionales).
BATERIA = {
    1: 1 / sqrt(3 * x + 4),
    2: x**2 / sqrt(2 + x**3),
    3: cos(1 / x) / x**2,
    4: x / sqrt(x + 4),
    5: x * sqrt(x + 2),
    6: x**3 * exp(x**4),
    7: (2 * x + 7) ** sp.Rational(1, 3),
    8: x * (3 * x**2 + 1) ** 5,
    9: (log(x) + 3) / (x * (log(x) + 1)),
    10: sen(x) ** 3 * cos(x) ** 2,
    11: x * log(x),
    12: log(x + 1),
    13: sp.asin(x) / sqrt(1 - x**2),
    14: x * sen(x),
    15: x**2 * (2 * x**3 - 5) ** 4,
    16: 5 * x / (2 * x**2 + 3) ** sp.Rational(1, 3),
    17: x * 3 ** (x**2 + 1),
    18: 1 / (exp(x) + 2),
    19: 1 / (4 * 2**x + 2 ** (-x)),  # a = 2 como caso concreto
    20: (x + 5) / (x**2 + x - 2),
    21: x / ((x + 2) * (x - 1) ** 2),
    22: (3 * x**2 + 4 * x + 7) / (x**3 - 3 * x - 2),
    23: (2 * x**2 + x) / (x**3 - 1),
    24: sec(x) ** 2 * tan(x) ** 3,
    25: cos(x) * sen(x) ** 3,
    26: sen(3 * x) ** 2,
    27: 1 / sen(x),
    28: 1 / (1 - sen(x)),
    29: sen(x) / (cos(x) ** 2 - 4 * cos(x) + 13),
    30: 4 / (cos(x) - 2 * sen(x) * cos(x)),
    31: 1 / (x**2 * sqrt(x)),
    32: 1 / (x * sqrt(x + 4)),
    33: 1 / (sqrt(x) + x ** sp.Rational(1, 3)),
    34: 1 / ((1 + x) ** sp.Rational(1, 2) + (1 + x) ** sp.Rational(1, 4)),
}

# Respuestas escritas a mano con la notacion de clase (comprobadas a mano).
A_MANO = {
    1: "(2/3)√(3x+4) + C",
    2: "2/3 sqrt(2+x^3) + C",
    3: "-sen(1/x) + C",
    4: "(2/3)(x+4)^(3/2) - 8√(x+4) + C",
    5: "2/5 (x+2)^(5/2) - 4/3 (x+2)^(3/2) + C",
    6: "e^(x^4)/4 + C",
    7: "(3/8)(2x+7)^(4/3) + C",
    8: "(3x^2+1)^6/36 + C",
    9: "ln x + 2 ln|ln(x) + 1| + C",
    10: "cos(x)^5/5 - cos(x)^3/3 + C",
    11: "x^2 ln(x)/2 - x^2/4 + C",
    12: "(x+1) ln(x+1) - x + C",
    13: "arcsen(x)^2/2 + C",
    14: "sen(x) - x cos(x) + C",
    15: "(2x^3-5)^5/30 + C",
    16: "(15/8)(2x^2+3)^(2/3) + C",
    17: "3^(x^2+1)/(2 ln 3) + C",
    18: "x/2 - ln(e^x + 2)/2 + C",
    20: "2ln|x-1| - ln|x+2| + C",
    24: "tg(x)^4/4 + C",
    25: "sen^4(x)/4 + C",
    26: "x/2 - sen(6x)/12 + C",
    27: "ln|tan(x/2)| + C",
    28: "tan(x) + sec(x) + C",
    31: "-2/(3x^(3/2)) + C",
}

# Formas distintas pero equivalentes de la misma primitiva.
EQUIVALENTES = [
    (BATERIA[26], "x/2 - sen(3x)cos(3x)/6 + C"),
    (BATERIA[25], "-cos(2x)/8 + cos(4x)/32 + C"),  # sen^4/4 + constante
    (BATERIA[28], "2/(1 - tan(x/2)) + C"),          # forma con tan(x/2)
    (BATERIA[12], "(x+1)(ln(x+1) - 1) + C"),
    (BATERIA[18], "-ln(1 + 2e^(-x))/2 + C"),
    (1 / x, "ln|x| + 7"),                          # otra constante, sin +C
]

# Errores tipicos que el verificador debe rechazar.
ERRONEAS = [
    (BATERIA[1], "2√(3x+4) + C"),          # se olvida dividir entre 3
    (BATERIA[6], "e^(x^4) + C"),           # se olvida el 1/4
    (BATERIA[11], "x^2 ln(x)/2 + C"),      # partes a medias
    (BATERIA[26], "x/2 + sen(6x)/12 + C"),  # signo
    (BATERIA[3], "sen(1/x) + C"),          # signo del cambio
    (BATERIA[20], "ln|x-1| + ln|x+2| + C"),  # coeficientes de fracciones simples
    (BATERIA[14], "-x cos(x) + C"),
    (1 / (x**2 + 4 * x + 13), "arctan((x+2)/3) + C"),  # falta el 1/3 (ficha I04)
]


class TestLectura(unittest.TestCase):
    def test_notaciones(self):
        casos = {
            "2x": 2 * x, "x^2": x**2, "x**2": x**2, "sen x": sen(x), "sen(x)^2": sen(x) ** 2,
            "sen^2(x)": sen(x) ** 2, "2sen(x)": 2 * sen(x), "3tg x": 3 * tan(x), "e^(2x)": exp(2 * x), "ln|x|": log(sp.Abs(x)),
            "arctg(x)": atan(x), "√(x+1)": sqrt(x + 1), "x·e^x": x * exp(x), "3 − x": 3 - x,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(sp.simplify(leer(texto)[0] - esperado), 0)

    def test_constante(self):
        self.assertTrue(leer("x^2/2 + C", quitar_constante=True)[1])
        self.assertFalse(leer("x^2/2", quitar_constante=True)[1])

    def test_letras_extranas(self):
        r = comprobar_integral("y^2 + C", x)
        self.assertFalse(r.correcto)
        self.assertIn("no son x", r.error)


class TestBateria(unittest.TestCase):
    def test_respuestas_a_mano(self):
        for n, texto in A_MANO.items():
            with self.subTest(ejercicio=n):
                r = comprobar_integral(texto, BATERIA[n], semilla=n)
                self.assertTrue(r.correcto, f"{n}: {texto} {r}")

    def test_ida_y_vuelta(self):
        """La primitiva de sympy, mostrada con notacion de clase y releida, se acepta."""
        for n, f in BATERIA.items():
            with self.subTest(ejercicio=n):
                primitiva = sp.integrate(f, x)
                if primitiva.has(sp.Integral) or primitiva.has(sp.Piecewise):
                    self.skipTest(f"sympy no da una primitiva elemental de {n}")
                texto = mostrar(primitiva) + " + C"
                r = comprobar_integral(texto, f, semilla=n)
                self.assertTrue(r.correcto, f"{n}: {texto} {r}")

    def test_equivalentes(self):
        for f, texto in EQUIVALENTES:
            with self.subTest(respuesta=texto):
                self.assertTrue(comprobar_integral(texto, f).correcto)

    def test_erroneas(self):
        for f, texto in ERRONEAS:
            with self.subTest(respuesta=texto):
                self.assertFalse(comprobar_integral(texto, f).correcto)


class TestAvisos(unittest.TestCase):
    def test_falta_c(self):
        r = comprobar_integral("x^2/2", x)
        self.assertTrue(r.correcto)
        self.assertIn("falta +C", r.avisos)

    def test_falta_valor_absoluto(self):
        r = comprobar_integral("ln(x) + C", 1 / x)
        self.assertTrue(r.correcto)
        self.assertTrue(any("|·|" in a for a in r.avisos))

    def test_con_valor_absoluto_sin_aviso(self):
        self.assertEqual(comprobar_integral("ln|x| + C", 1 / x).avisos, [])


class TestDerivadas(unittest.TestCase):
    def test_basicas(self):
        casos = [
            (x**4, "4x^3"),
            (log(sp.Abs(x)), "1/x"),
            (exp(-x**2 / 2), "-x e^(-x^2/2)"),
            (atan((x - 3) / 2), "2/((x-3)^2+4)"),
            (log(x**2 - 6 * x + 13), "(2x-6)/(x^2-6x+13)"),
        ]
        for f, texto in casos:
            with self.subTest(respuesta=texto):
                self.assertTrue(comprobar_derivada(texto, f).correcto)

    def test_errores(self):
        self.assertFalse(comprobar_derivada("e^(-x^2/2)", exp(-x**2 / 2)).correcto)
        self.assertFalse(comprobar_derivada("1/((x-3)^2+4)", atan((x - 3) / 2)).correcto)


if __name__ == "__main__":
    unittest.main()
