"""Ejemplos resueltos con huecos (retirada progresiva)."""
import builtins
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import practica
from calculo import registro, sesion, tutela
from calculo.fichas import cargar, cargar_ejemplos
from calculo.huecos import HUECO, huecos_de, recortar
from calculo.planificador import elegir_examen


def _e(tecnica, nota, motivo="nueva"):
    return {"tecnica": tecnica, "nota": nota, "motivo": motivo}


class TestCalculoHuecos(unittest.TestCase):
    # Antes quien fallaba o se rendia veia un ejemplo con
    # 1 hueco, MAS dificil que el completo de quien nunca lo intento. Ahora el numero de
    # huecos sigue a los aciertos y un fallo reciente devuelve el ejemplo completo.
    def test_segun_aciertos(self):
        self.assertEqual(huecos_de([], "tabla"), 0)
        self.assertEqual(huecos_de([_e("otra", 4)], "tabla"), 0)
        self.assertEqual(huecos_de([_e("tabla", 1), _e("tabla", 2)], "tabla"), 0)   # nunca acertada
        self.assertEqual(huecos_de([_e("tabla", 3)], "tabla"), 1)
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 4)], "tabla"), 2)
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 2)], "tabla"), 1)   # con ayuda no es fallo
        self.assertIsNone(huecos_de([_e("tabla", 3), _e("tabla", 4), _e("tabla", 3)], "tabla"))

    def test_tras_un_fallo_ejemplo_completo(self):
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 1)], "tabla"), 0)
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 4), _e("tabla", 1)], "tabla"), 0)
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 1), _e("tabla", 3)], "tabla"), 2)
        # Desde 3 aciertos ya no hay ejemplo aunque falle (lo cubren pistas y repaso).
        self.assertIsNone(huecos_de([_e("tabla", 3)] * 3 + [_e("tabla", 1)], "tabla"))

    def test_orden_por_hora(self):
        a = {**_e("tabla", 1), "ts": "2026-10-28T10:00:00"}
        b = {**_e("tabla", 3), "ts": "2026-10-27T10:00:00"}
        self.assertEqual(huecos_de([a, b], "tabla"), 0)   # el ultimo de verdad es el fallo

    def test_simulacro_no_cuenta(self):
        self.assertEqual(huecos_de([_e("tabla", 4, "simulacro")], "tabla"), 0)
        self.assertEqual(huecos_de([_e("tabla", 4, "simulacro"), _e("tabla", 2)], "tabla"), 0)
        self.assertEqual(huecos_de([_e("tabla", 4, "simulacro")] * 3 + [_e("tabla", 3)], "tabla"), 1)
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 1, "simulacro")], "tabla"), 1)

    def test_nivel_sin_acierto_no_cuenta(self):
        """Un «no lo se» en la prueba de nivel no es un intento: ejemplo completo."""
        self.assertEqual(huecos_de([_e("tabla", 1, "nivel")], "tabla"), 0)
        self.assertEqual(huecos_de([_e("tabla", 3), _e("tabla", 1, "nivel")], "tabla"), 1)
        self.assertEqual(huecos_de([_e("tabla", 3, "nivel")], "tabla"), 1)   # un acierto si cuenta

    def test_recorte(self):
        pasos = ["a", "b", "c", "d"]
        self.assertEqual(recortar(pasos, 0), (pasos, []))
        self.assertEqual(recortar(pasos, 1), (["a", "b", "c", HUECO], ["d"]))
        self.assertEqual(recortar(pasos, 2), (["a", "b", HUECO, HUECO], ["c", "d"]))
        # Ejemplos cortos: siempre queda el primer paso.
        self.assertEqual(recortar(["a", "b"], 2), (["a", HUECO], ["b"]))
        self.assertEqual(recortar(["a"], 2), (["a"], []))


class TestHuecosEnSesion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = cargar()
        cls.ejemplos = cargar_ejemplos(fichas=cls.fichas)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ruta = self.tmp / "registro.jsonl"
        self.parches = [
            mock.patch.object(registro, "RUTA", self.ruta),
            mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
            mock.patch.object(sesion, "SIMULACROS", self.tmp / "simulacros"),
            mock.patch.object(practica, "CACHE", self.tmp / ".cache"),
            mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
            mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones"),
        ]
        for p in self.parches:
            p.start()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def _previo(self, tecnica, notas):
        ficha = next(f for f in self.fichas.values() if f.tecnica == tecnica)
        for i, n in enumerate(notas):
            registro.anadir({"ts": registro.ahora().isoformat(), "ficha": ficha.id, "tipo": ficha.tipo,
                             "grupo": ficha.grupo, "tecnica": tecnica, "semilla": 900 + i, "motivo": "nueva",
                             "nota": n, "correcto": n >= 3, "pistas": 0})

    def test_la_respuesta_del_ejemplo_se_acepta_en_todas_las_tecnicas(self):
        for tecnica, ej in self.ejemplos.items():
            with self.subTest(tecnica=tecnica):
                v = ej["variante"]
                self.assertTrue(sesion.comprobar(v, v.respuesta_modelo).correcto)
                self.assertFalse(sesion.comprobar(v, "x^99").correcto)

    def _ejercicio(self, ficha_id, respuesta_ejemplo, vistas=None, motivo="nueva"):
        v = self.fichas[ficha_id].variante(1)
        respuestas = iter(["3", v.respuesta_modelo])
        prompts = []

        def entrada(p):
            prompts.append(p)
            if "Resultado del ejemplo" in p:
                return respuesta_ejemplo
            if "Enter para seguir" in p:
                return ""
            return next(respuestas)

        salida = io.StringIO()
        with mock.patch.object(builtins, "input", entrada), redirect_stdout(salida):
            practica._un_ejercicio(self.fichas, {"ficha": ficha_id, "semilla": 1, "motivo": motivo}, 1, 2, vistas)
        return salida.getvalue(), prompts

    def _lineas(self):
        return self.ruta.read_text(encoding="utf-8").splitlines() if self.ruta.exists() else []

    def test_un_hueco_correcto(self):
        self._previo("tabla", [3])
        ej = self.ejemplos["tabla"]
        texto, _ = self._ejercicio("I01", ej["variante"].respuesta_modelo)
        n = len(ej["pasos"])
        self.assertIn("Ejemplo con huecos (tabla)", texto)
        self.assertIn(f"Paso {n}: {ej['pasos'][-1]}", texto)   # se ensena al final
        self.assertIn("Bien.", texto)
        self.assertLess(texto.index("Ejemplo con huecos"), texto.index("[1/2]"))

    def test_dos_huecos_enter_vacio_y_fallo(self):
        self._previo("tabla", [3, 3])
        ej = self.ejemplos["tabla"]
        texto, _ = self._ejercicio("I01", "")
        self.assertNotIn("Bien.", texto)
        self.assertNotIn("No coincide", texto)
        self.assertIn(f"Paso {len(ej['pasos']) - 1}: {ej['pasos'][-2]}", texto)

    def test_respuesta_mala_se_avisa(self):
        self._previo("tabla", [3])
        texto, _ = self._ejercicio("I01", "x^99")
        self.assertIn("No coincide", texto)

    def test_tres_aciertos_o_mas_ejercicio_en_frio(self):
        self._previo("tabla", [3, 4, 3])
        texto, prompts = self._ejercicio("I01", "")
        self.assertNotIn("Ejemplo con huecos", texto)
        self.assertNotIn("Tecnica nueva", texto)
        self.assertFalse(any("Resultado del ejemplo" in p for p in prompts))

    def test_no_registra_el_ejemplo_y_una_vez_por_tecnica_y_sesion(self):
        self._previo("tabla", [3])
        antes = self._lineas()
        vistas = set()
        t1, _ = self._ejercicio("I01", "", vistas)
        despues = self._lineas()
        self.assertEqual(len(despues), len(antes) + 1)   # solo el ejercicio real
        self.assertEqual(json.loads(despues[-1])["ficha"], "I01")
        t2, _ = self._ejercicio("I02", "", vistas)
        self.assertIn("Ejemplo con huecos", t1)
        self.assertNotIn("Ejemplo con huecos", t2)

    def test_json_con_huecos(self):
        self._previo("tabla", [3])
        ej = self.ejemplos["tabla"]
        pares = [({"ficha": "I01"}, {}), ({"ficha": "I02"}, {})]
        practica._con_ejemplo(self.fichas, pares)
        e = pares[0][1]["ejemplo"]
        self.assertEqual(e["huecos"], 1)
        self.assertEqual(e["pasos_ocultos"], ej["pasos"][-1:])
        self.assertEqual(e["pasos"], ej["pasos"][:-1] + [HUECO])
        self.assertNotIn("ejemplo", pares[1][1])   # una vez por tecnica

    def test_json_completo_sin_huecos_y_sin_ejemplo_si_domina(self):
        pares = [({"ficha": "I01"}, {})]
        practica._con_ejemplo(self.fichas, pares)
        e = pares[0][1]["ejemplo"]
        self.assertNotIn("huecos", e)
        self.assertNotIn(HUECO, e["pasos"])
        self.assertEqual(set(e), {"tecnica", "idea", "enunciado", "pasos", "resultado"})
        self._previo("tabla", [3, 3, 3])
        pares = [({"ficha": "I01"}, {})]
        practica._con_ejemplo(self.fichas, pares)
        self.assertNotIn("ejemplo", pares[0][1])

    def test_cola_json_no_escribe_en_el_registro(self):
        self._previo("tabla", [2])
        antes = self._lineas()
        with redirect_stdout(io.StringIO()):
            practica.main(["cola"])
        self.assertEqual(self._lineas(), antes)

    def test_simulacro_no_ensena_ejemplos(self):
        ex = elegir_examen(date.today())
        if ex is None:
            self.skipTest("sin examen proximo")
        it = iter([""] + ["1"] * 20)   # «1» se lee en cualquier tipo de ficha
        salida = io.StringIO()
        with mock.patch.object(builtins, "input", lambda p: next(it)), redirect_stdout(salida), \
                mock.patch.object(practica, "elegir_examen", lambda dia, nombre=None: ex):
            practica.sesion_simulacro(self.fichas, date.today(), None, git=False)
        self.assertNotIn("Ejemplo con huecos", salida.getvalue())
        self.assertNotIn("Tecnica nueva", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
