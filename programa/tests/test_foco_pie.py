"""Foco neutro y pie segun la pantalla."""
import re
import unittest
from pathlib import Path

INTERFAZ = Path(__file__).resolve().parent.parent / "interfaz"


class TestFocoNeutro(unittest.TestCase):
    """Ninguna opcion debe parecer elegida, ni marcarse con un Enter de mas."""

    def setUp(self):
        self.js = (INTERFAZ / "app.js").read_text(encoding="utf-8")
        self.html = (INTERFAZ / "index.html").read_text(encoding="utf-8")

    def test_las_tarjetas_de_opciones_pueden_recibir_el_foco(self):
        for bloque in ("bloque-confianza", "bloque-causa", "final-preguntas"):
            self.assertRegex(self.html, rf'id="{bloque}"[^>]*tabindex="-1"')
            self.assertIn(f'$("{bloque}").focus()', self.js.replace('$("bloque-confianza")).focus()', '$("bloque-confianza").focus()'))

    def test_no_se_enfoca_la_primera_opcion(self):
        for bloque in ("bloque-confianza", "causas", "final-preguntas"):
            self.assertNotIn(f'$("{bloque}").querySelector("button").focus()', self.js)


class TestPie(unittest.TestCase):
    def setUp(self):
        js = (INTERFAZ / "app.js").read_text(encoding="utf-8")
        bloque = re.search(r"const ATAJOS = \{(.*?)\};", js, re.S)[1]
        self.atajos = dict(re.findall(r'(\w+): "([^"]*)"', bloque))

    def test_cada_pantalla_dice_solo_sus_teclas(self):
        self.assertIn("comprobar", self.atajos["respuesta"])
        self.assertIn("1 a 5", self.atajos["confianza"])
        self.assertIn("1 a 4", self.atajos["causa"])
        for fase in ("final", "resumen", "vacia", "confianza", "causa"):
            self.assertNotIn("comprobar", self.atajos[fase])
        self.assertNotIn("confianza", self.atajos["final"])


if __name__ == "__main__":
    unittest.main()
