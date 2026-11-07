"""Rutas del proyecto: la unica fuente de verdad.

    calculus-daily/        RAIZ (el repo; git trabaja aqui)
    ├── Practicar.bat
    ├── otras-opciones/        los demas .bat
    ├── usuario/               USUARIO: lo del usuario (diario, datos, revisiones...)
    ├── .cache/ y .venv/       CACHE y el entorno: los crea el programa (ocultos)
    └── programa/              PROGRAMA: practica.py, calculo/, fichas/, interfaz/...

Nada de usuario/ ni de .cache vive dentro de programa/.
"""
import os
from pathlib import Path

PROGRAMA = Path(__file__).resolve().parent.parent
RAIZ = PROGRAMA.parent
USUARIO = RAIZ / "usuario"
DATOS = USUARIO / "datos"
# CALCULO_CACHE: otra .cache (solo herramientas/pruebas.py, para no tocar la de verdad).
CACHE = Path(os.environ.get("CALCULO_CACHE") or RAIZ / ".cache")
VENV = RAIZ / ".venv"
FICHAS = PROGRAMA / "fichas"
INTERFAZ = PROGRAMA / "interfaz"
HERRAMIENTAS = PROGRAMA / "herramientas"
DOCS = PROGRAMA / "docs"
