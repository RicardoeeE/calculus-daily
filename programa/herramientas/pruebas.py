"""Bateria de pruebas en segundo plano: sin ventanas y sin tocar el log real.

    .venv\\Scripts\\python.exe programa\\herramientas\\pruebas.py [patron]

Las pruebas lanzan git, python y powershell. Si se ejecutan desde un proceso sin consola
(un editor, una tarea programada), cada uno abria y cerraba una consola. Aqui todos los
subprocesos van con CREATE_NO_WINDOW y la .cache es temporal: los avisos que provocan las
pruebas (lineas danadas, datos que faltan) ya no acaban en el .cache/servicio.log de verdad.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROGRAMA = Path(__file__).resolve().parent.parent


class _SinVentana(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)


def main(patron="test*.py"):
    if sys.platform == "win32":
        subprocess.Popen = _SinVentana
    cache = tempfile.mkdtemp(prefix="calculo-pruebas-")
    os.environ["CALCULO_CACHE"] = cache   # antes de importar calculo.rutas
    os.chdir(PROGRAMA)
    sys.path.insert(0, str(PROGRAMA))
    sys.dont_write_bytecode = True
    try:
        suite = unittest.defaultTestLoader.discover("tests", pattern=patron, top_level_dir=str(PROGRAMA))
        return 0 if unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite).wasSuccessful() else 1
    finally:
        shutil.rmtree(cache, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
