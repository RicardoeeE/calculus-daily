"""Ejemplos resueltos (fichas/ejemplos.toml): cobertura, claves y sesion."""
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
from calculo.fichas import CARPETA, ErrorFicha, cargar, cargar_ejemplos


class TestEjemplos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = cargar()
        cls.ejemplos = cargar_ejemplos(fichas=cls.fichas)

    def test_cada_tecnica_tiene_ejemplo(self):
        tecnicas = {f.tecnica for f in self.fichas.values()}
        self.assertEqual(tecnicas - set(self.ejemplos), set())
        self.assertEqual(set(self.ejemplos) - tecnicas, set())

    def test_ejemplos_construyen_y_su_clave_se_acepta(self):
        for tecnica, ej in self.ejemplos.items():
            with self.subTest(tecnica=tecnica):
                v = ej["variante"]
                self.assertEqual(v.ficha.tecnica, tecnica)
                self.assertTrue(sesion.comprobar(v, v.respuesta_modelo).correcto)
                self.assertEqual(ej["enunciado"], v.enunciado)
                self.assertEqual(ej["resultado"], v.solucion_texto)

    def test_el_ultimo_paso_acaba_en_el_resultado_que_se_ensena(self):
        """En cociente y pvi el ultimo paso llega a la misma forma que el resultado."""
        import re
        plano = lambda t: re.sub(r"[\s·*]", "", t).replace("e^(x)", "e^x")
        for tecnica in ("cociente", "pvi"):
            ej = self.ejemplos[tecnica]
            with self.subTest(tecnica=tecnica):
                self.assertIn(plano(ej["variante"].respuesta_modelo), plano(ej["pasos"][-1]))

    def test_pasos_con_contenido(self):
        for tecnica, ej in self.ejemplos.items():
            with self.subTest(tecnica=tecnica):
                self.assertTrue(3 <= len(ej["pasos"]) <= 6)
                self.assertTrue(all(p.strip() for p in ej["pasos"]))
                self.assertTrue(ej["idea"].strip())

    def test_cargar_no_toma_ejemplos_por_fichas(self):
        self.assertFalse(any(i.startswith("ejemplo") for i in self.fichas))
        self.assertNotIn("pasos", {c for f in self.fichas.values() for c in vars(f)})

    def _con_ejemplos(self, texto):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for r in Path(CARPETA).glob("*.toml"):
            if r.name != "ejemplos.toml":
                shutil.copy(r, tmp / r.name)
        (tmp / "ejemplos.toml").write_text(texto, encoding="utf-8")
        return tmp

    def test_errores_claros(self):
        malo = '[[ejemplo]]\ntecnica = "tabla"\nficha = "NO-EXISTE"\nparams = {}\npasos = ["a"]\n'
        with self.assertRaisesRegex(ErrorFicha, "no existe"):
            cargar_ejemplos(self._con_ejemplos(malo))
        otra = '[[ejemplo]]\ntecnica = "partes"\nficha = "I01"\nparams = {}\npasos = ["a"]\n'
        with self.assertRaisesRegex(ErrorFicha, "tecnica"):
            cargar_ejemplos(self._con_ejemplos(otra))


class TestEjemploEnSesion(unittest.TestCase):
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
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fichas = cargar()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def _ejercicio(self, ficha_id, motivo="nueva"):
        v = self.fichas[ficha_id].variante(1)
        respuestas = iter(["3", v.respuesta_modelo])
        entrada = lambda p: "" if "Enter para seguir" in p else next(respuestas)
        salida = io.StringIO()
        with mock.patch.object(builtins, "input", entrada), redirect_stdout(salida):
            practica._un_ejercicio(self.fichas, {"ficha": ficha_id, "semilla": 1, "motivo": motivo}, 1, 2)
        return salida.getvalue()

    def test_se_ensena_la_primera_vez_y_no_la_segunda(self):
        primera = self._ejercicio("I01")
        self.assertIn("Tecnica nueva: tabla. Antes, un ejemplo resuelto:", primera)
        self.assertIn("1. ", primera)
        self.assertIn("Resultado:", primera)
        self.assertLess(primera.index("Tecnica nueva"), primera.index("[1/2]"))
        segunda = self._ejercicio("I02")   # misma tecnica (tabla), ya practicada
        self.assertNotIn("Tecnica nueva", segunda)
        otra = self._ejercicio("D01", motivo="examen")   # tecnica distinta: ejemplo otra vez
        self.assertIn("Tecnica nueva: potencia", otra)

    def test_enter_tolera_fin_de_entrada(self):
        v = self.fichas["I01"].variante(1)
        respuestas = iter(["3", v.respuesta_modelo])

        def entrada(p):
            if "Enter para seguir" in p:
                raise EOFError
            return next(respuestas)

        with mock.patch.object(builtins, "input", entrada), redirect_stdout(io.StringIO()) as out:
            practica._un_ejercicio(self.fichas, {"ficha": "I01", "semilla": 1, "motivo": "nueva"}, 1, 1)
        self.assertIn("Correcto.", out.getvalue())

    def test_cola_json_lleva_ejemplo_solo_en_tecnicas_nuevas(self):
        salida = io.StringIO()
        with redirect_stdout(salida):
            practica.main(["cola"])
        cola = json.loads(salida.getvalue())
        con = [c for c in cola if "ejemplo" in c]
        self.assertTrue(con)
        self.assertEqual(len({c["tecnica"] for c in con}), len(con))   # una vez por tecnica
        for c in con:
            self.assertEqual(set(c["ejemplo"]), {"tecnica", "idea", "enunciado", "pasos", "resultado"})
            self.assertEqual(c["ejemplo"]["tecnica"], c["tecnica"])
        # Tras practicar una tecnica, su ejemplo ya no sale completo (con un acierto: con huecos).
        x = con[0]
        self._ejercicio(x["ficha"])
        salida = io.StringIO()
        with redirect_stdout(salida):
            practica.main(["cola"])
        self.assertFalse(any("ejemplo" in c and c["tecnica"] == x["tecnica"] and "huecos" not in c["ejemplo"]
                             for c in json.loads(salida.getvalue())))


if __name__ == "__main__":
    unittest.main()
