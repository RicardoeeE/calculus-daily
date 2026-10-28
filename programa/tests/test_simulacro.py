"""Simulacro cronometrado (seleccion, cupo, informe, sin pistas)."""
import builtins
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import practica
from calculo import registro, sesion, tutela
from calculo.fichas import cargar
from calculo.planificador import cola, cola_simulacro, elegir_examen, examenes



def _mala(v):
    """Una respuesta equivocada que se puede leer (las ilegibles se piden otra vez)."""
    from calculo.sesion import comprobar
    for c in ("x^99", "99", "99, 98", "98, 99, 97", "x^99 + y^99", "99, 98, 97, 96"):
        r = comprobar(v, c)
        if not r.error and not r.correcto:
            return c
    raise AssertionError(f"sin respuesta mala legible para {v.ficha.id}")

class TestSimulacro(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.parches = [
            mock.patch.object(registro, "RUTA", self.tmp / "registro.jsonl"),
            mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
            mock.patch.object(sesion, "SIMULACROS", self.tmp / "simulacros"),
            mock.patch.object(practica, "CACHE", self.tmp / ".cache"),
            mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
            mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones"),
        ]
        for p in self.parches:
            p.start()
        self.fichas = cargar()
        self.dia = date.today()
        self.ex = elegir_examen(date(2026, 10, 28), "P2")

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def test_seleccion_con_largas_y_variada(self):
        lista = cola_simulacro(self.fichas, [], self.dia, self.ex, 4)
        self.assertEqual(len(lista), 4)
        self.assertGreaterEqual(sum(1 for x in lista if x.ficha.larga), 2)
        self.assertTrue(all(x.ficha.tecnica in self.ex["tecnicas"] for x in lista))
        self.assertTrue(all(x.motivo == "simulacro" for x in lista))
        self.assertEqual(len({x.ficha.id for x in lista}), 4)
        self.assertGreaterEqual(len({x.ficha.tecnica for x in lista}), 3)
        # Determinista, y distinta de la semilla del modo examen.
        self.assertEqual([(x.ficha.id, x.semilla) for x in lista],
                         [(x.ficha.id, x.semilla) for x in cola_simulacro(self.fichas, [], self.dia, self.ex, 4)])

    def test_no_gasta_cupo(self):
        antes = [x.ficha.id for x in cola(self.fichas, [], self.dia)]
        lista = cola_simulacro(self.fichas, [], self.dia, self.ex, 4)
        entradas = [{"ts": registro.ahora().isoformat(), "ficha": x.ficha.id, "tipo": x.ficha.tipo,
                     "grupo": x.ficha.grupo, "tecnica": x.ficha.tecnica, "semilla": x.semilla,
                     "motivo": "simulacro", "nota": 3, "correcto": True, "pistas": 0} for x in lista]
        despues = cola(self.fichas, entradas, self.dia)
        self.assertEqual(len(despues), len(antes))
        self.assertEqual(len(despues), 5)

    def test_repetir_el_mismo_dia_cambia_la_semilla(self):
        a = cola_simulacro(self.fichas, [], self.dia, self.ex, 4)
        entradas = [{"ts": registro.ahora().isoformat(), "ficha": x.ficha.id, "motivo": "simulacro", "nota": 3}
                    for x in a]
        b = cola_simulacro(self.fichas, entradas, self.dia, self.ex, 4)
        self.assertFalse({(x.ficha.id, x.semilla) for x in a} & {(x.ficha.id, x.semilla) for x in b})

    def _simulacro(self, respuestas, **kw):
        it = iter(respuestas)
        salida = io.StringIO()
        with mock.patch.object(builtins, "input", lambda p: next(it)), redirect_stdout(salida), \
                mock.patch.object(practica, "elegir_examen", lambda dia, nombre=None: self.ex):
            practica.sesion_simulacro(self.fichas, self.dia, "P2", git=False, **kw)
        return salida.getvalue()

    def test_sesion_completa_sin_pistas_y_con_informe(self):
        lista = cola_simulacro(self.fichas, [], self.dia, self.ex, 4)
        v0 = lista[0].ficha.variante(lista[0].semilla)
        malas = [_mala(x.ficha.variante(x.semilla)) for x in lista]
        # Enter para empezar; 1.º bien; 2.º mal; 3.º en blanco; 4.º «p» (no es una pista: es una respuesta
        # mala o, si no se lee, se pide otra vez) y despues una mala que si se lee.
        texto = self._simulacro(["", v0.respuesta_modelo, "x^99", malas[1], "", "p", malas[3]], minutos=40)
        self.assertNotIn("Pista:", texto)
        self.assertNotIn("Correcto.", texto)       # no hay correccion durante la prueba
        self.assertIn("Quedan 40 min", texto)
        self.assertIn("Nota: 1/4 (2,5 sobre 10)", texto)
        self.assertIn("SIN RESPONDER", texto)
        self.assertNotIn("Pista:", texto)
        log = registro.leer()
        self.assertEqual(len(log), 3)              # el ejercicio en blanco no se registra
        self.assertTrue(all(e["motivo"] == "simulacro" and e["pistas"] == 0 for e in log))
        self.assertEqual([e["correcto"] for e in log], [True, False, False])
        informes = list((self.tmp / "simulacros").glob("*.md"))
        self.assertEqual(len(informes), 1)
        self.assertTrue(informes[0].name.startswith(f"{self.dia.isoformat()}_P2"))
        md = informes[0].read_text(encoding="utf-8")
        self.assertIn("1/4", md)
        self.assertIn("Solucion:", md)
        self.assertIn("sin responder", md)

    def test_se_acaba_el_tiempo(self):
        # minutos = 0: nada se puede responder y no se registra nada.
        texto = self._simulacro([""], minutos=0)
        self.assertIn("Se acabo el tiempo", texto)
        self.assertEqual(registro.leer(), [])
        self.assertIn("Nota: 0/4", texto)
        self.assertEqual(len(list((self.tmp / "simulacros").glob("*.md"))), 1)

    def test_revisor_cola_y_motivo(self):
        salida = io.StringIO()
        with redirect_stdout(salida), mock.patch.object(practica, "elegir_examen", lambda dia, nombre=None: self.ex):
            practica.main(["simulacro", "--cola", "--nombre", "P2"])
        cola_ = json.loads(salida.getvalue())
        self.assertEqual(len(cola_), 4)
        self.assertEqual(cola_[0]["motivo"], "simulacro")
        x = cola_[0]
        self.assertEqual(practica.motivo_en_cola(self.dia, x["ficha"], x["semilla"]), "simulacro")
        v = self.fichas[x["ficha"]].variante(x["semilla"])
        sal = io.StringIO()
        with redirect_stdout(sal):
            practica.main(["registrar", x["ficha"], str(x["semilla"]), "--confianza", "3",
                           "--respuesta", v.respuesta_modelo])
        self.assertEqual(registro.leer()[0]["motivo"], "simulacro")
        # Volver a pedir la cola devuelve los 3 que faltan (el mismo simulacro).
        sal = io.StringIO()
        with redirect_stdout(sal), mock.patch.object(practica, "elegir_examen", lambda dia, nombre=None: self.ex):
            practica.main(["simulacro", "--cola", "--nombre", "P2"])
        self.assertEqual(len(json.loads(sal.getvalue())), 3)

    def test_datos_incluyen_simulacros(self):
        self.assertIn("usuario/simulacros", sesion._DATOS)

    def test_el_calendario_real_tiene_examenes(self):
        self.assertTrue(examenes())


if __name__ == "__main__":
    unittest.main()
