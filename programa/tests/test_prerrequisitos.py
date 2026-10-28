"""Fichas de algebra de prerrequisitos (trigonometria, logaritmos, potencias, sistemas, cubicas)."""
import unittest

from calculo.fichas import cargar
from calculo.sesion import comprobar

NUEVAS = ("AL-TRIG", "AL-TAN", "AL-DOBLE", "AL-PITAG", "AL-LNPROP", "AL-LNEXP", "AL-POT",
          "AL-SIS2", "AL-SIS2C", "AL-CUBICA")


class TestPrerrequisitos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = cargar()

    def test_estan_todas_con_fuente_y_pistas(self):
        for id_ in NUEVAS:
            f = self.fichas[id_]
            with self.subTest(ficha=id_):
                self.assertEqual(f.tipo, "algebra")
                self.assertTrue(f.fuente.startswith("prerrequisito"), f.fuente)
                self.assertEqual(len(f.pistas), 3)
                self.assertTrue(f.identidad)   # la clave se verifica con una identidad

    def test_todas_las_combinaciones_cuadran(self):
        for id_ in NUEVAS:
            for params in self.fichas[id_].combinaciones():
                with self.subTest(ficha=id_, params=params):
                    self.fichas[id_].construir(params)

    def test_trig_notables_escritos_a_mano(self):
        f = self.fichas["AL-TRIG"]
        v = next(f.construir({"ang": a}) for a in f.params["ang"] if a == "π/3")
        self.assertTrue(comprobar(v, "√3/2, 1/2").correcto)
        self.assertTrue(comprobar(v, "sen = sqrt(3)/2, cos = 1/2").correcto)
        self.assertFalse(comprobar(v, "1/2, √3/2").correcto)   # al reves
        v = f.construir({"ang": "π/4"})
        self.assertTrue(comprobar(v, "√2/2, √2/2").correcto)
        self.assertTrue(comprobar(v, "1/√2, 1/√2").correcto)

    def test_sistema_2x2_es_el_pvi_del_tema_2(self):
        v = self.fichas["AL-SIS2"].construir({"r1": 1, "r2": 3, "a": 1, "b": 0})
        # C1 + C2 = 1 y C1 + 3C2 = 0  ->  C1 = 3/2, C2 = -1/2
        self.assertTrue(comprobar(v, "3/2, -1/2").correcto)
        self.assertTrue(comprobar(v, "C1 = 3/2, C2 = -1/2").correcto)
        self.assertFalse(comprobar(v, "-1/2, 3/2").correcto)

    def test_cubica_en_orden(self):
        v = self.fichas["AL-CUBICA"].construir({"r1": -2, "r2": 1, "r3": 3})
        self.assertIn("x^3 - 2x^2 - 5x + 6", v.enunciado)
        self.assertTrue(comprobar(v, "-2, 1, 3").correcto)
        self.assertFalse(comprobar(v, "-2, 1, 4").correcto)

    def test_previa_en_el_tema_2_de_pvi(self):
        self.assertEqual(self.fichas["T2X-PVI-REAL"].previa, "AL-SIS2")
        self.assertEqual(self.fichas["T2X-PVI-COMP"].previa, "AL-SIS2C")
        self.assertEqual(self.fichas["T2X-CAR-ORD3"].previa, "AL-CUBICA")


if __name__ == "__main__":
    unittest.main()
