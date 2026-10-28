"""Un solo registro aunque lleguen
dos a la vez, acertar tras fallar vale 2 y las anotaciones de .cache no se pierden."""
import builtins
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import practica
from calculo import registro, rutas, sesion, tutela
from calculo.fichas import cargar
from calculo.sesion import YaRegistrado, registrar

PROGRAMA = rutas.PROGRAMA   # donde esta el paquete calculo
FICHAS = cargar()


class Temporal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ruta = self.tmp / "registro.jsonl"
        self.parches = [
            mock.patch.object(registro, "RUTA", self.ruta),
            mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
            mock.patch.object(practica, "CACHE", self.tmp / ".cache"),
            mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
            mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones"),
        ]
        for p in self.parches:
            p.start()
        self.v = FICHAS["D01"].variante(0)

    def tearDown(self):
        for p in self.parches:
            p.stop()


class TestRegistroUnico(Temporal):
    def test_hilos_a_la_vez_dejan_una_linea(self):
        errores, barrera = [], threading.Barrier(4)

        def uno():
            barrera.wait()
            try:
                registrar(self.v, "4x^3", 3, 0, ruta=self.ruta)
            except YaRegistrado as exc:
                errores.append(exc)

        hilos = [threading.Thread(target=uno) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(registro.leer(self.ruta)), 1)
        self.assertEqual(len(errores), 3)

    def test_procesos_a_la_vez_dejan_una_linea(self):
        codigo = (
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from calculo.fichas import cargar\n"
            "from calculo.sesion import registrar, YaRegistrado\n"
            "v = cargar()['D01'].variante(0)\n"
            "try:\n"
            "    registrar(v, '4x^3', 3, 0, ruta=sys.argv[2]); print('ok')\n"
            "except YaRegistrado:\n"
            "    print('repetido')\n"
        )
        procesos = [subprocess.Popen([sys.executable, "-c", codigo, str(PROGRAMA), str(self.ruta)],
                                     stdout=subprocess.PIPE, text=True) for _ in range(3)]
        salidas = sorted(p.communicate(timeout=120)[0].strip() for p in procesos)
        self.assertEqual(salidas, ["ok", "repetido", "repetido"])
        self.assertEqual(len(registro.leer(self.ruta)), 1)

    def test_forzar_sigue_permitiendo_un_segundo_intento(self):
        registrar(self.v, "4x^3", 3, 0, ruta=self.ruta)
        registrar(self.v, "4x^3", 3, 0, ruta=self.ruta, forzar=True)
        self.assertEqual(len(registro.leer(self.ruta)), 2)


class TestFallos(Temporal):
    def test_nota(self):
        self.assertEqual(registro.nota(True, 0), 3)
        self.assertEqual(registro.nota(True, 0, fallos=1), 2)
        self.assertEqual(registro.nota(True, 0, 5, 1, 100, fallos=1), 2)  # ni siquiera 4
        self.assertEqual(registro.nota(False, 0, fallos=3), 1)

    def test_registrar_guarda_los_fallos(self):
        entrada, _ = registrar(self.v, "4x^3", 3, 0, ruta=self.ruta, fallos=2)
        self.assertEqual((entrada["nota"], entrada["fallos"]), (2, 2))

    def test_terminal_cuenta_los_fallos(self):
        respuestas = iter(["3", "4x^4", "4x^3"])
        salida = io.StringIO()
        item = {"ficha": "D01", "semilla": 0, "motivo": "nueva"}
        entrada = lambda p: "" if "Enter para seguir" in p else next(respuestas)
        with mock.patch.object(builtins, "input", entrada), redirect_stdout(salida):
            practica._un_ejercicio(FICHAS, item, 1, 1)
        e = registro.leer()[-1]
        self.assertEqual((e["correcto"], e["fallos"], e["nota"]), (True, 1, 2))
        self.assertIn("costo", salida.getvalue())

    def test_revisor_comprobar_anota_y_registrar_lo_recoge(self):
        dia = date.today()
        with redirect_stdout(io.StringIO()):
            practica.main(["comprobar", "D01", "0", "4x^4"])
            practica.main(["comprobar", "D01", "0", "sen("])  # ilegible: no cuenta
        self.assertEqual(practica.fallos_anotados(dia, "D01", 0), 1)
        salida = io.StringIO()
        with redirect_stdout(salida):
            practica.main(["registrar", "D01", "0", "--confianza", "3", "--respuesta", "4x^3"])
        r = json.loads(salida.getvalue())
        self.assertEqual((r["nota"], r["fallos"]), (2, 1))


class TestAnotacionesConcurrentes(Temporal):
    def test_pistas_y_fallos_en_hilos(self):
        dia = date.today()

        def trabajo(n):
            practica.anotar_pista(dia, "D01", 0, 1 + n % 4)
            practica.anotar_fallo(dia, "D01", 0)

        hilos = [threading.Thread(target=trabajo, args=(n,)) for n in range(12)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(practica.pistas_anotadas(dia, "D01", 0), 4)
        self.assertEqual(practica.fallos_anotados(dia, "D01", 0), 12)

    def test_fichero_roto_no_tumba(self):
        dia = date.today()
        ruta = practica._ruta_cache(f"pistas-{dia.isoformat()}.json")
        ruta.write_text('{"D01:0": 2', encoding="utf-8")
        self.assertEqual(practica.pistas_anotadas(dia, "D01", 0), 0)
        practica.anotar_pista(dia, "D01", 0, 1)
        self.assertEqual(practica.pistas_anotadas(dia, "D01", 0), 1)


if __name__ == "__main__":
    unittest.main()
