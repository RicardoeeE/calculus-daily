"""_edo_texto con \\b de verdad y la solucion con el texto del autor."""
import unittest

from calculo.expresiones import limpiar
from calculo.fichas import _edo_texto, cargar
from calculo.sesion import comprobar

FICHAS = cargar()


class TestEdoTexto(unittest.TestCase):
    """Las dos regex llevaban un retroceso literal (\\x08) en vez de \\b: nunca quitaban
    «+ 0y'» ni el 1 de «1y»."""

    def test_sin_retroceso(self):
        import inspect
        self.assertNotIn("\x08", inspect.getsource(_edo_texto))

    def test_quita_ceros_y_unos(self):
        self.assertEqual(_edo_texto("ypp + 0yp + 4y"), "y'' + 4y")
        self.assertEqual(_edo_texto("ypp - 0yp - 1y"), "y'' - y")
        self.assertEqual(_edo_texto("1ypp + 3yp + 2y"), "y'' + 3y' + 2y")
        self.assertEqual(_edo_texto("ypp + 10y"), "y'' + 10y")       # el 1 de 10 no se toca
        self.assertEqual(_edo_texto("ypp + 2.1y"), "y'' + 2.1y")     # ni el de 2.1

    def test_enunciados_edo(self):
        for f in FICHAS.values():
            if f.tipo != "edo_solucion":
                continue
            for s in range(5):
                e = f.variante(s).enunciado
                with self.subTest(ficha=f.id, semilla=s):
                    self.assertNotIn("0y", e.replace("10y", "").replace("20y", ""))
                    self.assertNotRegex(e, r"(?<![\w.])1\s*y")


class TestSolucionDelAutor(unittest.TestCase):
    def test_con_parametros_forma_de_clase(self):
        con = [f for f in FICHAS.values() if f.solucion is not None and f.params
               and f.tipo in ("integral", "derivada", "definida", "parcial", "edo_solucion", "calculo")]
        self.assertTrue(con)
        for f in con:
            for s in range(3):
                v = f.variante(s)
                with self.subTest(ficha=f.id, semilla=s):
                    self.assertNotIn("{", v.solucion_texto)
                    r = comprobar(v, v.respuesta_modelo)
                    self.assertTrue(r.correcto, (v.respuesta_modelo, r.error))

    def test_todas_las_fichas_aceptan_su_solucion(self):
        for f in FICHAS.values():
            v = f.variante(1)
            with self.subTest(ficha=f.id):
                self.assertTrue(comprobar(v, v.respuesta_modelo).correcto, v.respuesta_modelo)

    def test_ejemplos_de_clase(self):
        # Con parametros, el texto del autor se usa si no es mas largo que la forma de sympy:
        # C-ATAN («arctan((x - 2)/3)/3») si; T2X-PVI-REAL y DCO-EXP («(4 e^(-x) + 1 e^(4x))/(4 + 1)»,
        # «(x + 1 - 1)e^x») no, porque la plantilla sustituida queda sin operar.
        for fid, autor in (("C-ATAN", True), ("T2X-PVI-REAL", False), ("DCO-EXP", False)):
            if fid not in FICHAS:
                continue
            f = FICHAS[fid]
            v = f.variante(1)
            with self.subTest(ficha=fid):
                plantilla = limpiar(f.solucion.format(**v.params)) if f.params else f.solucion
                self.assertEqual(v.solucion_texto.removesuffix(" + C") == plantilla, autor)
                self.assertTrue(comprobar(v, v.respuesta_modelo).correcto)


if __name__ == "__main__":
    unittest.main()
