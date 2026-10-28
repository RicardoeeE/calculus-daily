"""Los .bat (Practicar, Terminal, Quitar-recordatorio), el recordatorio y el doctor."""
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from calculo import doctor, rutas

RAIZ = rutas.RAIZ   # el repo: Practicar.bat, otras-opciones/, README.md
PS1 = rutas.HERRAMIENTAS / "recordatorio.ps1"


def _crlf(nombre):
    datos = (RAIZ / nombre).read_bytes()
    return datos.count(b"\n") == datos.count(b"\r\n"), datos.decode("utf-8")


class TestBats(unittest.TestCase):
    def test_practicar_no_espera_en_silencio(self):
        """Sin pywebview y con la red colgada, cada arranque esperaba ~31 s
        callado; y la reinstalacion de :comprobar iba sin tope (98 s)."""
        ok, texto = _crlf("Practicar.bat")
        self.assertTrue(ok)
        self.assertIn("Intento instalar la ventana (max. 30 s)", texto)
        self.assertIn(".cache/intento-ventana.txt", texto)   # como mucho una vez al dia
        self.assertEqual(texto.count("--timeout 15 --retries 1"), 2)
        comprobar = texto[texto.index(":comprobar"):texto.index(":practicar")]
        self.assertIn("echo ", comprobar)
        self.assertIn("la ventana", texto[:texto.index(":comprobar")])
        self.assertIn("Hoy solo 2", texto)

    def test_terminal_bat(self):
        ok, texto = _crlf("otras-opciones/Terminal.bat")
        self.assertTrue(ok)
        self.assertIn("practica.py hoy", texto)
        self.assertIn("Practicar.bat", texto)     # si falta el entorno, remite a Practicar
        self.assertNotIn("venv .venv", texto)     # no crea el entorno

    def test_quitar_recordatorio_bat(self):
        ok, texto = _crlf("otras-opciones/Quitar-recordatorio.bat")
        self.assertTrue(ok)
        self.assertIn("-ExecutionPolicy Bypass", texto)
        self.assertIn(r"programa\herramientas\quitar-recordatorio.ps1", texto)

    def test_readme_los_cita(self):
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        for nombre in ("Terminal.bat", "Quitar-recordatorio.bat", "Hoy solo 2"):
            self.assertIn(nombre, readme)


class TestDoctorRecordatorio(unittest.TestCase):
    """OJO si la tarea programada apunta a otro recordatorio.ps1."""

    def xml(self, ruta):
        return (f'<Exec><Command>powershell.exe</Command><Arguments>-NoProfile -File "{ruta}"'
                '</Arguments></Exec>')

    def test_sin_tarea_nada(self):
        self.assertEqual(doctor._recordatorio(lambda: (1, "")), [])

    def test_misma_ruta_ok(self):
        r = doctor._recordatorio(lambda: (0, self.xml(rutas.HERRAMIENTAS / "recordatorio.ps1")))
        self.assertEqual(r[0][0], True)

    def test_otra_ruta_ojo(self):
        r = doctor._recordatorio(lambda: (0, self.xml(r"D:\viejo\calculo-diario\herramientas\recordatorio.ps1")))
        self.assertIsNone(r[0][0])
        self.assertIn(r"D:\viejo", r[0][1])

    def test_fallo_al_consultar_nada(self):
        def roto():
            raise OSError("sin schtasks")
        self.assertEqual(doctor._recordatorio(roto), [])


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell.exe"), "solo Windows")
class TestRecordatorio(unittest.TestCase):
    """Texto, «Hoy no», tope de 3 avisos y racha con tope de tiempo.
    Con -SoloDecidir no sale ninguna ventana ni se toca la tarea programada."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def correr(self, ahora, racha="0:4", respuesta=7, **extra):
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1), "-SoloDecidir",
                "-Carpeta", str(self.tmp), "-Ahora", ahora, "-Respuesta", str(respuesta)]
        if racha is not None:
            args += ["-Racha", racha]
        for k, v in extra.items():
            args += [f"-{k}", str(v)]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr)
        decision, _, texto = r.stdout.strip().partition("|")
        return decision, texto

    def test_texto_sin_presion(self):
        decision, texto = self.correr("2026-10-28T07:30:00")
        self.assertEqual(decision, "avisar")
        self.assertIn("Llevas 4 d", texto)
        self.assertIn("Hoy con 2 ya cuenta.", texto)
        self.assertNotIn("pierdas", texto)
        self.assertIn("Cancelar: hoy no", texto)

    def test_hecho_no_avisa(self):
        self.assertEqual(self.correr("2026-10-28T07:30:00", racha="1:5")[0], "hecho")

    def test_como_mucho_3_y_no_seguidos(self):
        horas = ["07:30", "07:40", "08:00", "08:30", "09:00"]
        decisiones = [self.correr(f"2026-10-28T{h}:00")[0] for h in horas]
        self.assertEqual(decisiones, ["avisar", "reciente", "avisar", "avisar", "tope"])
        self.assertEqual(self.correr("2026-10-29T07:30:00")[0], "avisar")   # otro dia, de cero

    def test_hoy_no_silencia_hasta_manana(self):
        self.assertEqual(self.correr("2026-10-28T07:30:00", respuesta=2)[0], "avisar")
        self.assertEqual(self.correr("2026-10-28T11:00:00")[0], "hoy-no")
        self.assertEqual(self.correr("2026-10-29T07:30:00")[0], "avisar")

    def test_racha_colgada_aviso_sin_racha(self):
        lento = self.tmp / "lento.py"
        lento.write_text("import time\ntime.sleep(30)\nprint('{\"hecho_hoy\": false, \"racha\": 9}')\n",
                         encoding="utf-8")
        inicio = time.monotonic()
        decision, texto = self.correr("2026-10-28T07:30:00", racha=None, Python=sys.executable, Guion=lento,
                                      TopeRacha=2)
        self.assertLess(time.monotonic() - inicio, 25)
        self.assertEqual(decision, "avisar")
        self.assertNotIn("Llevas", texto)
        self.assertIn("Hoy con 2 ya cuenta.", texto)

    def test_racha_de_verdad(self):
        rapido = self.tmp / "rapido.py"
        rapido.write_text("print('{\"hecho_hoy\": false, \"racha\": 7}')\n", encoding="utf-8")
        decision, texto = self.correr("2026-10-28T07:30:00", racha=None, Python=sys.executable, Guion=rapido)
        self.assertIn("Llevas 7 d", texto)

    def test_sin_acentos(self):
        self.assertTrue(all(b < 128 for b in PS1.read_bytes()))


if __name__ == "__main__":
    unittest.main()
