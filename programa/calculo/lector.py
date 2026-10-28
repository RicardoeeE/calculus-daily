"""Lectura con tope de tiempo real para la vista previa de la ventana.

sympy no se puede interrumpir desde un hilo: una respuesta como 9**9**9**9 lo
deja calculando (y llenando la memoria) para siempre. Por eso la vista previa
lee en un proceso aparte que se mata si pasa del tope y se vuelve a arrancar
en la siguiente lectura. Protocolo: una linea JSON por peticion y por respuesta.

  python -m calculo.lector CACHE     (lo arranca la clase Lector; no se usa a mano)
"""
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

from .rutas import CACHE, PROGRAMA

TOPE = 2.0        # segundos por lectura
ARRANQUE = 90.0   # segundos para importar sympy y cargar las fichas
DEMASIADO = ("Es demasiado grande para leerla a tiempo. Revisa la expresión "
             "(¿una potencia de potencias?).")
NO_DISPONIBLE = "La vista previa no está disponible ahora; Comprobar funciona igual."


def _servidor(cache):
    for flujo in (sys.stdin, sys.stdout):
        flujo.reconfigure(encoding="utf-8")
    from .fichas import cargar
    from .servicio import Sesion
    s = Sesion(cargar(), cache=cache, seguro=True)
    print("listo", flush=True)
    for linea in sys.stdin:
        try:
            p = json.loads(linea)
            r = s.leer(p["texto"], p["ficha"], p["semilla"])
        except Exception as exc:  # peticion mal formada: se contesta igual
            r = {"ok": False, "leido": None, "latex": None, "error": str(exc)}
        print(json.dumps(r, ensure_ascii=False), flush=True)


class Lector:
    """Cliente del proceso lector. Una lectura cada vez (cerrojo); si una pasa
    del tope, se mata el proceso y se contesta {ok: False, tope: True}."""

    def __init__(self, cache, tope=TOPE, arranque=ARRANQUE):
        self.cache = Path(cache)
        self.tope = tope
        self.arranque = arranque
        self._proc = None
        self._salida = None
        self._cerrojo = threading.Lock()

    def _arrancar(self):
        extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        self._salida = queue.Queue()
        self._proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "calculo.lector", str(self.cache)], cwd=str(PROGRAMA),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **extra)
        proc, salida = self._proc, self._salida

        def leer_salida():
            try:
                for linea in proc.stdout:
                    salida.put(linea)
            except (OSError, ValueError):  # se cerro al matarlo
                pass
            salida.put(None)
        threading.Thread(target=leer_salida, daemon=True).start()
        try:
            if salida.get(timeout=self.arranque) != "listo\n":
                raise RuntimeError("el lector no arranco")
        except (queue.Empty, RuntimeError):
            self._matar()
            raise RuntimeError("el lector no arranco")

    def _matar(self):
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for flujo in (proc.stdin, proc.stdout):
                try:
                    flujo.close()
                except OSError:
                    pass

    def preparar(self):
        """Arranca el proceso por adelantado (en un hilo, al abrir la ventana)."""
        with self._cerrojo:
            if self._proc is None or self._proc.poll() is not None:
                try:
                    self._arrancar()
                except (OSError, RuntimeError):
                    pass

    def leer(self, texto, ficha, semilla):
        with self._cerrojo:
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._arrancar()
                self._proc.stdin.write(json.dumps({"texto": texto, "ficha": ficha, "semilla": semilla},
                                                  ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
                linea = self._salida.get(timeout=self.tope)
            except queue.Empty:
                self._matar()
                return {"ok": False, "leido": None, "latex": None, "avisos": [], "error": DEMASIADO,
                        "tope": True}
            except (OSError, RuntimeError, ValueError):
                self._matar()
                return {"ok": False, "leido": None, "latex": None, "avisos": [], "error": NO_DISPONIBLE,
                        "disponible": False}
            if linea is None:
                self._matar()
                return {"ok": False, "leido": None, "latex": None, "avisos": [], "error": NO_DISPONIBLE,
                        "disponible": False}
            return json.loads(linea)

    def cerrar(self):
        with self._cerrojo:
            self._matar()


if __name__ == "__main__":
    _servidor(sys.argv[1] if len(sys.argv) > 1 else str(CACHE))
