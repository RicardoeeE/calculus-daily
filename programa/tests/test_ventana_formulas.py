"""Toda formula de la ventana llega en trozos (texto | tex) desde Python."""
from pathlib import Path

from calculo import rutas, servicio
from calculo.huecos import HUECO
from tests.test_latex import reconstruir
from tests.test_servicio import FICHAS
from tests.test_ventana import ConLector

APP = (rutas.INTERFAZ / "app.js").read_text(encoding="utf-8")
HTML = (rutas.INTERFAZ / "index.html").read_text(encoding="utf-8")


def tiene_tex(partes):
    return any("tex" in p for p in partes or [])


class TestEjemploEnTrozos(ConLector):
    def test_ejemplo_completo_de_racionales(self):
        """El paso de fracciones simples: «Separa: 1/((x - 1)(x + 1)) = ...» con \\frac."""
        r = self.api.sin_saber_empezar("R-DOS", 0)
        ej = r["ejemplo"]
        self.assertEqual(len(ej["pasos_trozos"]), len(ej["pasos"]))
        primero = ej["pasos_trozos"][0]
        self.assertEqual(primero[0], {"texto": "Separa: "})
        self.assertIn(r"\frac{1}{(x - 1) (x + 1)}", primero[1]["tex"])
        for plano, partes in zip(ej["pasos"], ej["pasos_trozos"]):
            self.assertEqual(reconstruir(partes), plano)       # nada se pierde
        self.assertTrue(tiene_tex(ej["resultado_trozos"]))
        self.assertTrue(ej["enunciado_latex"].startswith(r"\int"))
        self.assertTrue(ej["idea_trozos"])

    def test_ejemplo_con_huecos(self):
        cargado = self.api._s.ejemplo_cargado("racionales")
        ej = servicio.ejemplo_json(cargado, 1)
        self.api._ejemplo_trozos(ej)
        self.assertEqual(ej["pasos"][-1], HUECO)
        self.assertEqual(ej["pasos_trozos"][-1], [{"texto": HUECO}])
        self.assertEqual(len(ej["ocultos_trozos"]), 1)
        self.assertTrue(tiene_tex(ej["ocultos_trozos"][0]))
        self.assertEqual(reconstruir(ej["ocultos_trozos"][0]), ej["pasos_ocultos"][0])

    def test_la_cola_lleva_los_trozos(self):
        for e in self.api.cola()["ejercicios"]:
            with self.subTest(ficha=e["ficha"]):
                self.assertIn("como_responder_trozos", e)
                if e["enunciado_latex"]:
                    self.assertIsNone(e["enunciado_trozos"])
                else:
                    self.assertEqual(reconstruir(e["enunciado_trozos"]), e["enunciado"])
                if e.get("ejemplo"):
                    self.assertIn("pasos_trozos", e["ejemplo"])


class TestEnunciadosYMensajes(ConLector):
    def test_enunciados_sin_formula_propia(self):
        """Algebra, EDOs y calculos (sin enunciado_latex): el enunciado entero en trozos."""
        for fid in ("AL-FRAC", "T2-GEN-REAL", "T2-WR-EXP", "AL-SIS2"):
            d = self.api._s.ejercicio(fid, 0)
            self.assertIsNone(d["enunciado_latex"])
            self.api._enunciado_trozos(d)
            with self.subTest(ficha=fid):
                self.assertTrue(tiene_tex(d["enunciado_trozos"]))
                self.assertEqual(reconstruir(d["enunciado_trozos"]), d["enunciado"])

    def test_instruccion_de_las_exactas(self):
        d = self.api._s.ejercicio("EX-POLI", 0)
        from calculo.ventana import _partes_enunciado
        d["enunciado_antes"], d["enunciado_despues"] = _partes_enunciado(d["enunciado"])
        self.api._enunciado_trozos(d)
        self.assertTrue(tiene_tex(d["enunciado_despues_trozos"]))   # «Escribe ∂M/∂y, ∂N/∂x»

    def test_he_leido_en_trozos(self):
        v = FICHAS["I01"].variante(0)
        r = self.api.comprobar("I01", 0, "x^2")
        self.assertTrue(r["ok"])
        self.assertEqual(reconstruir(r["leido_trozos"]), r["leido"])
        self.assertEqual(len(r["avisos_trozos"]), len(r["avisos"]))
        self.assertTrue(v)


class TestInterfaz(ConLector):
    def test_js_solo_pinta(self):
        self.assertNotIn("textoConFormulas", APP)           # el JS ya no parte texto
        self.assertIn("throwOnError: true", APP)            # lo que KaTeX no entienda, en monoespaciada
        self.assertIn('code.className = "mono"', APP)
        self.assertNotRegex(APP, r"\.innerHTML|insertAdjacentHTML|outerHTML")
        for campo in ("pasos_trozos", "ocultos_trozos", "idea_trozos", "resultado_trozos",
                      "enunciado_trozos", "leido_trozos", "como_responder_trozos"):
            self.assertIn(campo, APP)
        self.assertIn('id="ejemplo-enunciado-antes"', HTML)
