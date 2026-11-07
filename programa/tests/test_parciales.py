"""Parciales, EDOs exactas, funcion potencial y modo foco."""
import unittest
from datetime import date, timedelta

import sympy as sp

from calculo.expresiones import X, Y
from calculo.fichas import cargar
from calculo.planificador import (
    CUPO, CUPO_FOCO, CUPO_FOCO_DERIVADA, CUPO_MINIMO_FOCO, ESCALON_FOCO, cola, cupos, foco_activo, progreso,
)
from calculo.sesion import comprobar
from calculo.verificar import comprobar_parcial
from tests.test_planificador import entrada

M = sp.exp(X**2) * (2 * X * Y + X)
N = sp.exp(X**2)


class TestParciales(unittest.TestCase):
    def test_exacta_tipica(self):
        self.assertTrue(comprobar_parcial("2x e^(x^2)", M, Y).correcto)
        self.assertTrue(comprobar_parcial("e^(x^2)·2x", N, X).correcto)

    def test_errores_tipicos(self):
        # derivar tambien la x de e^(x^2) cuando se deriva respecto a y
        self.assertFalse(comprobar_parcial("2x e^(x^2)(2x y + x) + 2x e^(x^2)", M, Y).correcto)
        # olvidar la cadena
        self.assertFalse(comprobar_parcial("e^(x^2)", N, X).correcto)
        # derivar respecto a la letra equivocada
        self.assertFalse(comprobar_parcial("2y e^(x^2)", M, Y).correcto)

    def test_exacta_y_potencial(self):
        fichas = cargar()
        v = fichas["EX-EXP"].variante(0)
        self.assertTrue(comprobar(v, "2x e^(x^2), 2x e^(x^2)").correcto)
        self.assertFalse(comprobar(v, "2x e^(x^2), 0").correcto)
        self.assertIn("es exacta", v.solucion_texto)
        self.assertIn("no es exacta", fichas["EX-NO"].variante(0).solucion_texto)
        p = fichas["PO-EXP"].variante(0)
        self.assertTrue(comprobar(p, "y e^(x^2) + e^(x^2)/2 + C").correcto)
        self.assertTrue(comprobar(p, "e^(x^2)(y + 1/2) + 5").correcto)
        self.assertFalse(comprobar(p, "y e^(x^2) + C").correcto)


class TestFoco(unittest.TestCase):
    def test_foco_al_empezar(self):
        fichas = cargar()
        self.assertTrue(foco_activo(fichas, []))
        self.assertEqual(cupos(fichas, []), CUPO_FOCO)
        c = cola(fichas, [], date(2026, 10, 27))
        grupos = [x.ficha.grupo for x in c]
        self.assertEqual(grupos.count("parcial"), CUPO_FOCO["parcial"])
        self.assertEqual(grupos.count("derivada"), CUPO_FOCO["derivada"])
        self.assertEqual(len(c), sum(CUPO_FOCO.values()))

    def test_foco_se_apaga_al_dominar(self):
        fichas = cargar()
        log = []
        dia = date(2026, 11, 1)
        tecnicas = {f.tecnica for f in fichas.values() if f.grupo == "parcial"}
        for tecnica in sorted(tecnicas):
            dos = [f for f in fichas.values() if f.tecnica == tecnica][:2]
            log += [entrada(dos[i % len(dos)], dia, 3) for i in range(4)]
        self.assertFalse(foco_activo(fichas, log))
        self.assertEqual(cupos(fichas, log), CUPO)

    def test_carga_total_igual(self):
        self.assertEqual(sum(CUPO.values()), sum(CUPO_FOCO.values()))
        self.assertEqual(sum(CUPO.values()), sum(CUPO_FOCO_DERIVADA.values()))

    def _dominar(self, fichas, tecnicas, dia, nota=3):
        log = []
        for tecnica in sorted(tecnicas):
            dos = [f for f in fichas.values() if f.tecnica == tecnica][:2]
            log += [entrada(dos[i % len(dos)], dia, nota) for i in range(4)]
        return log

    def test_foco_se_apaga_sin_orden_superior(self):
        """Basta con dominar los escalones 1-4 (parciales y exactas), no las EDOs de orden superior."""
        fichas = cargar()
        base = {f.tecnica for f in fichas.values() if f.grupo == "parcial" and f.escalon <= ESCALON_FOCO}
        self.assertEqual(base, {"constante", "parcial_cadena", "exactitud", "potencial"})
        log = self._dominar(fichas, base, date(2026, 11, 1))
        self.assertFalse(foco_activo(fichas, log))
        self.assertTrue(foco_activo(fichas, log[:-4]))   # sin la ultima tecnica, sigue

    def test_foco_mira_alguna_vez_no_a_la_vez(self):
        """Cada tecnica dominada alguna vez; antes, las 4 a la vez."""
        fichas = cargar()
        dia = date(2026, 11, 1)
        log = self._dominar(fichas, {"constante"}, dia)
        log += self._dominar(fichas, {"constante"}, dia + timedelta(1), nota=1)   # se pierde
        log += self._dominar(fichas, {"parcial_cadena", "exactitud", "potencial"}, dia + timedelta(2))
        self.assertNotIn("constante", progreso(fichas, log).dominadas)
        self.assertFalse(foco_activo(fichas, log))

    def test_derivada_un_dia_si_otro_no(self):
        """Con el foco, si el ultimo dia practicado no hubo derivada, hoy hay una
        (en lugar del algebra); si la hubo, vuelve el algebra. Los dias saltados no cuentan."""
        fichas = cargar()
        d0 = date(2026, 11, 3)
        self.assertEqual(cupos(fichas, [], dia=d0), CUPO_FOCO)   # primer dia: algebra
        log = [entrada(fichas["I01"], d0, 3)]
        self.assertEqual(cupos(fichas, log, dia=d0 + timedelta(3)), CUPO_FOCO_DERIVADA)
        c = cola(fichas, log, d0 + timedelta(3))
        self.assertEqual([x.ficha.grupo for x in c].count("derivada"), 1)
        log += [entrada(x.ficha, d0 + timedelta(3), 3) for x in c]
        self.assertEqual(cupos(fichas, log, dia=d0 + timedelta(4)), CUPO_FOCO)
        self.assertEqual(cupos(fichas, log, dia=d0 + timedelta(4), minimo=True), CUPO_MINIMO_FOCO)

    def test_sin_dia_cupo_de_siempre(self):
        self.assertEqual(cupos(cargar(), []), CUPO_FOCO)


if __name__ == "__main__":
    unittest.main()
