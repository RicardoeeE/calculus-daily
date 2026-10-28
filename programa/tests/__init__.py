"""En la bateria, las copias de datos (calculo/datos.py) van a una carpeta
temporal que se borra al acabar, nunca a las copias de verdad.
El calendario de examenes es uno fijo de prueba, no el de fichas/calendario.toml."""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

if not os.environ.get("CALCULO_DIARIO_COPIAS"):
    _COPIAS = tempfile.mkdtemp(prefix="calculo-copias-pruebas-")
    os.environ["CALCULO_DIARIO_COPIAS"] = _COPIAS
    atexit.register(shutil.rmtree, _COPIAS, True)

os.environ.setdefault("CALCULO_DIARIO_CALENDARIO", str(Path(__file__).with_name("calendario_prueba.toml")))
