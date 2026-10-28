"""Errores tipicos por ficha y modo examen."""
import unittest
from datetime import date

import sympy as sp

from calculo.diagnostico import coincide_error, diagnosticar, errores_tipicos
from calculo.expresiones import leer
from calculo.fichas import cargar
from calculo.planificador import cola, cola_examen, elegir_examen
from calculo.sesion import comprobar
from tests.test_planificador import entrada

FICHAS = cargar()
CON_ERRORES = [f for f in FICHAS.values() if f.errores]


def _texto_de_forma(v, error):
    """Una respuesta concreta que tiene la forma del error (el doble de la forma)."""
    return f"2·({error['forma'].format(**v.params)})"


class TestErroresTipicos(unittest.TestCase):
    def test_hay_errores_en_el_tema_2(self):
        ids = {f.id for f in CON_ERRORES}
        for fid in ("T2-GEN-COMP", "T2X-YP-RES", "T2-WR-EXP", "EX-EXP"):
            self.assertIn(fid, ids)

    def test_cada_error_se_reconoce_y_no_es_correcto(self):
        for f in CON_ERRORES:
            for semilla in (1, 2):
                v = f.variante(semilla)
                for error in f.errores:
                    texto = error["respuesta"].format(**v.params) if "respuesta" in error \
                        else _texto_de_forma(v, error)
                    if f.tipo in ("exacta",):
                        texto = texto.replace(";", ",")
                    with self.subTest(ficha=f.id, semilla=semilla, error=texto):
                        self.assertTrue(coincide_error(v, texto, error), "la plantilla no se reconoce")
                        self.assertFalse(comprobar(v, texto).correcto, "la plantilla de error es correcta")

    def test_la_respuesta_correcta_no_dispara_errores(self):
        for f in CON_ERRORES:
            v = f.variante(1)
            with self.subTest(ficha=f.id):
                self.assertEqual(errores_tipicos(v, v.respuesta_modelo), [])

    def test_el_error_propio_va_antes_que_el_generico(self):
        v = FICHAS["S-X3EXP"].construir({})
        self.assertIn("du = 4x^3 dx", diagnosticar(v, "e^(x^4) + C")[0])

    def test_resonancia(self):
        v = FICHAS["T2X-YP-RES"].construir({"a": 2, "b": 5})
        self.assertIn("resonancia", diagnosticar(v, "-e^(2x)/3")[0])


class TestModoExamen(unittest.TestCase):
    DIA = date(2026, 10, 27)

    def test_elige_la_p2(self):
        ex = elegir_examen(self.DIA)
        self.assertIn("P2", ex["nombre"])
        self.assertIn("P3", elegir_examen(self.DIA, "p3")["nombre"])
        self.assertIsNone(elegir_examen(self.DIA, "no existe"))

    def test_solo_tecnicas_del_examen_y_una_larga(self):
        ex = elegir_examen(self.DIA)
        lista = cola_examen(FICHAS, [], self.DIA, ex, n=8)
        self.assertEqual(len(lista), 8)
        self.assertTrue(all(x.ficha.tecnica in ex["tecnicas"] for x in lista))
        self.assertLessEqual(sum(x.ficha.larga for x in lista), 1)
        primeras = [x.ficha.tecnica for x in lista[:5]]
        self.assertEqual(len(primeras), len(set(primeras)))  # intercalado
        self.assertTrue(all(x.motivo == "examen" for x in lista))

    def test_primero_lo_mas_flojo(self):
        ex = elegir_examen(self.DIA)
        log = [entrada(FICHAS["T2-CAR-COMP"], date(2026, 10, 1), 1)]  # visto y fallado
        lista = cola_examen(FICHAS, log, self.DIA, ex)
        self.assertEqual(lista[0].ficha.id, "T2-CAR-COMP")

    def test_no_gasta_el_cupo(self):
        antes = cola(FICHAS, [], self.DIA)
        e = entrada(FICHAS["T2-CAR-REAL"], self.DIA, 3)
        e["motivo"] = "examen"
        despues = cola(FICHAS, [e], self.DIA)
        self.assertEqual(len(antes), len(despues))


if __name__ == "__main__":
    unittest.main()
