"""Ayudas de la ventana («Hoy solo 2», «No se por donde empezar»...), con la API sin abrirla."""
import re
from pathlib import Path
from unittest import mock

from calculo import registro, rutas, servicio, ventana
from calculo.latex import trozos
from tests.test_servicio import FICHAS
from tests.test_ventana import ConLector

APP = (rutas.INTERFAZ / "app.js").read_text(encoding="utf-8")
HTML = (rutas.INTERFAZ / "index.html").read_text(encoding="utf-8")


class TestHoySolo2(ConLector):
    def test_minimo_da_la_cola_minima(self):
        self.assertFalse(self.api.inicio()["minimo"])
        normal = self.api.cola()["ejercicios"]
        self.assertEqual(len(normal), 5)
        r = self.api.minimo()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["ejercicios"]), 2)
        self.assertEqual({e["total"] for e in r["ejercicios"]}, {2})
        self.assertTrue(self.api.inicio()["minimo"])
        # La misma cola que `ventana --minimo` y que `cola --minimo` en modo revisor.
        self.assertEqual([(e["ficha"], e["semilla"]) for e in r["ejercicios"]],
                         [(g["ficha"], g["semilla"]) for g in servicio.cola_guardada(self.cache, FICHAS,
                                                                                     self.api._s.hoy(), True)])

    def test_en_la_interfaz(self):
        self.assertIn('id="solo-dos"', HTML)
        self.assertIn('llamar("minimo")', APP)


class TestNoSePorDondeEmpezar(ConLector):
    def test_ejemplo_completo_y_cuenta_como_pista_2(self):
        r = self.api.sin_saber_empezar("I01", 0)
        self.assertTrue(r["ok"])
        self.assertIsNotNone(r["ejemplo"])
        self.assertNotIn("huecos", r["ejemplo"])      # completo, aunque tocaran huecos
        self.assertEqual(r["pistas_vistas"], 2)
        self.assertTrue(r["solucion_disponible"])
        d =self.api._s.ejercicio("I01", 0)
        self.assertTrue(d["solucion_disponible"])
        self.assertTrue(self.api.causa_necesaria("I01", 0, False, False)["necesaria"])
        v = FICHAS["I01"].variante(0)
        r = self.api.registrar("I01", 0, 3, v.respuesta_modelo, False, "1", False)
        self.assertEqual((r["nota"], r["pistas"]), (2, 2))

    def test_sin_ejemplo_da_las_pistas_1_y_2(self):
        with mock.patch.object(servicio, "cargar_ejemplos", return_value={}):
            s = servicio.Sesion(FICHAS, cache=self.cache, seguro=True)
            api = ventana.API(s, cache=self.cache, git=False, lector=self.lector)
            r = api.sin_saber_empezar("D01", 0)
        self.assertIsNone(r["ejemplo"])
        v = FICHAS["D01"].variante(0)
        self.assertEqual(r["pistas"], [v.pista(1), v.pista(2)])
        self.assertEqual(len(r["pistas_trozos"]), 2)

    def test_boton_visible_antes_de_responder(self):
        self.assertIn('id="no-se"', HTML)
        self.assertIn('$("no-se").hidden = !!estado.ultima || estado.fallos > 0 || estado.pistas >= 2', APP)


class TestSolucionConfirmadaYMemoria(ConLector):
    def test_practicar_solo_despues_de_registrar(self):
        v = FICHAS["D01"].variante(0)
        r = self.api.practicar("D01", 0, v.respuesta_modelo)
        self.assertFalse(r["ok"])   # antes de registrar no sirve para tantear
        self.api.pista("D01", 0, 2)
        self.api.solucion("D01", 0)
        self.api.registrar("D01", 0, 2, None, True, "1", False)
        antes = registro.leer()
        r = self.api.practicar("D01", 0, v.respuesta_modelo)
        self.assertTrue(r["ok"] and r["correcto"])
        self.assertFalse(self.api.practicar("D01", 0, "x^99")["correcto"])
        self.assertEqual(registro.leer(), antes)    # sin nota ni registro
        self.assertEqual(self.api._s.ejercicio("D01", 0)["fallos"], 0)

    def test_confirmacion_en_la_interfaz(self):
        self.assertIn("¿Seguro? Cuenta como no sabido.", HTML)
        self.assertIn('$("ver-solucion").addEventListener("click", pedirSolucion)', APP)
        self.assertIn('id="reescribir"', HTML)


class TestFormulas(ConLector):
    def test_trozos(self):
        # El conversor escribe lo que pone el texto (el «·» incluido), cada
        # formula lleva su `fuente` y el punto final ya no se pierde.
        self.assertEqual(trozos("4·x^(4-1)."), [{"tex": r"4 \cdot x^{4 - 1}", "fuente": "4·x^(4-1)"},
                                                {"texto": "."}])
        self.assertEqual(trozos("Potencia de x."), [{"texto": "Potencia de x."}])
        t = trozos("Solucion: x^2/2 + C")
        self.assertEqual(t[0], {"texto": "Solucion: "})
        self.assertEqual(t[1]["tex"], r"\frac{x^{2}}{2} + C")
        self.assertEqual(trozos("Solucion: h = 1, k = 9")[1], {"tex": r"h = 1,\; k = 9", "fuente": "h = 1, k = 9"})
        self.assertEqual(trozos("a\nb"), [{"texto": "a\nb"}])
        hostil = "<img src=x onerror=alert(1)>"
        self.assertEqual(trozos(hostil), [{"texto": hostil}])   # va con textContent

    def test_pista_solucion_y_diagnostico_llevan_trozos(self):
        r = self.api.pista("DC-SEN", 0, 3)   # «Derivada de a x^2: 2·a·x.» (la de D01 ya no da formula)
        self.assertTrue(any("tex" in t for t in r["trozos"]))
        r = self.api.comprobar("I05", 0, "x^2") if "I05" in FICHAS else self.api.comprobar("D01", 0, "x^2")
        self.assertEqual(len(r["diagnostico_trozos"]), len(r["diagnostico"]))
        self.api.pista("D01", 0, 2)          # la solucion solo se ofrece tras la pista 2
        sol = self.api.solucion("D01", 0)
        self.assertTrue(any("tex" in t for t in sol["trozos"]))

    def test_sin_innerhtml(self):
        self.assertNotRegex(APP, r"\.innerHTML|insertAdjacentHTML|outerHTML")
        self.assertIn("createTextNode", APP)


class TestSalirConLaSubidaVisible(ConLector):
    def test_preparar_salida_sube_y_dice_sin_red(self):
        api = ventana.API(self.api._s, cache=self.cache, git=True, lector=self.lector)
        self.assertEqual(api.preparar_salida()["estado"], "nada")   # sin registros, nada
        api.registrar("D01", 0, 3, "4x^3", False, None, False)
        with mock.patch.object(servicio.Sesion, "sincronizar",
                               return_value={"ok": False, "mensaje": "git: commit hecho. Sin red: se sube la proxima vez."}):
            r = api.preparar_salida()
            self.assertIn(r["estado"], ("subiendo", "sin_red"))
            api._hilo_subida.join(5)
        self.assertEqual(api.estado_subida()["estado"], "sin_red")
        self.assertTrue((self.tmp / "sesiones.md").exists())   # el diario, antes de subir
        self.assertIsNotNone(api._hilo_subida)
        self.assertEqual(api.despues(), "git: commit hecho. Sin red: se sube la proxima vez.")

    def test_choque_no_es_sin_red(self):
        api = ventana.API(self.api._s, cache=self.cache, git=True, lector=self.lector)
        api.registrar("D01", 0, 3, "4x^3", False, None, False)
        with mock.patch.object(servicio.Sesion, "sincronizar",
                               return_value={"ok": False, "mensaje": "git: commit hecho, pero lo de otro equipo choca"}):
            api.terminar()
            api._hilo_subida.join(5)
        self.assertEqual(api.estado_subida()["estado"], "revisar")


class TestBarraDeProgreso(ConLector):
    def test_total_menos_pendientes(self):
        """Con un ejercicio hecho en medio (por la terminal), la barra
        contaba desde la posicion del primero pendiente."""
        self.assertIn("total - cola.length", APP)
        c = self.api.cola()["ejercicios"]
        segundo = c[1]
        v = FICHAS[segundo["ficha"]].variante(segundo["semilla"])
        self.api._s.registrar(segundo["ficha"], segundo["semilla"], 3, v.respuesta_modelo)
        resto = self.api.cola()["ejercicios"]
        total = resto[0]["total"]
        self.assertEqual((total, len(resto), resto[0]["numero"]), (5, 4, 1))
        # total - pendientes = 1 hecho (20 %), no numero - 1 = 0.
        self.assertEqual(round(100 * (total - len(resto)) / total), 20)


class TestPruebaLimpia(ConLector):
    def test_el_humo_borra_su_carpeta_si_sale_bien(self):
        codigo = Path(ventana.__file__).read_text(encoding="utf-8")
        self.assertRegex(codigo, re.compile(r"if bien:.*\n\s*shutil\.rmtree\(temporal", re.M))
