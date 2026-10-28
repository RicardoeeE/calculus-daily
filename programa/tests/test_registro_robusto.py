"""registro.jsonl con la ultima linea cortada y cerrojos huerfanos."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from calculo import registro


def _entrada(n):
    return {"ts": registro.ahora().isoformat(), "ficha": f"D0{n}", "nota": 3}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = self.tmp / "registro.jsonl"


class TestLineaCortada(Base):
    def test_no_se_pega_a_la_linea_rota(self):
        """Un corte a mitad de escritura dejaba la ultima linea sin \\n y la
        siguiente se pegaba a ella: se perdian las dos."""
        registro.anadir(_entrada(1), self.ruta)
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write('{"ts": "2026-10-28T10:00:00+01:00", "fic')   # corte
        registro.anadir(_entrada(2), self.ruta)
        self.assertEqual([e["ficha"] for e in registro.leer(self.ruta)], ["D01", "D02"])
        self.assertTrue(self.ruta.read_text(encoding="utf-8").endswith("\n"))

    def test_fichero_normal_sin_lineas_vacias(self):
        for n in (1, 2, 3):
            registro.anadir(_entrada(n), self.ruta)
        self.assertEqual(len(self.ruta.read_text(encoding="utf-8").splitlines()), 3)

    def test_fichero_vacio(self):
        self.ruta.write_text("", encoding="utf-8")
        registro.anadir(_entrada(1), self.ruta)
        self.assertEqual(self.ruta.read_text(encoding="utf-8").count("\n"), 1)


class TestCerrojo(Base):
    def marca(self):
        return self.ruta.with_name(self.ruta.name + ".lock")

    def test_guarda_el_pid(self):
        with registro.cerrojo(self.ruta):
            dueno = json.loads(self.marca().read_text(encoding="utf-8"))
        self.assertEqual(dueno["pid"], os.getpid())
        self.assertFalse(self.marca().exists())

    def test_huerfano_de_un_proceso_muerto_se_rompe_al_momento(self):
        """Antes un .lock huerfano bloqueaba 30 s y la espera era de 5 s."""
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.marca().write_text(json.dumps({"pid": p.pid, "inicio": 1}), encoding="utf-8")
        inicio = time.monotonic()
        registro.anadir(_entrada(1), self.ruta)
        self.assertLess(time.monotonic() - inicio, 2)
        self.assertEqual(len(registro.leer(self.ruta)), 1)

    def test_pid_reutilizado_se_rompe(self):
        """El PID existe (es este proceso) pero con otra hora de inicio: no es el dueno."""
        yo = registro.inicio_proceso(os.getpid())
        if not yo:
            self.skipTest("sin hora de inicio de procesos en este sistema")
        self.marca().write_text(json.dumps({"pid": os.getpid(), "inicio": yo + 12345}), encoding="utf-8")
        registro.anadir(_entrada(1), self.ruta)
        self.assertEqual(len(registro.leer(self.ruta)), 1)

    def test_vivo_se_respeta_hasta_la_espera(self):
        self.marca().write_text(json.dumps({"pid": os.getpid(), "inicio": registro.inicio_proceso(os.getpid())}),
                                encoding="utf-8")
        inicio = time.monotonic()
        with mock.patch.object(registro, "ESPERA_CERROJO", 0.5):
            registro.anadir(_entrada(1), self.ruta)
        self.assertGreater(time.monotonic() - inicio, 0.4)
        self.assertEqual(len(registro.leer(self.ruta)), 1)

    def test_viejo_sin_pid_se_rompe_tras_la_espera(self):
        """Un cerrojo de una version anterior (vacio) mas viejo que la espera se rompe:
        los dos tiempos son el mismo."""
        self.marca().write_text("", encoding="utf-8")
        viejo = time.time() - registro.ESPERA_CERROJO - 1
        os.utime(self.marca(), (viejo, viejo))
        registro.anadir(_entrada(1), self.ruta)
        self.assertEqual(len(registro.leer(self.ruta)), 1)


if __name__ == "__main__":
    unittest.main()
