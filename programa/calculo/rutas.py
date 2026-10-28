"""Rutas del proyecto: la unica fuente de verdad.

    calculo-diario-app/        RAIZ (el repo; git trabaja aqui)
    ├── Practicar.bat
    ├── otras-opciones/        los demas .bat
    ├── usuario/               USUARIO: lo del usuario (diario, datos, revisiones...)
    ├── .cache/ y .venv/       CACHE y el entorno: los crea el programa (ocultos)
    └── programa/              PROGRAMA: practica.py, calculo/, fichas/, interfaz/...

Nada de usuario/ ni de .cache vive dentro de programa/.
"""
from pathlib import Path

PROGRAMA = Path(__file__).resolve().parent.parent
RAIZ = PROGRAMA.parent
USUARIO = RAIZ / "usuario"
DATOS = USUARIO / "datos"
CACHE = RAIZ / ".cache"
VENV = RAIZ / ".venv"
FICHAS = PROGRAMA / "fichas"
INTERFAZ = PROGRAMA / "interfaz"
HERRAMIENTAS = PROGRAMA / "herramientas"
DOCS = PROGRAMA / "docs"
