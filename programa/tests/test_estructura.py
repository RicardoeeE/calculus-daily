"""Raiz minima: en la raiz solo lo de cada dia; el resto en programa/ y
otras-opciones/. usuario/ y .cache siguen en la raiz."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from calculo import rutas

RAIZ = rutas.RAIZ
PERMITIDOS = {
    "Practicar.bat", "otras-opciones", "usuario", "README.md", "README.es.md", "LICENSE", "programa",
    ".gitignore", ".gitattributes", ".git",
    ".venv", ".cache",                     # los crea el programa; ocultos, no van a git
    "desktop.ini", "Thumbs.db",            # los pone Windows a veces
}
_A_PROGRAMA_USUARIO = re.compile(r"programa[\\/]+(usuario|\.cache)\b", re.I)
_ENLACE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _git_raiz():
    r = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, {linea.split("/")[0] for linea in r.stdout.splitlines() if linea}


class TestRaizMinima(unittest.TestCase):
    def test_rutas(self):
        self.assertEqual(rutas.PROGRAMA.name, "programa")
        self.assertTrue((rutas.PROGRAMA / "practica.py").exists())
        self.assertEqual(rutas.USUARIO, RAIZ / "usuario")
        self.assertEqual(rutas.CACHE, RAIZ / ".cache")
        self.assertTrue((RAIZ / "Practicar.bat").exists())

    def test_en_la_raiz_solo_lo_permitido(self):
        sobran = sorted(p.name for p in RAIZ.iterdir() if p.name not in PERMITIDOS)
        self.assertEqual(sobran, [], "en la raiz solo va lo de cada dia; lo demas a programa/ u otras-opciones/")

    def test_git_en_la_raiz(self):
        codigo, primeros = _git_raiz()
        if codigo:
            self.skipTest("sin git")
        self.assertLessEqual(primeros, PERMITIDOS)
        self.assertNotIn(".venv", primeros)
        self.assertNotIn(".cache", primeros)

    def test_otras_opciones_solo_bat(self):
        nombres = sorted(p.name for p in (RAIZ / "otras-opciones").iterdir())
        self.assertTrue(nombres and all(n.endswith(".bat") for n in nombres), nombres)
        self.assertEqual([p.name for p in RAIZ.glob("*.bat")], ["Practicar.bat"])
        for n in ("Terminal.bat", "Preparar-examen.bat", "Simulacro.bat", "Prueba-nivel.bat",
                  "Quitar-recordatorio.bat", "Comprobar-datos.bat"):
            self.assertIn(n, nombres)

    def test_lanzadores(self):
        practicar = (RAIZ / "Practicar.bat").read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', practicar)
        self.assertIn(r"programa\practica.py ventana", practicar)
        self.assertIn(r"-r programa\requirements.txt", practicar)
        self.assertIn("attrib +h", practicar)
        for oculto in (".venv", ".cache"):
            self.assertIn(oculto, practicar[practicar.index("attrib +h") - 80:])
        for bat in (RAIZ / "otras-opciones").glob("*.bat"):
            datos = bat.read_bytes()
            self.assertEqual(datos.count(b"\n"), datos.count(b"\r\n"), bat.name)   # CRLF
            texto = datos.decode("utf-8")
            self.assertIn("chcp 65001 >nul <nul", texto, bat.name)
            self.assertIn('cd /d "%~dp0.."', texto, bat.name)
            self.assertNotRegex(texto, r"(?<![\\\w])practica\.py", bat.name)   # siempre programa\practica.py

    def test_nada_apunta_a_programa_usuario(self):
        ficheros = [p for ext in ("*.py", "*.bat", "*.ps1", "*.js", "*.html", "*.toml")
                    for p in list(RAIZ.glob(ext)) + list(rutas.PROGRAMA.rglob(ext))
                    if ".venv" not in p.parts and p.name != "test_estructura.py"]
        malos = [str(p.relative_to(RAIZ)) for p in ficheros
                 if _A_PROGRAMA_USUARIO.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(malos, [])

    def test_rutas_de_los_modulos_fuera_de_programa(self):
        """En un proceso limpio (las pruebas redirigen estas rutas a temporales)."""
        codigo = (
            "import json, practica\n"
            "from calculo import datos, registro, servicio, sesion, tutela\n"
            "print(json.dumps([str(x) for x in (registro.RUTA, sesion.DIARIO, sesion.SIMULACROS, tutela.NOTAS,"
            " tutela.REVISIONES, datos.DATOS, servicio.CACHE, practica.CACHE)]))\n")
        r = subprocess.run([sys.executable, "-B", "-c", codigo], cwd=rutas.PROGRAMA, capture_output=True,
                           text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        for ruta in map(Path, json.loads(r.stdout)):
            self.assertFalse(ruta.is_relative_to(rutas.PROGRAMA), ruta)
            self.assertTrue(ruta.is_relative_to(RAIZ), ruta)

    def test_enlaces_markdown(self):
        """Cada enlace relativo a un fichero de los .md del repo existe."""
        rotos = []
        for md in [*RAIZ.glob("*.md"), *(RAIZ / "usuario").rglob("*.md"), *rutas.DOCS.rglob("*.md")]:
            if "historia" in md.relative_to(RAIZ).parts:
                continue   # documentos antiguos: citan la estructura de su dia
            for destino in _ENLACE.findall(md.read_text(encoding="utf-8")):
                if re.match(r"^[a-z]+:", destino) or destino.startswith("#"):
                    continue
                ruta = (md.parent / destino.split("#")[0]).resolve()
                if not ruta.exists():
                    rotos.append(f"{md.relative_to(RAIZ)} -> {destino}")
        self.assertEqual(rotos, [])


if __name__ == "__main__":
    unittest.main()
