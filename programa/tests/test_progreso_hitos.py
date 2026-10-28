"""El escalon guardado no baja (progreso.jsonl) y raices con coma decimal."""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from calculo import registro, rutas, sesion
from calculo.fichas import cargar
from calculo.planificador import guardar_hitos, leer_hitos, progreso, progreso_al_dia
from calculo.verificar import comprobar_raices, leer_raices

FICHAS = cargar()


def _dominar(tecnica, n=6):
    ids = sorted(f.id for f in FICHAS.values() if f.tecnica == tecnica)[:2]
    t0 = datetime(2026, 10, 1, 10).astimezone()
    return [{"ts": (t0 + timedelta(days=i)).isoformat(), "ficha": ids[i % len(ids)], "tipo": FICHAS[ids[0]].tipo,
             "grupo": FICHAS[ids[0]].grupo, "tecnica": tecnica, "semilla": i, "nota": 3, "correcto": True,
             "pistas": 0} for i in range(n)]


class TestHitos(unittest.TestCase):
    """El escalon se recalculaba con las fichas actuales y bajaba si se
    anadian tecnicas a un escalon ya superado."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = self.tmp / "progreso.jsonl"
        # Antes: el escalon 1 de derivadas solo tenia «potencia».
        self.antes = {fid: f for fid, f in FICHAS.items() if f.grupo != "derivada" or f.tecnica not in
                      ("cadena", "producto")}
        self.entradas = _dominar("potencia")

    def test_no_baja_al_anadir_tecnicas(self):
        self.assertEqual(progreso_al_dia(self.antes, self.entradas, self.ruta).escalon["derivada"], 2)
        # Sin hitos, con las tecnicas nuevas en el escalon 1, se volvia al 1 (el fallo).
        self.assertEqual(progreso(FICHAS, self.entradas).escalon["derivada"], 1)
        self.assertEqual(progreso_al_dia(FICHAS, self.entradas, self.ruta).escalon["derivada"], 2)
        self.assertEqual(leer_hitos(self.ruta)["derivada"], 2)

    def test_solo_anade_lineas_al_subir(self):
        progreso_al_dia(self.antes, self.entradas, self.ruta)
        n = len(self.ruta.read_text(encoding="utf-8").splitlines())
        progreso_al_dia(self.antes, self.entradas, self.ruta)
        self.assertEqual(len(self.ruta.read_text(encoding="utf-8").splitlines()), n)

    def test_sin_fichero_o_roto_no_rompe(self):
        self.assertEqual(leer_hitos(self.tmp / "no-existe.jsonl"), {})
        self.ruta.write_text('<<<<<<< HEAD\n{"grupo": "integral", "escalon": 3}\nbasura\n{"grupo": 7}\n'
                             '{"grupo": "derivada", "escalon": "x"}\n', encoding="utf-8")
        self.assertEqual(leer_hitos(self.ruta), {"integral": 3})
        self.assertEqual(progreso(FICHAS, [], leer_hitos(self.ruta)).escalon["integral"], 3)

    def test_union_de_dos_equipos_toma_el_maximo(self):
        self.ruta.write_text('{"grupo": "integral", "escalon": 2}\n{"grupo": "integral", "escalon": 4}\n'
                             '{"grupo": "integral", "escalon": 3}\n', encoding="utf-8")
        self.assertEqual(leer_hitos(self.ruta)["integral"], 4)
        guardar_hitos({"integral": 3}, self.ruta)   # menor: no se escribe nada
        self.assertEqual(len(self.ruta.read_text(encoding="utf-8").splitlines()), 3)

    def test_cerrar_lo_guarda_junto_al_registro(self):
        reg = self.tmp / "registro.jsonl"
        for e in self.entradas:
            registro.anadir({**e, "ts": registro.ahora().isoformat(), "enunciado": "x"}, reg)
        with mock.patch.object(sesion, "DIARIO", self.tmp / "diario.md"):
            sesion.cerrar_local(registro.ahora().date(), self.antes, ruta=reg)
        self.assertEqual(leer_hitos(self.tmp / "progreso.jsonl").get("derivada"), 2)

    def test_en_los_datos_que_se_suben(self):
        self.assertIn("usuario/datos/progreso.jsonl", sesion._DATOS)
        attrs = (rutas.RAIZ / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("usuario/datos/progreso.jsonl merge=union", attrs)


class TestRaicesComaDecimal(unittest.TestCase):
    """«0,5, 3» se partia en 0 | 5 | 3."""

    def test_mismo_criterio_que_partir(self):
        self.assertEqual(leer_raices("0,5, 3").leido, "0.5, 3")
        self.assertEqual(leer_raices("0,5; 3").leido, "0.5, 3")
        self.assertEqual(leer_raices("2, -3").leido, "2, -3")
        self.assertEqual(leer_raices("2,-3").leido, "2, -3")
        self.assertTrue(comprobar_raices("0,5, 3", [0.5, 3]).correcto)
        self.assertTrue(comprobar_raices("3; 1/2", [0.5, 3]).correcto)

    def test_complejas_siguen(self):
        self.assertEqual(len(leer_raices("1±2i").exprs), 2)


if __name__ == "__main__":
    unittest.main()
