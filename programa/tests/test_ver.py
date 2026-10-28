"""Tecla v, ver la ficha con math-plotter (sin abrir nada de verdad)."""
import builtins
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import practica
from calculo import ver
from calculo.fichas import cargar


class TestVer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = cargar()

    def setUp(self):
        # Un math-plotter de mentira: solo hace falta el script y el .venv.
        self.mp = Path(tempfile.mkdtemp()) / "math-plotter"
        (self.mp / ".venv" / "Scripts").mkdir(parents=True)
        (self.mp / ".venv" / "Scripts" / "python.exe").write_text("")
        (self.mp / "math_plotter_pro.py").write_text("")

    def _cmd(self, ficha_id, semilla=1):
        cmd, mensaje = ver.comando(self.fichas[ficha_id].variante(semilla), self.mp)
        self.assertEqual(mensaje, "")
        return cmd[2:]   # sin python ni script

    def test_integral_dibuja_el_integrando(self):
        args = self._cmd("I02")
        self.assertEqual(args[:2], ["--funcion", "1/x"])
        self.assertNotIn("--derivada", args)
        self.assertNotIn("--area", args)

    def test_definida_con_area(self):
        f = next(f for f in self.fichas.values() if f.tipo == "definida" and "oo" not in "".join(f.limites))
        v = f.variante(1)
        args = ver.comando(v, self.mp)[0][2:]
        self.assertIn("--area", args)
        a, b = args[args.index("--area") + 1:args.index("--area") + 3]
        self.assertLess(float(a), float(b))
        self.assertLess(float(args[args.index("--desde") + 1]), float(a))
        self.assertGreater(float(args[args.index("--hasta") + 1]), float(b))

    def test_definida_infinita_sin_area(self):
        f = next((f for f in self.fichas.values() if f.tipo == "definida" and "oo" in "".join(f.limites)), None)
        if f is None:
            self.skipTest("no hay definidas con limite infinito")
        self.assertNotIn("--area", ver.comando(f.variante(1), self.mp)[0])

    def test_derivada_y_parcial_con_derivada(self):
        self.assertIn("--derivada", self._cmd("D01"))
        parcial = next(f for f in self.fichas.values() if f.tipo == "parcial")
        cmd = self._cmd(parcial.id)
        self.assertIn("--derivada", cmd)
        self.assertNotIn("y", cmd[1].replace("exp", "").replace("sqrt", ""))   # la otra letra es un numero

    def test_sintaxis_de_math_plotter(self):
        """Nada de «·», «sen», «^» ni letras sueltas distintas de x."""
        for f in self.fichas.values():
            args = ver.argumentos(f.variante(2))
            if args is None:
                continue
            with self.subTest(ficha=f.id):
                expr = args[1]
                for malo in ("·", "sen", "^", "√", "∞", "ln", "arc"):
                    self.assertNotIn(malo, expr)

    def test_sin_grafica_para_algebra(self):
        cmd, mensaje = ver.comando(self.fichas["AL-CUAD"].variante(1), self.mp)
        self.assertIsNone(cmd)
        self.assertEqual(mensaje, ver.SIN_GRAFICA)

    def test_sin_math_plotter(self):
        inexistente = Path(tempfile.mkdtemp()) / "no-existe"
        cmd, mensaje = ver.comando(self.fichas["I02"].variante(1), inexistente)
        self.assertIsNone(cmd)
        self.assertEqual(mensaje, "Para ver graficas instala math-plotter junto a calculo-diario")

    def test_variable_de_entorno(self):
        with mock.patch.dict("os.environ", {"MATH_PLOTTER": str(self.mp)}):
            self.assertEqual(ver.carpeta_plotter(), self.mp)
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("MATH_PLOTTER", None)
            self.assertEqual(ver.carpeta_plotter(), ver.POR_DEFECTO)

    def test_lanza_proceso_aparte(self):
        with mock.patch.dict("os.environ", {"MATH_PLOTTER": str(self.mp)}), \
                mock.patch.object(ver.subprocess, "Popen") as popen:
            mensaje = ver.ver_ficha(self.fichas["I02"].variante(1))
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][2], "--funcion")
        self.assertIn("grafica", mensaje)

    def _sesion(self, ficha_id, respuestas):
        v = self.fichas[ficha_id].variante(1)
        it = iter(respuestas)
        salida = io.StringIO()
        # .cache aparte: la terminal anota ahi la hora de inicio.
        with mock.patch.object(builtins, "input", lambda p: next(it)), redirect_stdout(salida), \
                mock.patch.object(practica, "CACHE", Path(tempfile.mkdtemp()) / ".cache"), \
                mock.patch.object(practica, "registrar", return_value=({}, __import__("datetime").date.today())) as reg, \
                mock.patch.object(practica, "ejemplo_con_huecos", return_value=(None, 0)):
            practica._un_ejercicio(self.fichas, {"ficha": ficha_id, "semilla": 1, "motivo": "repaso"}, 1, 1)
        return salida.getvalue(), reg

    def test_tecla_v_no_cuenta_como_pista_y_avisa_si_no_hay_plotter(self):
        inexistente = Path(tempfile.mkdtemp()) / "no-existe"
        v = self.fichas["I02"].variante(1)
        with mock.patch.dict("os.environ", {"MATH_PLOTTER": str(inexistente)}):
            texto, reg = self._sesion("I02", ["3", "v", v.solucion_texto])
        self.assertIn("Para ver graficas instala math-plotter junto a calculo-diario", texto)
        self.assertIn("Correcto.", texto)
        self.assertEqual(reg.call_args.args[3], 0)   # pistas = 0


if __name__ == "__main__":
    unittest.main()
