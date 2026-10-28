"""Sesion completa de principio a fin, en una carpeta temporal y sin git."""
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


class TestSesionCompleta(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.parches = [
            mock.patch.object(registro, "RUTA", self.tmp / "registro.jsonl"),
            mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
            mock.patch.object(practica, "CACHE", self.tmp / ".cache"),
            mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
            mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones"),
        ]
        for p in self.parches:
            p.start()
        self.fichas = cargar()
        self.dia = date.today()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def test_interactiva(self):
        """Primer ejercicio bien; segundo: respuesta erronea, pista y rendirse."""
        pendientes = practica.cola_de_hoy(self.fichas, self.dia, minimo=True)
        self.assertEqual(len(pendientes), 2)
        v1 = self.fichas[pendientes[0]["ficha"]].variante(pendientes[0]["semilla"])
        # ... "s" (se rinde), causa 3, sensacion 4 y un comentario
        respuestas = iter(["4", v1.solucion_texto, "2", "0", "p", "s", "3", "4", "hoy bien"])
        salida = io.StringIO()
        # Las tecnicas nuevas piden un Enter tras el ejemplo resuelto.
        entrada = lambda p: "" if "Enter para seguir" in p else next(respuestas)
        with mock.patch.object(builtins, "input", entrada), redirect_stdout(salida):
            practica.sesion_interactiva(self.fichas, self.dia, minimo=True, git=False)
        texto = salida.getvalue()
        self.assertIn("Correcto.", texto)
        self.assertIn("No cuadra", texto)
        self.assertIn("Pista:", texto)
        log = registro.leer()
        self.assertEqual([e["nota"] for e in log], [3, 1])
        self.assertEqual(log[0]["confianza"], 4)
        self.assertEqual(log[1]["pistas"], 4)
        self.assertEqual(log[1]["causa"], tutela.CAUSAS["3"])
        self.assertIn("El motor ve", texto)  # el «0» de la integral tiene diagnostico
        notas = tutela.leer_notas()
        self.assertEqual((notas[0]["tipo"], notas[0]["valor"], notas[0]["texto"]), ("sensacion", 4, "hoy bien"))
        diario = (self.tmp / "sesiones.md").read_text(encoding="utf-8")
        self.assertIn("Practica (motor)", diario)
        self.assertIn("2 ejercicios, 1 sin ayuda", diario)
        # La cola del dia ya esta vacia.
        self.assertEqual(practica.cola_de_hoy(self.fichas, self.dia, minimo=True), [])

    def test_modo_revisor(self):
        """Los comandos JSON: cola, comprobar, pista, registrar, cerrar, informe."""
        def correr(*args):
            salida = io.StringIO()
            with redirect_stdout(salida):
                practica.main(list(args))
            return salida.getvalue()

        cola = json.loads(correr("cola"))
        self.assertEqual(len(cola), 5)  # 5 por defecto
        x = next(c for c in cola if c["tipo"] != "algebra")
        v = self.fichas[x["ficha"]].variante(x["semilla"])
        self.assertFalse(json.loads(correr("comprobar", x["ficha"], str(x["semilla"]), "x^99"))["correcto"])
        ok = json.loads(correr("comprobar", x["ficha"], str(x["semilla"]), v.solucion_texto))
        self.assertTrue(ok["correcto"])
        self.assertTrue(correr("pista", x["ficha"], str(x["semilla"]), "1").strip())
        r = json.loads(correr("registrar", x["ficha"], str(x["semilla"]), "--confianza", "2",
                              "--pistas", "1", "--respuesta", v.solucion_texto))
        # El «x^99» de antes cuenta como fallo: acertar despues vale 2.
        self.assertEqual((r["nota"], r["fallos"]), (2, 1))
        self.assertEqual(len(json.loads(correr("cola"))), 4)
        self.assertIn("1 ejercicio,", correr("cerrar", "--sin-git"))
        self.assertIn("PENDIENTES HOY", correr("informe"))

    def test_la_nota_no_se_puede_inflar(self):
        """registrar vuelve a comprobar: una respuesta mala queda como fallo."""
        f = self.fichas["I01"]
        v = f.variante(1)
        entrada, _ = sesion.registrar(v, "x^3", confianza=5, pistas=0)
        self.assertFalse(entrada["correcto"])
        self.assertEqual(entrada["nota"], 1)


if __name__ == "__main__":
    unittest.main()
