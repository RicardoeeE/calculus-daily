"""La subida con git (sesion._git) en repositorios temporales de verdad."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from calculo import rutas, sesion

RAIZ = rutas.RAIZ
DIA = date(2026, 10, 28)


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check,
                          encoding="utf-8", errors="replace")


def configurar(raiz):
    git(raiz, "config", "user.email", "t@t")
    git(raiz, "config", "user.name", "t")
    git(raiz, "config", "core.autocrlf", "false")


def escribir(raiz, nombre, texto):
    ruta = Path(raiz) / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


def subir(raiz, n=1):
    with mock.patch.object(sesion, "RAIZ", Path(raiz)):
        return sesion._git(DIA, n)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)


class TestUnRepo(Base):
    def setUp(self):
        super().setUp()
        self.raiz = self.tmp / "repo"
        self.raiz.mkdir()
        git(self.raiz, "init", "-q", "-b", "main")
        configurar(self.raiz)
        escribir(self.raiz, "otro.md", "x\n")
        git(self.raiz, "add", "otro.md")
        git(self.raiz, "commit", "-q", "-m", "inicio")

    def test_carpetas_de_datos_no_rompen(self):
        """Con usuario/revisiones y usuario/simulacros creadas, read_text sobre
        la carpeta daba PermissionError y la ventana decia «sin red»."""
        escribir(self.raiz, "usuario/datos/registro.jsonl", "{}\n")
        escribir(self.raiz, "usuario/revisiones/2026-10-28.md", "# revision\n")
        escribir(self.raiz, "usuario/simulacros/2026-10-28_P2.md", "# simulacro\n")
        mensaje = subir(self.raiz)
        self.assertIn("commit hecho", mensaje)
        cambiados = set(git(self.raiz, "show", "--name-only", "--format=", "HEAD").stdout.split())
        self.assertEqual(cambiados, {"usuario/datos/registro.jsonl", "usuario/revisiones/2026-10-28.md",
                                     "usuario/simulacros/2026-10-28_P2.md"})

    def test_marcas_dentro_de_una_carpeta(self):
        escribir(self.raiz, "usuario/revisiones/2026-10-28.md", "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n")
        self.assertIn("usuario/revisiones/2026-10-28.md tiene marcas de conflicto", subir(self.raiz))

    def test_plural_en_el_commit(self):
        escribir(self.raiz, "usuario/diario.md", "uno\n")
        subir(self.raiz, 1)
        self.assertEqual(git(self.raiz, "log", "-1", "--format=%s").stdout.strip(),
                         "content: sesion 2026-10-28 (1 ejercicio)")
        escribir(self.raiz, "usuario/diario.md", "dos\n")
        subir(self.raiz, 3)
        self.assertEqual(git(self.raiz, "log", "-1", "--format=%s").stdout.strip(),
                         "content: sesion 2026-10-28 (3 ejercicios)")

    def test_index_lock_viejo_se_borra(self):
        """Un git muerto deja .git/index.lock; si es viejo, se quita."""
        escribir(self.raiz, "usuario/diario.md", "uno\n")
        marca = self.raiz / ".git" / "index.lock"
        marca.write_text("", encoding="utf-8")
        viejo = time.time() - sesion.INDEX_LOCK_VIEJO - 60
        os.utime(marca, (viejo, viejo))
        self.assertIn("commit hecho", subir(self.raiz))
        self.assertFalse(marca.exists())

    def test_index_lock_reciente_se_respeta(self):
        escribir(self.raiz, "usuario/diario.md", "uno\n")
        marca = self.raiz / ".git" / "index.lock"
        marca.write_text("", encoding="utf-8")
        self.assertIn("no se pudo hacer commit", subir(self.raiz))
        self.assertTrue(marca.exists())


class TestDosEquipos(Base):
    """Dos clones de un remoto bare, con el .gitattributes del repo."""

    def setUp(self):
        super().setUp()
        self.remoto = self.tmp / "remoto.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remoto))
        semilla = self.tmp / "semilla"
        git(self.tmp, "clone", "-q", str(self.remoto), str(semilla))
        configurar(semilla)
        shutil.copy(RAIZ / ".gitattributes", semilla / ".gitattributes")
        escribir(semilla, "otro.md", "x\n")
        escribir(semilla, "usuario/datos/registro.jsonl", '{"a": 0}\n')
        git(semilla, "add", ".")
        git(semilla, "commit", "-q", "-m", "inicio")
        git(semilla, "push", "-q", "origin", "main")
        self.a, self.b = self.tmp / "a", self.tmp / "b"
        for c in (self.a, self.b):
            git(self.tmp, "clone", "-q", str(self.remoto), str(c))
            configurar(c)

    def limpio(self, raiz):
        self.assertFalse((raiz / ".git" / "rebase-merge").exists())
        self.assertFalse((raiz / ".git" / "rebase-apply").exists())
        self.assertEqual(git(raiz, "ls-files", "-u").stdout.strip(), "")

    def test_informes_del_mismo_dia_se_juntan(self):
        for c, quien in ((self.a, "A"), (self.b, "B")):
            escribir(c, "usuario/datos/registro.jsonl", f'{{"a": 0}}\n{{"equipo": "{quien}"}}\n')
            escribir(c, "usuario/revisiones/2026-10-28.md", f"# Revision\nhecha en {quien}\n")
            escribir(c, "usuario/revisiones/2026-10-28_nivel.md", f"# Nivel\n{quien}\n")
            escribir(c, "usuario/simulacros/2026-10-28_P2.md", f"# Simulacro\n{quien}\n")
        self.assertIn("subido", subir(self.a))
        mensaje = subir(self.b)
        self.assertIn("subido", mensaje)
        self.limpio(self.b)
        rev = (self.b / "usuario/revisiones/2026-10-28.md").read_text(encoding="utf-8")
        self.assertIn("hecha en A", rev)
        self.assertIn("hecha en B", rev)
        reg = (self.b / "usuario/datos/registro.jsonl").read_text(encoding="utf-8")
        self.assertIn('"A"', reg)
        self.assertIn('"B"', reg)
        # Y el siguiente cierre de A trae lo de B sin chocar.
        escribir(self.a, "usuario/diario.md", "A otra vez\n")
        self.assertIn("subido", subir(self.a))

    def test_choque_deja_el_repo_limpio_y_lo_dice(self):
        escribir(self.a, "otro.md", "de A\n")
        git(self.a, "commit", "-q", "-am", "A")
        git(self.a, "push", "-q")
        escribir(self.b, "otro.md", "de B\n")
        git(self.b, "commit", "-q", "-am", "B")
        escribir(self.b, "usuario/diario.md", "sesion de B\n")
        mensaje = subir(self.b)
        self.assertIn("choca", mensaje)
        self.assertIn("otro.md", mensaje)
        self.assertIn("queda como estaba", mensaje)
        self.limpio(self.b)
        self.assertEqual(git(self.b, "status", "--porcelain").stdout.strip(), "")

    def test_cambios_sin_commit_fuera_de_los_datos(self):
        """Sin --autostash, «pull --rebase» se negaba con otro.md a medias."""
        escribir(self.a, "usuario/diario.md", "A\n")
        self.assertIn("subido", subir(self.a))
        escribir(self.b, "otro.md", "a medias en B\n")
        escribir(self.b, "usuario/datos/registro.jsonl", '{"a": 0}\n{"equipo": "B"}\n')
        self.assertIn("subido", subir(self.b))
        self.assertEqual((self.b / "otro.md").read_text(encoding="utf-8"), "a medias en B\n")
        self.limpio(self.b)

    def test_sin_red_mensaje_neutro(self):
        """Sin red, un mensaje neutro: nada de «a mano»."""
        git(self.b, "remote", "set-url", "origin", "https://equipo-que-no-existe.invalid/repo.git")
        escribir(self.b, "usuario/diario.md", "B\n")
        entorno = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
        with mock.patch.object(sesion, "RAIZ", self.b):
            mensaje = sesion._git(DIA, 1, timeout=60, entorno=entorno)
        self.assertIn("Sin red: se sube la proxima vez", mensaje)
        self.assertNotIn("a mano", mensaje)


if __name__ == "__main__":
    unittest.main()
