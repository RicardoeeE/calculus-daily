"""Capa de servicio (calculo/servicio.py): la sesion sin input() ni print."""
import io
import json
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

import practica
from calculo import registro, servicio, sesion, tutela
from calculo.fichas import cargar
from calculo.servicio import Sesion
from tests.test_verificar import A_MANO, EQUIVALENTES, ERRONEAS

FICHAS = cargar()


class Temporal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache = self.tmp / ".cache"
        self.parches = [
            mock.patch.object(registro, "RUTA", self.tmp / "registro.jsonl"),
            mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
            mock.patch.object(practica, "CACHE", self.cache),
            mock.patch.object(servicio, "CACHE", self.cache),
            mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
            mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones"),
        ]
        for p in self.parches:
            p.start()
        self.s = Sesion(FICHAS, cache=self.cache)

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def json(self, r):
        """Todo lo que devuelve Sesion se puede mandar a la ventana tal cual."""
        return json.loads(json.dumps(r, ensure_ascii=False))


class TestFlujo(Temporal):
    def test_sesion_completa(self):
        c = self.json(self.s.cola(minimo=True))
        self.assertTrue(c["ok"])
        ejercicios = c["ejercicios"]
        self.assertEqual(len(ejercicios), 2)
        self.assertEqual([(e["numero"], e["total"]) for e in ejercicios], [(1, 2), (2, 2)])
        for e in ejercicios:
            self.assertTrue({"enunciado", "tipo", "tecnica", "como_responder", "ficha", "semilla"} <= set(e))
        # La misma cola que da `cola` en modo revisor.
        self.assertEqual([(e["ficha"], e["semilla"]) for e in ejercicios],
                         [(g["ficha"], g["semilla"]) for g in practica.cola_de_hoy(FICHAS, Sesion.hoy(), True)])

        e1, e2 = ejercicios
        v1 = FICHAS[e1["ficha"]].variante(e1["semilla"])
        self.assertTrue(self.json(self.s.mostrar(e1["ficha"], e1["semilla"]))["ok"])
        lec = self.json(self.s.leer(v1.respuesta_modelo, e1["ficha"], e1["semilla"]))
        self.assertTrue(lec["ok"])
        r = self.json(self.s.comprobar(e1["ficha"], e1["semilla"], v1.respuesta_modelo))
        self.assertTrue(r["correcto"])
        self.assertFalse(r["solucion_disponible"])
        r = self.json(self.s.registrar(e1["ficha"], e1["semilla"], 4, v1.respuesta_modelo))
        self.assertEqual((r["ok"], r["ya_registrado"], r["nota"]), (True, False, 3))

        self.s.mostrar(e2["ficha"], e2["semilla"])
        self.assertIn("texto", self.json(self.s.pista(e2["ficha"], e2["semilla"], 1)))
        sol = self.json(self.s.solucion(e2["ficha"], e2["semilla"]))
        self.assertIn("Solucion:", sol["texto"])
        self.assertTrue(self.json(self.s.causa_necesaria(e2["ficha"], e2["semilla"], rendido=True))["necesaria"])
        r = self.json(self.s.registrar(e2["ficha"], e2["semilla"], 2, rendido=True, causa="1"))
        self.assertEqual((r["nota"], r["pistas"]), (1, 4))
        self.assertEqual(registro.leer()[-1]["causa"], tutela.CAUSAS["1"])

        self.assertTrue(self.json(self.s.sensacion(4, "bien"))["ok"])
        self.assertTrue(self.json(self.s.queja("la pista 2 no se entiende"))["ok"])
        with mock.patch.object(sesion.subprocess, "run", side_effect=AssertionError("sin git")):
            cierre = self.json(self.s.cerrar_local())
        self.assertIn("2 ejercicios", cierre["mensaje"])
        self.assertIn("Practica (motor)", (self.tmp / "sesiones.md").read_text(encoding="utf-8"))
        self.assertEqual(self.s.cola(minimo=True)["ejercicios"], [])

    def test_retomar_numera_el_dia(self):
        e1 = self.s.cola()["ejercicios"][0]
        v = FICHAS[e1["ficha"]].variante(e1["semilla"])
        Sesion(FICHAS, cache=self.cache).registrar(e1["ficha"], e1["semilla"], 3, v.respuesta_modelo)
        resto = Sesion(FICHAS, cache=self.cache).cola()["ejercicios"]   # otra instancia: todo esta en disco
        self.assertEqual(len(resto), 4)
        self.assertEqual((resto[0]["numero"], resto[0]["total"]), (2, 5))

    def test_revisor_y_servicio_intercambiables(self):
        with redirect_stdout(io.StringIO()):
            practica.main(["comprobar", "D01", "0", "4x^4"])
        r = self.s.registrar("D01", 0, 3, "4x^3")
        self.assertEqual((r["nota"], r["fallos"]), (2, 1))


class TestSolucionDisponible(Temporal):
    def test_tras_un_fallo(self):
        r = self.s.comprobar("D01", 0, "4x^4")
        self.assertEqual((r["correcto"], r["fallos"], r["solucion_disponible"]), (False, 1, True))
        self.assertTrue(r["diagnostico"] is not None)

    def test_ilegible_no_cuenta(self):
        r = self.s.comprobar("D01", 0, "sen(")
        self.assertTrue(r["error"])
        self.assertFalse(r["solucion_disponible"])

    def test_tras_la_pista_2(self):
        self.assertFalse(self.s.pista("D02", 1, 1)["solucion_disponible"])
        self.assertTrue(self.s.pista("D02", 1, 2)["solucion_disponible"])
        self.assertTrue(self.s.ejercicio("D02", 1)["solucion_disponible"])


class TestIdempotente(Temporal):
    def test_dos_veces(self):
        r1 = self.s.registrar("D01", 0, 3, "4x^3")
        r2 = self.s.registrar("D01", 0, 3, "4x^3")
        self.assertEqual((r1["ya_registrado"], r2["ya_registrado"], r2["ok"]), (False, True, True))
        self.assertEqual(r2["entrada"], r1["entrada"])
        self.assertEqual(len(registro.leer()), 1)

    def test_cuatro_hilos(self):
        barrera, resultados = threading.Barrier(4), []

        def uno():
            s = Sesion(FICHAS, cache=self.cache)
            barrera.wait()
            resultados.append(s.registrar("D01", 0, 3, "4x^3"))

        hilos = [threading.Thread(target=uno) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(registro.leer()), 1)
        self.assertTrue(all(r["ok"] for r in resultados))
        self.assertEqual(sorted(r["ya_registrado"] for r in resultados), [False, True, True, True])


class TestSeguro(Temporal):
    def test_excepcion_a_ok_false_con_log(self):
        r = self.s.pista("NO-EXISTE", 1, 1)
        self.assertEqual(r["ok"], False)
        self.assertIn("NO-EXISTE", r["error"])
        log = (self.cache / "servicio.log").read_text(encoding="utf-8")
        self.assertIn("KeyError", log)
        self.assertIn("pista", log)

    def test_error_inesperado(self):
        with mock.patch.object(servicio, "diagnosticar", side_effect=RuntimeError("roto")):
            r = self.s.comprobar("D01", 0, "4x^4")
        self.assertEqual(r, {"ok": False, "error": "roto"})
        self.assertIn("RuntimeError: roto", (self.cache / "servicio.log").read_text(encoding="utf-8"))

    def test_sin_envolver(self):
        crudo = Sesion(FICHAS, cache=self.cache, seguro=False)
        with self.assertRaises(KeyError):
            crudo.pista("NO-EXISTE", 1, 1)
        with self.assertRaises(KeyError):
            Sesion.pista.sin_envolver(self.s, "NO-EXISTE", 1, 1)
        with self.assertRaises(ValueError):
            crudo.registrar("D01", 0, 9, "4x^3")   # confianza fuera de 1-5


class TestLeer(Temporal):
    def _corpus(self):
        integral = [t for t in A_MANO.values()] + [t for _, t in EQUIVALENTES] + [t for _, t in ERRONEAS]
        casos = [("I01", 1, t) for t in integral]
        casos += [("D01", 0, t) for t in ("4x^3", "-x e^(-x^2/2)", "2/((x-3)^2+4)", "x^x (ln(x)+1)", "sen^2(x)")]
        casos += [(f, 1, t) for f in ("I01", "D01", "AL-CUAD", "PC-CERO", "EX-POLI", "PO-POLI", "DF-POLI",
                                      "T2-CAR-COMP", "T2-GEN-REAL", "T2-OP-XEXP")
                  for t in ("sen(", "x^99", "y", "3, 4", "2±3i", "C1 e^x + C2 e^(-x)", "x y^2", "")]
        for tipo in sorted({f.tipo for f in FICHAS.values()}):
            for f in [f for f in FICHAS.values() if f.tipo == tipo][:4]:
                casos.append((f.id, 1, f.variante(1).respuesta_modelo))
        return casos

    def test_mismo_leido_que_comprobar(self):
        for ficha, semilla, texto in self._corpus():
            with self.subTest(ficha=ficha, texto=texto):
                v = FICHAS[ficha].variante(semilla)
                esperado = sesion.comprobar(v, texto)
                r = self.json(self.s.leer(texto, ficha, semilla))
                self.assertEqual(r["leido"], esperado.leido)
                self.assertEqual(r["error"], esperado.error)
                self.assertEqual(r["ok"], esperado.error is None)
                if r["ok"]:
                    self.assertIsInstance(r["latex"], str)
                self.assertNotIn("correcto", r)   # solo lee: no dice si esta bien

    def test_no_anota_nada(self):
        self.s.leer("4x^4", "D01", 0)
        self.assertEqual(self.s.ejercicio("D01", 0)["fallos"], 0)


class TestSegundos(Temporal):
    def test_medidos_por_el_motor(self):
        with mock.patch.object(servicio, "reloj", return_value=1000.0):
            self.s.mostrar("D01", 0)
        with mock.patch.object(servicio, "reloj", return_value=1042.4):
            r = self.s.registrar("D01", 0, 3, "4x^3")
        self.assertEqual(r["segundos"], 42)
        self.assertEqual(registro.leer()[-1]["segundos"], 42)

    def test_tope_de_20_minutos(self):
        with mock.patch.object(servicio, "reloj", return_value=1000.0):
            self.s.mostrar("D01", 0)
        with mock.patch.object(servicio, "reloj", return_value=1000.0 + 20 * 60 + 1):
            r = self.s.registrar("D01", 0, 3, "4x^3")
        self.assertIsNone(r["segundos"])

    def test_sin_mostrar_no_hay_segundos(self):
        self.assertIsNone(self.s.registrar("D01", 0, 3, "4x^3")["segundos"])

    def test_los_de_fuera_mandan(self):
        self.assertEqual(self.s.registrar("D01", 0, 3, "4x^3", segundos=77)["segundos"], 77)


class TestCambioDeDia(Temporal):
    def test_el_dia_se_calcula_en_cada_llamada(self):
        hoy = registro.ahora().replace(hour=23, minute=59)
        manana = hoy + timedelta(days=1)
        with mock.patch.object(registro, "ahora", return_value=hoy):
            self.assertEqual(self.s.cola()["dia"], hoy.date().isoformat())
            self.s.mostrar("D01", 0)
            self.s.pista("D01", 0, 3)
            self.assertFalse(self.s.registrar("D01", 0, 3, "4x^3")["ya_registrado"])
        with mock.patch.object(registro, "ahora", return_value=manana):
            self.assertEqual(self.s.cola()["dia"], manana.date().isoformat())
            self.assertEqual(self.s.ejercicio("D01", 0)["pistas_vistas"], 0)   # las pistas de ayer no cuentan
            r = self.s.registrar("D01", 0, 3, "4x^3")
        self.assertFalse(r["ya_registrado"])   # es otro dia: vale
        self.assertIsNone(r["segundos"])       # el reloj se puso ayer
        self.assertEqual([registro.fecha(e) for e in registro.leer()], [hoy.date(), manana.date()])


class TestSincronizar(Temporal):
    def test_git_colgado_no_cuelga(self):
        self.s.registrar("D01", 0, 3, "4x^3")
        colgado = subprocess.TimeoutExpired(["git"], 60)
        with mock.patch.object(sesion.subprocess, "run", side_effect=colgado) as run:
            inicio = time.monotonic()
            r = self.json(self.s.sincronizar(timeout=60))
        self.assertLess(time.monotonic() - inicio, 5)
        self.assertEqual(r["ok"], False)
        self.assertIn("se agoto el tiempo", r["mensaje"])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 60)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GCM_INTERACTIVE"], "never")   # el gestor de credenciales no pregunta

    def test_sin_intentos_no_llama_a_git(self):
        with mock.patch.object(sesion.subprocess, "run") as run:
            r = self.s.sincronizar()
        self.assertTrue(r["ok"])
        run.assert_not_called()

    def test_cerrar_de_siempre_igual(self):
        """`practica.py cerrar` sigue siendo diario + git sin tope (lo de antes)."""
        self.s.registrar("D01", 0, 3, "4x^3")
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(sesion.subprocess, "run", return_value=ok) as run:
            texto = sesion.cerrar(Sesion.hoy(), FICHAS)
        self.assertIn("1 ejercicio,", texto)
        self.assertIn("git:", texto)
        self.assertIsNone(run.call_args.kwargs["timeout"])
        self.assertIsNone(run.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
