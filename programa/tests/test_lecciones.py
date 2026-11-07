"""Lecciones: estructura, formulas que se pintan y matematicas comprobadas con sympy."""
import unittest

import sympy as sp

from calculo.fichas import NOMBRES_TECNICA, cargar, cargar_lecciones
from calculo.latex import trozos
from calculo.ventana import API

CAMPOS = ("titulo", "tema", "que_es", "reconocer", "forma", "pasos", "ojo", "ejemplo", "guiado")
EDO2 = {"producto", "partes", "caracteristica", "comprobar_solucion", "wronskiano", "forma_yp", "pvi"}


def textos(d):
    """Todos los textos de una leccion que se pintan."""
    if isinstance(d, str):
        yield d
    elif isinstance(d, list):
        for x in d:
            yield from textos(x)
    elif isinstance(d, dict):
        for k, v in d.items():
            if k not in ("tecnica", "titulo", "tema", "correcta", "verificar"):
                yield from textos(v)


class TestLecciones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lecciones = cargar_lecciones()

    def test_cubre_las_tecnicas_de_derivadas_integrales_y_edo2(self):
        self.assertLessEqual(EDO2, set(self.lecciones))

    def test_toda_tecnica_tiene_nombre(self):
        self.assertEqual({f.tecnica for f in cargar().values()} - set(NOMBRES_TECNICA), set())

    def test_estructura(self):
        for tecnica, d in self.lecciones.items():
            with self.subTest(tecnica=tecnica):
                self.assertIn(tecnica, NOMBRES_TECNICA)
                for campo in CAMPOS:
                    self.assertTrue(d.get(campo), campo)
                self.assertGreaterEqual(len(d["ejemplo"]), 2, "varios ejemplos")
                for ej in d["ejemplo"]:
                    self.assertTrue(ej["enunciado"] and ej["pasos"] and ej["resultado"] and ej["verificar"])

    def test_guiado_una_sola_correcta_y_todas_explican(self):
        for tecnica, d in self.lecciones.items():
            g = d["guiado"]
            self.assertTrue(g["enunciado"] and g["cierre"] and g["verificar"])
            self.assertGreaterEqual(len(g["paso"]), 3)
            for p in g["paso"]:
                with self.subTest(tecnica=tecnica, pregunta=p["pregunta"]):
                    self.assertEqual(sum(bool(o.get("correcta")) for o in p["opciones"]), 1)
                    self.assertGreaterEqual(len(p["opciones"]), 3)
                    self.assertTrue(all(o["texto"] and o["porque"] for o in p["opciones"]))
                    self.assertEqual(len({o["texto"] for o in p["opciones"]}), len(p["opciones"]))

    def test_la_correcta_no_va_siempre_en_el_mismo_sitio(self):
        for tecnica, d in self.lecciones.items():
            sitios = {next(i for i, o in enumerate(p["opciones"]) if o.get("correcta")) for p in d["guiado"]["paso"]}
            self.assertGreaterEqual(len(sitios), 2, tecnica)

    def test_las_cuentas_salen(self):
        x, r = sp.Symbol("x"), sp.Symbol("r")
        for tecnica, d in self.lecciones.items():
            pares = [par for ej in d["ejemplo"] for par in ej["verificar"]] + d["guiado"]["verificar"]
            for a, b in pares:
                with self.subTest(tecnica=tecnica, a=a):
                    izq = sp.sympify(a, locals={"x": x, "r": r})
                    der = sp.sympify(b, locals={"x": x, "r": r})
                    self.assertEqual(sp.simplify(izq - der), 0)

    def test_toda_formula_se_convierte(self):
        for tecnica, d in self.lecciones.items():
            for texto in textos(d):
                with self.subTest(tecnica=tecnica, texto=texto):
                    self.assertEqual(texto.count("$") % 2, 0)
                    self.assertFalse([p for p in trozos(texto) if p.get("mono")], "formula sin convertir")

    def test_la_ventana_recibe_trozos_y_no_las_comprobaciones(self):
        api = API.__new__(API)
        d = api._leccion_trozos(self.lecciones["producto"])
        self.assertEqual(d["titulo"], "Regla del producto")
        self.assertNotIn("verificar", d["ejemplo"][0])
        self.assertTrue(any("tex" in t for t in d["forma"]))
        self.assertTrue(d["guiado"]["paso"][0]["opciones"][1]["correcta"])

    def test_alpes_aclarado_en_producto_y_partes(self):
        for tecnica in ("producto", "partes"):
            self.assertIn("ALPES", " ".join(self.lecciones[tecnica]["ojo"]))


if __name__ == "__main__":
    unittest.main()
