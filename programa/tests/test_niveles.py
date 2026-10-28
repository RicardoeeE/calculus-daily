"""Niveles visibles, intercalado en repasos y algebra previa."""
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from calculo import registro
from calculo.fichas import cargar
from calculo.planificador import Dominio, cola, dominio, nivel, subidas_de_nivel
from calculo.sesion import cerrar, informe, resumen_dia

FICHAS = cargar()


def entrada(ficha, dia, nota, hora=18):
    f = FICHAS[ficha]
    ts = datetime.combine(dia, time(hora)).astimezone().isoformat()
    return {"ts": ts, "ficha": f.id, "tipo": f.tipo, "grupo": f.grupo, "tecnica": f.tecnica,
            "nota": nota, "correcto": nota > 1, "nueva": True, "pistas": 0, "enunciado": f"{f.id} {ts}"}


def _dom(intentos, aciertos, ok=1, pedidas=2):
    from calculo.planificador import prob_mayor
    return Dominio("t", intentos, aciertos, ok, pedidas, prob_mayor(aciertos, intentos - aciertos))


class TestNivel(unittest.TestCase):
    def test_escalera_de_niveles(self):
        self.assertEqual(nivel(_dom(0, 0, 0)), "sin empezar")
        self.assertEqual(nivel(_dom(2, 0, 0)), "sin empezar")   # fallos solos: aun sin empezar
        self.assertEqual(nivel(_dom(1, 1)), "familiar")
        self.assertEqual(nivel(_dom(2, 2)), "familiar")         # pocos intentos
        self.assertEqual(nivel(_dom(3, 3)), "competente")
        self.assertEqual(nivel(_dom(5, 1)), "familiar")         # P(p > 0,7) < 0,3
        self.assertEqual(nivel(_dom(4, 4, ok=2)), "dominada")

    def test_dominada_coincide_con_la_regla_actual(self):
        d = Dominio("t", 4, 4, 2, 2, 0.9)
        self.assertTrue(d.dominada)
        self.assertEqual(nivel(d), "dominada")

    def test_subida_y_sin_aviso_si_baja(self):
        d0 = date(2026, 11, 2)
        antes = [entrada("D01", d0 - timedelta(i), 3) for i in (1, 2)]    # 2 aciertos: familiar
        hoy = [entrada("D01", d0, 3)]                                       # 3 aciertos: competente
        self.assertEqual(subidas_de_nivel(antes + hoy, d0, FICHAS),
                         [("potencia", "familiar", "competente")])
        malo = antes + [entrada("D01", d0 - timedelta(3), 3), entrada("D01", d0, 1)]  # baja: no se dice
        self.assertEqual(subidas_de_nivel(malo, d0, FICHAS), [])
        self.assertEqual(subidas_de_nivel(antes, d0 + timedelta(5), FICHAS), [])  # nada hoy

    def test_primer_acierto_sube_de_sin_empezar(self):
        d0 = date(2026, 11, 2)
        self.assertEqual(subidas_de_nivel([entrada("D01", d0, 3)], d0, FICHAS),
                         [("potencia", "sin empezar", "familiar")])

    def test_resumen_y_cerrar_muestran_la_subida(self):
        d0 = date(2026, 11, 2)
        log = [entrada("D01", d0 - timedelta(1), 3), entrada("D01", d0 - timedelta(2), 3), entrada("D01", d0, 3)]
        self.assertIn("potencia: familiar → competente", resumen_dia(log[-1:], [("potencia", "familiar", "competente")]))
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "registro.jsonl"
            for e in log:
                registro.anadir(e, ruta)
            texto = cerrar(d0, FICHAS, git=False, ruta=ruta, diario=Path(tmp) / "diario.md")
            self.assertIn("Nivel: potencia: familiar → competente", texto)
            informe_ = informe(d0, FICHAS, ruta=ruta)
            self.assertIn("potencia [competente]", informe_)
            self.assertIn("[sin empezar]", informe_)

    def test_nada_de_rachas_ni_castigos(self):
        d0 = date(2026, 11, 2)
        log = [entrada("D01", d0 - timedelta(i), 3) for i in (1, 2, 3)] + [entrada("D01", d0, 1)]
        self.assertNotIn("Nivel", resumen_dia(log[-1:], subidas_de_nivel(log, d0, FICHAS)))


class TestIntercalado(unittest.TestCase):
    def test_repasos_de_tecnicas_distintas(self):
        """Con 2 plazas y repasos vencidos de varias tecnicas, no salen dos de la misma."""
        dia = date(2026, 12, 1)
        # Tres de «tabla» (las mas olvidadas) y dos de otras tecnicas, mas recientes.
        log = [entrada("I01", date(2026, 9, 1), 3), entrada("I02", date(2026, 9, 2), 3),
               entrada("I03", date(2026, 9, 3), 3), entrada("L-RAIZ", date(2026, 9, 20), 3),
               entrada("I05", date(2026, 9, 25), 3)]
        cola_ = cola(FICHAS, log, dia, calendario="no-existe.toml")
        integrales = [x for x in cola_ if x.ficha.grupo == "integral"]
        self.assertEqual([x.motivo for x in integrales], ["repaso", "repaso"])
        ids = {x.ficha.id for x in integrales}
        self.assertIn("I01", ids)                          # la mas olvidada sigue dentro
        self.assertEqual(ids, {"I01", "L-RAIZ"})              # y la mas olvidada de otra tecnica
        self.assertEqual(len({x.ficha.tecnica for x in integrales}), 2)

    def test_si_solo_hay_una_tecnica_se_repite(self):
        dia = date(2026, 12, 1)
        log = [entrada(i, date(2026, 9, 1 + k), 3) for k, i in enumerate(["I01", "I02", "I03", "P-XRAIZ", "P-POT"])]
        integrales = [x for x in cola(FICHAS, log, dia, calendario="no-existe.toml") if x.ficha.grupo == "integral"]
        self.assertEqual({x.ficha.id for x in integrales}, {"I01", "I02"})


class TestPrevia(unittest.TestCase):
    dia = date(2026, 12, 1)

    def atascada(self, ficha="I04"):
        return [entrada(ficha, self.dia - timedelta(4 - k), 1) for k in range(4)]

    def test_las_previas_apuntan_a_algebra(self):
        con_previa = [f for f in FICHAS.values() if f.previa]
        self.assertGreaterEqual(len(con_previa), 20)
        for f in con_previa:
            self.assertEqual(FICHAS[f.previa].tipo, "algebra", f.id)
        self.assertEqual(FICHAS["I04"].previa, "AL-CUAD")
        self.assertEqual(FICHAS["R-DOS"].previa, "AL-FRAC")

    def test_ficha_atascada_cambia_el_calentamiento(self):
        cola_ = cola(FICHAS, self.atascada(), self.dia, calendario="no-existe.toml")
        algebra = [x for x in cola_ if x.ficha.grupo == "algebra"]
        self.assertEqual([(x.ficha.id, x.motivo) for x in algebra], [("AL-CUAD", "previa")])
        self.assertNotIn("I04", {x.ficha.id for x in cola_})   # la atascada sigue apartada

    def test_sin_atasco_el_calentamiento_es_el_normal(self):
        cola_ = cola(FICHAS, [], self.dia, calendario="no-existe.toml")
        self.assertNotIn("previa", {x.motivo for x in cola_})

    def test_no_se_repite_si_ya_se_hizo_hoy(self):
        log = self.atascada() + [entrada("AL-CUAD", self.dia, 3)]
        cola_ = cola(FICHAS, log, self.dia, calendario="no-existe.toml")
        self.assertEqual([x for x in cola_ if x.ficha.grupo == "algebra"], [])

    def test_dia_minimo_no_tiene_calentamiento(self):
        cola_ = cola(FICHAS, self.atascada(), self.dia, minimo=True, calendario="no-existe.toml")
        self.assertEqual([x for x in cola_ if x.ficha.grupo == "algebra"], [])

    def test_pasada_la_pausa_vuelve_lo_normal(self):
        cola_ = cola(FICHAS, self.atascada(), self.dia + timedelta(10), calendario="no-existe.toml")
        self.assertNotIn("previa", {x.motivo for x in cola_})


if __name__ == "__main__":
    unittest.main()
