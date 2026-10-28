"""Racha para el recordatorio (2026-10-28): dias seguidos con 2 ejercicios o mas;
el fin de semana sin practica no la rompe."""
import unittest
from datetime import date

from calculo.registro import racha


def intentos(*dias, n=2):
    return [{"ts": f"{d.isoformat()}T08:00:00+01:00", "ficha": "D01", "nota": 3}
            for d in dias for _ in range(n)]


class TestRacha(unittest.TestCase):
    def test_vacio(self):
        self.assertEqual(racha([], date(2026, 10, 28)), (False, 0))

    def test_hoy_hecho_cuenta(self):
        e = intentos(date(2026, 10, 27), date(2026, 10, 28))  # martes y miercoles
        self.assertEqual(racha(e, date(2026, 10, 28)), (True, 2))

    def test_hoy_sin_hacer_cuenta_hasta_ayer(self):
        e = intentos(date(2026, 10, 26), date(2026, 10, 27))
        self.assertEqual(racha(e, date(2026, 10, 28)), (False, 2))

    def test_un_ejercicio_no_basta(self):
        e = intentos(date(2026, 10, 28), n=1)
        self.assertEqual(racha(e, date(2026, 10, 28)), (False, 0))

    def test_hueco_entre_semana_rompe(self):
        e = intentos(date(2026, 10, 26), date(2026, 10, 28))  # falta el martes
        self.assertEqual(racha(e, date(2026, 10, 28)), (True, 1))

    def test_fin_de_semana_no_rompe(self):
        # viernes 23 y lunes 26; sabado y domingo sin practica
        e = intentos(date(2026, 10, 23), date(2026, 10, 26))
        self.assertEqual(racha(e, date(2026, 10, 26)), (True, 2))

    def test_fin_de_semana_practicado_suma(self):
        e = intentos(date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 26))
        self.assertEqual(racha(e, date(2026, 10, 26)), (True, 3))


if __name__ == "__main__":
    unittest.main()
