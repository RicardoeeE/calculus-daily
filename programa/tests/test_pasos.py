"""Pasos automaticos en la pista 4."""
import unittest
from types import SimpleNamespace
from unittest import mock

import sympy as sp

from calculo.expresiones import X, Y
from calculo.fichas import Variante, cargar
from calculo import pasos as modulo_pasos
from calculo.pasos import pasos


def _variante(tipo, funcion, solucion, respecto=None):
    ficha = SimpleNamespace(tipo=tipo, solucion=None, params={}, respecto=respecto, pistas=[])
    return Variante(ficha=ficha, semilla=0, params={}, funcion=funcion, solucion=solucion)


def _integral(f):
    return pasos(_variante("integral", f, sp.integrate(f, X)))


def _derivada(f):
    return pasos(_variante("derivada", f, sp.diff(f, X)))


class PasosIntegral(unittest.TestCase):
    def assertPalabras(self, lineas, *palabras):
        texto = "\n".join(lineas)
        self.assertTrue(lineas, "sin pasos")
        for p in palabras:
            self.assertIn(p, texto)

    def test_partes(self):
        self.assertPalabras(_integral(X * sp.exp(X)), "partes", "u = x", "dv =")

    def test_sustitucion(self):
        self.assertPalabras(_integral(X * sp.exp(X ** 2)), "u = x^2", "du = 2·x dx")

    def test_potencia(self):
        self.assertPalabras(_integral(X ** 3), "Potencia", "x^4/4")

    def test_logaritmo(self):
        self.assertPalabras(_integral(1 / X), "ln|x|")

    def test_arcotangente(self):
        self.assertPalabras(_integral(1 / (X ** 2 + 4)), "arctan")

    def test_fracciones_simples(self):
        self.assertPalabras(_integral(1 / (X ** 2 + X)), "Fracciones simples", "ln|")

    def test_trigonometrica(self):
        self.assertPalabras(_integral(sp.sin(X) ** 2), "Reescribe", "cos(2·x)")

    def test_cclica_partes_repetidas(self):
        self.assertPalabras(_integral(sp.exp(X) * sp.sin(X)), "partes", "reaparece")

    def test_ultimo_es_la_solucion(self):
        v = _variante("integral", X * sp.exp(X), sp.integrate(X * sp.exp(X), X))
        self.assertIn(v.solucion_texto, pasos(v)[-1])

    def test_no_pasa_de_unos_8(self):
        self.assertLessEqual(len(_integral(sp.expand(X ** 4 + 3 * X ** 3 - X ** 2 + 5 * X + 7))), 9)
        self.assertLessEqual(len(_integral(sp.sin(X) ** 2)), 9)


class PasosDerivada(unittest.TestCase):
    def test_producto(self):
        t = "\n".join(_derivada(X ** 2 * sp.sin(X)))
        self.assertIn("Producto", t)
        self.assertIn("f' = 2·x", t)
        self.assertIn("g' = cos(x)", t)

    def test_cadena(self):
        t = "\n".join(_derivada(sp.sin(X ** 2)))
        self.assertIn("Cadena", t)
        self.assertIn("dentro", t)
        self.assertIn("(2·x)", t)

    def test_cociente(self):
        self.assertIn("Cociente", "\n".join(_derivada((X + 1) / (X ** 2 + 3))))

    def test_suma(self):
        self.assertIn("Suma", "\n".join(_derivada(sp.sin(X ** 2) + sp.exp(3 * X))))

    def test_directa(self):
        self.assertIn("directamente", "\n".join(_derivada(X ** 3)))


class PasosParcial(unittest.TestCase):
    def test_otra_letra_es_constante(self):
        f = X ** 2 * Y ** 3
        v = _variante("parcial", f, sp.diff(f, Y), respecto="y")
        t = "\n".join(pasos(v))
        self.assertIn("x es un número (constante)", t)
        v = _variante("parcial", f, sp.diff(f, X), respecto="x")
        self.assertIn("y es un número (constante)", "\n".join(pasos(v)))


class PasosTodasLasFichas(unittest.TestCase):
    def test_ninguna_ficha_rompe_pista_4(self):
        """Sin limite de tiempo (la prueba no debe depender de la carga del equipo)."""
        vacias = []
        with mock.patch.object(modulo_pasos, "LIMITE_S", 300):
            self._recorrer(vacias)
        # Solo las que sympy no sabe resolver (trigonometricas raras)
        self.assertLessEqual(len(vacias), 6, vacias)

    def test_limite_de_tiempo(self):
        """Si sympy tarda mas que el limite, no hay pasos pero la pista da la solucion."""
        v = cargar()["PA-XEXP"].variante(1)
        with mock.patch.object(modulo_pasos, "LIMITE_S", 0.0001):
            self.assertEqual(modulo_pasos.pasos(v), [])
            self.assertIn("Solucion:", v.pista(4))

    def _recorrer(self, vacias):
        for ficha in cargar().values():
            v = ficha.variante(3)
            texto = v.pista(4)
            self.assertIn(f"Solucion: {v.solucion_texto}", texto, ficha.id)
            self.assertTrue(texto.rstrip().splitlines()[-1].startswith("Solucion:"), ficha.id)
            p = pasos(v)
            if p:
                self.assertIn(v.solucion_texto, p[-1], ficha.id)
            elif ficha.tipo in ("integral", "derivada", "parcial"):
                vacias.append(ficha.id)

    def test_otros_tipos_solo_dan_el_resultado(self):
        for ficha in cargar().values():
            if ficha.tipo not in ("integral", "derivada", "parcial"):
                v = ficha.variante(1)
                self.assertEqual(pasos(v), [], ficha.id)
                self.assertTrue(v.pista(4).startswith("Solucion:"), ficha.id)

    def test_pista_4_numera_los_pasos(self):
        v = _variante("integral", X * sp.exp(X), sp.integrate(X * sp.exp(X), X))
        v.ficha.pistas = []
        lineas = v.pista(4).splitlines()
        self.assertTrue(lineas[0].lstrip().startswith("1. "))
        self.assertTrue(lineas[-1].startswith("Solucion: "))


if __name__ == "__main__":
    unittest.main()
