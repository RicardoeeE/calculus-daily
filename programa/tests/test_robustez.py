"""Tipos nuevos (algebra, definidas), registro danado y doctor."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calculo import registro
from calculo.doctor import revisar
from calculo.fichas import cargar
from calculo.sesion import comprobar


class TestTiposNuevos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = cargar()

    def test_algebra_formatos(self):
        v = self.fichas["AL-CUAD"].construir({"h": 3, "k": 4})
        self.assertIn("x^2 - 6x + 13", v.enunciado)
        for texto in ("3, 4", "h = 3, k = 4", "3;4"):
            self.assertTrue(comprobar(v, texto).correcto, texto)
        self.assertFalse(comprobar(v, "-3, 4").correcto)
        self.assertIn("2 valores", comprobar(v, "3").error)

    def test_fracciones(self):
        v = self.fichas["AL-FRAC"].construir({"n": 1, "p": 1, "q": -1})
        self.assertTrue(comprobar(v, "1/2, -1/2").correcto)
        self.assertTrue(comprobar(v, "0.5, -0.5").correcto)

    def test_definida(self):
        v = self.fichas["DF-ISOTERMO"].construir({"k": 2, "v1": 1, "v2": 3})
        self.assertTrue(comprobar(v, "2 ln(3)").correcto)
        self.assertTrue(comprobar(v, "ln 9").correcto)
        self.assertFalse(comprobar(v, "ln 3").correcto)
        self.assertIn("sin x", comprobar(v, "2 ln(x)").error)
        r = comprobar(v, "2 ln 3 + C")
        self.assertTrue(r.correcto)
        self.assertIn("en una definida no va +C", r.avisos)

    def test_laplace_impropia(self):
        v = self.fichas["DF-LAPLACE-T"].construir({"s": 2})
        self.assertIn("∞", v.enunciado)
        self.assertTrue(comprobar(v, "1/4").correcto)


class TestRegistroDanado(unittest.TestCase):
    def test_linea_cortada_se_salta_y_doctor_la_senala(self):
        tmp = Path(tempfile.mkdtemp()) / "registro.jsonl"
        tmp.write_text(
            '{"ts": "2026-10-27T18:00:00+01:00", "ficha": "I01", "nota": 3}\n'
            '{"ts": "2026-10-27T18:05:00+01:00", "fich\n'
            '{"ts": "2026-10-27T18:09:00+01:00", "ficha": "I02", "nota": 9}\n',
            encoding="utf-8")
        self.assertEqual([e["ficha"] for e in registro.leer(tmp)], ["I01"])
        with self.assertRaises(registro.ErrorRegistro):
            registro.leer(tmp, estricto=True)
        with mock.patch.object(registro, "RUTA", tmp):
            resultados = revisar()
        # Ya no bloquea (MAL); al empezar la sesion se aparta sola
        self.assertTrue(any(ok is None and "linea 2" in m and "apartado" in m for ok, m in resultados))


class TestDoctor(unittest.TestCase):
    def test_instalacion_actual_en_verde(self):
        malos = [m for ok, m in revisar() if ok is False]
        self.assertEqual(malos, [])


if __name__ == "__main__":
    unittest.main()
