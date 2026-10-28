"""Ventana: la clase API llamada directamente, sin abrir ninguna ventana.

El humo real (`practica.py ventana --prueba`) abre la ventana: solo se ejecuta
con la variable de entorno VENTANA_HUMO=1 y si hay pywebview y WebView2."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import practica
from calculo import lector, registro, rutas, servicio, sesion, ventana
from calculo.doctor import version_webview2
from calculo.lector import Lector
from tests.test_servicio import FICHAS, Temporal

RAIZ = rutas.RAIZ


class ConLector(Temporal):
    """Un solo proceso lector para toda la clase (arrancarlo cuesta ~1 s)."""
    @classmethod
    def setUpClass(cls):
        cls.lector = Lector(tempfile.mkdtemp())
        cls.lector.preparar()

    @classmethod
    def tearDownClass(cls):
        cls.lector.cerrar()

    def setUp(self):
        super().setUp()
        self.api = ventana.API(servicio.Sesion(FICHAS, cache=self.cache, seguro=True), cache=self.cache,
                               git=False, lector=self.lector)


class TestFlujo(ConLector):
    def test_un_ejercicio_completo(self):
        ini = self.api.inicio()
        self.assertTrue(ini["ok"])
        self.assertEqual([c["clave"] for c in ini["causas"]], ["1", "2", "3", "4"])
        c = self.api.cola()
        self.assertTrue(c["ok"])
        e = c["ejercicios"][0]
        self.assertEqual((e["numero"], e["total"]), (1, 5))
        self.assertIn("grafica", e)
        self.assertFalse(e["solucion_disponible"])
        v = FICHAS[e["ficha"]].variante(e["semilla"])
        self.assertTrue(self.api.mostrar(e["ficha"], e["semilla"])["ok"])
        lec = self.api.leer(v.respuesta_modelo, e["ficha"], e["semilla"])
        self.assertTrue(lec["ok"])
        self.assertNotIn("correcto", lec)         # vista previa neutra
        self.assertEqual(lec["leido"], sesion.comprobar(v, v.respuesta_modelo).leido)
        r = self.api.comprobar(e["ficha"], e["semilla"], v.respuesta_modelo)
        self.assertTrue(r["correcto"])
        self.assertFalse(self.api.causa_necesaria(e["ficha"], e["semilla"], False, False)["necesaria"])
        r = self.api.registrar(e["ficha"], e["semilla"], 4, v.respuesta_modelo, False, None, False)
        self.assertEqual((r["ok"], r["ya_registrado"], r["nota"]), (True, False, 3))
        self.assertRegex(r["proximo_texto"], r"^\d\d/\d\d$")
        self.assertNotIn("entrada", r)
        json.dumps(r)
        resto = self.api.cola()["ejercicios"]
        self.assertEqual((len(resto), resto[0]["numero"]), (4, 2))

    def test_fallo_pista_solucion_y_causa(self):
        r = self.api.comprobar("D01", 0, "4x^4")
        self.assertEqual((r["correcto"], r["fallos"]), (False, 1))
        self.assertIsInstance(r["diagnostico"], list)
        self.assertTrue(self.api.pista("D01", 0, 1)["ok"])
        sol = self.api.solucion("D01", 0)
        self.assertTrue(sol["ok"] and sol["rendido"])
        self.assertTrue(self.api.causa_necesaria("D01", 0, True, False)["necesaria"])
        r = self.api.registrar("D01", 0, 2, None, True, "2", False)
        self.assertEqual((r["nota"], r["pistas"], r["fallos"]), (1, 4, 1))

    def test_reclamo_sin_causa(self):
        self.api.comprobar("D01", 0, "4x^4")
        self.assertFalse(self.api.causa_necesaria("D01", 0, False, True)["necesaria"])
        r = self.api.registrar("D01", 0, 3, "4x^4", False, None, True)
        self.assertTrue(r["ok"])
        self.assertTrue(registro.leer()[-1].get("reclamo"))

    def test_ejemplo_con_huecos(self):
        tecnica = next(iter(servicio.cargar_ejemplos(fichas=FICHAS)))
        ej = servicio.cargar_ejemplos(fichas=FICHAS)[tecnica]
        r = self.api.comprobar_ejemplo(tecnica, ej["variante"].respuesta_modelo)
        self.assertTrue(r["correcto"])
        self.assertEqual(registro.leer(), [])    # sin nota ni registro

    def test_partes_del_enunciado(self):
        self.assertEqual(ventana._partes_enunciado("Ecuacion caracteristica: r^2 - 1 = 0.  Escribe las raices"),
                         ("Ecuacion caracteristica:", "Escribe las raices"))
        self.assertEqual(ventana._partes_enunciado("∫ x dx"), ("", ""))

    def test_solo_metodos_publicos(self):
        """pywebview expone a JavaScript todo lo publico: solo metodos."""
        for nombre in dir(self.api):
            if not nombre.startswith("_"):
                self.assertTrue(callable(getattr(self.api, nombre)), nombre)


class TestSolucionOculta(ConLector):
    def test_hasta_la_pista_2(self):
        r = self.api.solucion("D02", 1)
        self.assertFalse(r["ok"])
        self.assertEqual(registro.leer(), [])
        self.assertFalse(self.api.pista("D02", 1, 1)["solucion_disponible"])
        self.assertFalse(self.api.solucion("D02", 1)["ok"])
        self.assertTrue(self.api.pista("D02", 1, 2)["solucion_disponible"])
        self.assertTrue(self.api.solucion("D02", 1)["ok"])

    def test_tras_un_fallo(self):
        self.assertFalse(self.api.solucion("D01", 0)["ok"])
        self.assertTrue(self.api.comprobar("D01", 0, "4x^4")["solucion_disponible"])
        self.assertTrue(self.api.solucion("D01", 0)["ok"])

    def test_pista_4_no_en_la_ventana(self):
        r = self.api.pista("D01", 0, 4)
        self.assertFalse(r["ok"])
        self.assertEqual(self.api._s.ejercicio("D01", 0)["pistas_vistas"], 0)

    def test_ilegible_no_la_destapa(self):
        r = self.api.comprobar("D01", 0, "sen(")
        self.assertTrue(r["error"])
        self.assertFalse(self.api.solucion("D01", 0)["ok"])


class TestIdempotente(ConLector):
    def test_dos_registros_una_linea(self):
        r1 = self.api.registrar("D01", 0, 3, "4x^3", False, None, False)
        r2 = self.api.registrar("D01", 0, 3, "4x^3", False, None, False)
        self.assertEqual((r1["ya_registrado"], r2["ya_registrado"], r2["ok"]), (False, True, True))
        self.assertEqual(len(registro.leer()), 1)


class TestCerrar(ConLector):
    def test_closing_con_registros_escribe_el_diario(self):
        self.api.registrar("D01", 0, 3, "4x^3", False, None, False)
        diario = self.tmp / "sesiones.md"
        self.assertFalse(diario.exists())
        with mock.patch.object(sesion.subprocess, "run", side_effect=AssertionError("sin git")):
            self.assertTrue(self.api.al_cerrar())
        self.assertIn("<!-- motor", diario.read_text(encoding="utf-8"))

    def test_closing_sin_registros_no_escribe(self):
        self.assertFalse(self.api.al_cerrar())
        self.assertFalse((self.tmp / "sesiones.md").exists())

    def test_terminar_sin_git(self):
        self.api.registrar("D01", 0, 3, "4x^3", False, None, False)
        r = self.api.terminar()
        self.assertEqual((r["ok"], r["ejercicios"], r["subida"]["estado"]), (True, 1, "local"))
        self.assertIn("1 ejercicio", r["mensaje"])
        self.assertEqual(self.api.estado_subida()["estado"], "local")

    def test_terminar_sube_en_un_hilo(self):
        api = ventana.API(self.api._s, cache=self.cache, git=True, lector=self.lector)
        api.registrar("D01", 0, 3, "4x^3", False, None, False)
        with mock.patch.object(servicio.Sesion, "sincronizar",
                               side_effect=lambda *a, **k: (time.sleep(0.2), {"ok": True, "mensaje": "git: subido"})[1]):
            r = api.terminar()
            self.assertEqual(r["subida"]["estado"], "subiendo")   # el diario ya esta; git sigue aparte
            self.assertTrue((self.tmp / "sesiones.md").exists())
            api._hilo_subida.join(5)
        self.assertEqual(api.estado_subida()["estado"], "subido")

    def test_sin_red_se_dice(self):
        api = ventana.API(self.api._s, cache=self.cache, git=True, lector=self.lector)
        api.registrar("D01", 0, 3, "4x^3", False, None, False)
        with mock.patch.object(servicio.Sesion, "sincronizar",
                               return_value={"ok": False, "mensaje": "git: se agoto el tiempo"}):
            api.terminar()
            api._hilo_subida.join(5)
        self.assertEqual(api.estado_subida()["estado"], "sin_red")
        self.assertIn("sincronizar", (self.cache / "servicio.log").read_text(encoding="utf-8"))


class TestErrores(ConLector):
    def test_ok_false_al_log(self):
        r = self.api.mostrar("NO-EXISTE", 1)
        self.assertFalse(r["ok"])
        self.assertIn("NO-EXISTE", (self.cache / "servicio.log").read_text(encoding="utf-8"))

    def test_excepcion_de_la_api(self):
        r = self.api.registrar("D01", "x", 3, "4x^3", False, None, False)
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"])

    def test_lectura_ilegible_no_va_al_log(self):
        r = self.api.leer("sen(", "D01", 0)
        self.assertFalse(r["ok"])
        self.assertNotIn("_lectura", r)
        self.assertFalse((self.cache / "servicio.log").exists())

    def test_error_de_javascript(self):
        self.api.anotar_error("TypeError: x is undefined")
        self.assertIn("js: TypeError", (self.cache / "servicio.log").read_text(encoding="utf-8"))


class TestLecturaHostil(ConLector):
    def test_responde_a_tiempo(self):
        for texto in ("9**9**9**9", "9^9^9^9"):
            with self.subTest(texto=texto):
                t = time.monotonic()
                r = self.api.leer(texto, "D01", 0)
                self.assertLess(time.monotonic() - t, lector.TOPE + 2)
                self.assertFalse(r["ok"])
                self.assertTrue(r.get("tope"))
        r = self.api.leer("4x^3", "D01", 0)   # el lector se ha vuelto a arrancar
        self.assertEqual((r["ok"], r["leido"]), (True, sesion.comprobar(FICHAS["D01"].variante(0), "4x^3").leido))

    def test_comprobar_hostil_no_cuelga_ni_cuenta(self):
        t = time.monotonic()
        r = self.api.comprobar("D01", 0, "9**9**9**9")
        self.assertLess(time.monotonic() - t, lector.TOPE + 4)
        self.assertTrue(r["error"])
        self.assertEqual(self.api._s.ejercicio("D01", 0)["fallos"], 0)

    def test_limite_de_longitud(self):
        r = self.api.leer("x+" * 150, "D01", 0)
        self.assertFalse(r["ok"])
        self.assertIn("demasiado larga", r["error"])
        r = self.s.leer("x+" * 150, "D01", 0)
        self.assertIn("demasiado larga", r["error"])

    def test_avisos_de_ambiguedad(self):
        self.assertEqual(len(self.api.leer("1/2x", "D01", 0)["avisos"]), 1)
        self.assertEqual(len(self.api.leer("e^2x", "D01", 0)["avisos"]), 1)
        self.assertEqual(self.api.leer("x/2", "D01", 0)["avisos"], [])
        self.assertEqual(self.api.leer("e^(2x)", "D01", 0)["avisos"], [])


class TestInstanciaUnica(Temporal):
    def setUp(self):
        super().setUp()
        self.cache.mkdir(parents=True, exist_ok=True)

    def test_otra_viva_no_deja(self):
        otro = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            registro.escribir_json(self.cache / "ventana.pid",
                                   {"pid": otro.pid, "inicio": ventana._inicio_proceso(otro.pid)})
            self.assertFalse(ventana.tomar_instancia(self.cache))
        finally:
            otro.kill()
            otro.wait()
        self.assertTrue(ventana.tomar_instancia(self.cache))   # muerta: el cerrojo se recupera

    def test_pid_reusado_no_bloquea(self):
        registro.escribir_json(self.cache / "ventana.pid", {"pid": os.getppid() or 4, "inicio": 1})
        self.assertTrue(ventana.tomar_instancia(self.cache))

    def test_soltar(self):
        self.assertTrue(ventana.tomar_instancia(self.cache))
        ventana.soltar_instancia(self.cache)
        self.assertFalse((self.cache / "ventana.pid").exists())

    def test_segunda_ventana_sale_con_0(self):
        otro = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            registro.escribir_json(self.cache / "ventana.pid",
                                   {"pid": otro.pid, "inicio": ventana._inicio_proceso(otro.pid)})
            salida = []
            with mock.patch.dict(sys.modules, {"webview": mock.MagicMock()}), \
                    mock.patch.object(ventana, "version_webview2", return_value="1.0"):
                self.assertEqual(ventana.abrir(salida=salida.append), 0)
            self.assertIn("Ya hay una ventana", salida[0])
        finally:
            otro.kill()
            otro.wait()


class TestSinVentana(Temporal):
    def test_sin_pywebview_codigo_3(self):
        salida = []
        with mock.patch.dict(sys.modules, {"webview": None}):   # import webview -> ImportError
            self.assertEqual(ventana.abrir(salida=salida.append), ventana.SIN_VENTANA)
        self.assertIn("terminal", salida[0])

    def test_sin_webview2_codigo_3(self):
        with mock.patch.dict(sys.modules, {"webview": mock.MagicMock()}), \
                mock.patch.object(ventana, "version_webview2", return_value=None):
            self.assertEqual(ventana.abrir(salida=lambda _: None), ventana.SIN_VENTANA)

    def test_fallo_antes_de_mostrar_codigo_3(self):
        falso = mock.MagicMock()
        falso.start.side_effect = RuntimeError("WebView2 no arranca")
        cache = self.cache
        with mock.patch.dict(sys.modules, {"webview": falso}), \
                mock.patch.object(ventana, "version_webview2", return_value="1.0"), \
                mock.patch.object(ventana, "Lector", return_value=mock.MagicMock()):
            self.assertEqual(ventana.abrir(salida=lambda _: None), ventana.SIN_VENTANA)
        self.assertFalse((cache / "ventana.pid").exists())   # no deja el cerrojo puesto
        self.assertIn("WebView2 no arranca", (cache / "servicio.log").read_text(encoding="utf-8"))

    def test_practica_ventana_sale_con_3(self):
        with mock.patch.dict(sys.modules, {"webview": None}), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as fin:
                practica.main(["ventana"])
        self.assertEqual(fin.exception.code, 3)


class TestPracticarBat(unittest.TestCase):
    def test_respaldo_a_la_terminal(self):
        datos = (RAIZ / "Practicar.bat").read_bytes()
        self.assertEqual(datos.count(b"\n"), datos.count(b"\r\n"))   # CRLF
        texto = datos.decode("utf-8")
        self.assertIn("chcp 65001 >nul <nul", texto)
        self.assertIn("requirements-ventana.txt", texto)
        # La ventana va con pythonw y desacoplada; el respaldo lo abre ella (Terminal.bat)
        self.assertIn(r'start "" "%PYW%" programa\practica.py ventana --respaldo-terminal', texto)
        self.assertIn("goto terminal", texto[:texto.index(":abrir_ventana")])   # sin pywebview: aqui mismo
        self.assertIn("practica.py hoy", texto[texto.index(":terminal"):])

    def test_pywebview_fijado(self):
        lineas = (rutas.PROGRAMA / "requirements-ventana.txt").read_text(encoding="utf-8").split()
        self.assertEqual(lineas, ["pywebview==6.2.1"])
        self.assertNotIn("only-binary", (RAIZ / "Practicar.bat").read_text(encoding="utf-8"))

    def test_katex_local(self):
        k = rutas.INTERFAZ / "katex"
        self.assertTrue((k / "katex.min.js").exists() and (k / "katex.min.css").exists()
                        and (k / "LICENSE").exists())
        self.assertGreaterEqual(len(list((k / "fonts").glob("*.woff2"))), 20)
        html = (rutas.INTERFAZ / "index.html").read_text(encoding="utf-8")
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("http://", html.replace("http-equiv", ""))
        self.assertNotIn("https://", html)


@unittest.skipUnless(os.environ.get("VENTANA_HUMO") == "1", "humo real: VENTANA_HUMO=1 para abrir la ventana")
class TestHumoReal(unittest.TestCase):
    def test_recorrido(self):
        if ventana.version_webview2() is None:
            self.skipTest("sin WebView2")
        try:
            import webview  # noqa: F401
        except ImportError:
            self.skipTest("sin pywebview")
        r = subprocess.run([sys.executable, "-B", "practica.py", "ventana", "--prueba"], cwd=rutas.PROGRAMA,
                           capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
