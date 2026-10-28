"""Capturas de las formulas de la ventana, con datos temporales.

Abre la ventana de verdad (pywebview + WebView2) sobre una carpeta temporal con
una cola fija y la recorre sola para fotografiar los estados con formulas:

  1. el ejemplo resuelto de racionales;
  2. la confianza y la vista previa «He leido» de una respuesta;
  3. una integral con la solucion visible (R-DOS, tras pistas 1 y 2);
  4. el ejemplo de la tecnica «constante» (si toca), una parcial con la pista 3
     y la misma parcial ya comprobada.

Ademas copia cada foto, numerada, en CARPETA/fotogramas (los fotogramas del GIF).
Nunca toca usuario/datos ni sube nada (git=False). Uso, desde la raiz del repo:

  .venv\\Scripts\\python.exe programa\\herramientas\\capturas_ventana.py [CARPETA]
  (por defecto programa/docs/capturas)
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from calculo import registro, servicio, ventana  # noqa: E402
from calculo.fichas import cargar  # noqa: E402

COLA = [{"ficha": "R-DOS", "semilla": 1, "motivo": "nueva"},
        {"ficha": "PC-POLI-X", "semilla": 1, "motivo": "nueva"}]


def main(carpeta):
    import webview
    carpeta = Path(carpeta)
    (carpeta / "fotogramas").mkdir(parents=True, exist_ok=True)
    fichas = cargar()
    modelos = [fichas[c["ficha"]].variante(c["semilla"]).respuesta_modelo for c in COLA]
    temporal = Path(tempfile.mkdtemp(prefix="calculo-capturas-"))
    cache = ventana.datos_temporales(temporal)
    dia = servicio.Sesion.hoy()
    registro.escribir_json(servicio.ruta_cache(cache, f"cola-{dia.isoformat()}.json"), COLA)
    api = ventana.API(cache=cache, git=False)
    threading.Thread(target=api._lector.preparar, daemon=True).start()
    titulo = f"{ventana.TITULO} (capturas {os.getpid()})"
    hechas, error = [], []
    w = webview.create_window(titulo, url=str(ventana.INTERFAZ / "index.html"), js_api=api, width=980,
                              height=900, min_size=(560, 560), text_select=True,
                              background_color="#1B1D21" if ventana.tema_oscuro() else "#F7F6F2")

    def js(codigo):
        return w.evaluate_js(codigo)

    def esperar(condicion, tope=30):
        fin = time.monotonic() + tope
        while time.monotonic() < fin:
            try:
                if js(condicion):
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise TimeoutError(condicion)

    fotograma = [0]

    def foto(nombre, ver=None):
        if ver:
            js(f"document.getElementById({json.dumps(ver)}).scrollIntoView({{block: 'end'}})")
        time.sleep(0.6)
        ruta = carpeta / f"ventana-{nombre}.png"
        if ventana._captura(titulo, ruta):
            hechas.append(str(ruta))
            fotograma[0] += 1
            shutil.copyfile(ruta, carpeta / "fotogramas" / f"{fotograma[0]:02d}-{nombre}.png")

    def escribir(texto):
        js(f"const r = document.getElementById('respuesta'); r.value = {json.dumps(texto)};"
           "r.dispatchEvent(new Event('input', {bubbles: true}))")

    fase = "document.body.dataset.fase"

    def recorrido():
        try:
            w.events.loaded.wait(60)
            esperar(f"{fase} === 'ejemplo'")
            foto("ejemplo-racionales")
            js("document.getElementById('ejemplo-seguir').click()")
            esperar(f"{fase} === 'confianza'")
            js("window.scrollTo(0, 0)")
            foto("confianza")
            js("document.querySelector('[data-confianza=\"2\"]').click()")
            esperar(f"{fase} === 'respuesta'")
            escribir(modelos[0])
            esperar("document.getElementById('vista-previa-contenido').textContent.length > 0")
            foto("vista-previa")
            escribir("")
            for n in (1, 2):
                js("document.getElementById('pista').click()")
                esperar(f"document.querySelectorAll('#pistas li').length === {n}")
            js("document.getElementById('ver-solucion').click()")
            esperar("!document.getElementById('confirmar-solucion').hidden")
            js("document.getElementById('solucion-si').click()")
            esperar(f"{fase} === 'causa'")
            foto("integral-solucion", "solucion-texto")
            js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '1', bubbles: true}))")
            esperar(f"{fase} === 'hecho'")
            js("document.getElementById('siguiente').click()")
            esperar(f"['ejemplo', 'confianza'].includes({fase})")
            if js(fase) == "ejemplo":
                js("window.scrollTo(0, 0)")
                foto("ejemplo-parciales")
                js("document.getElementById('ejemplo-seguir').click()")
                esperar(f"{fase} === 'confianza'")
            js("window.scrollTo(0, 0)")
            js("document.querySelector('[data-confianza=\"2\"]').click()")
            esperar(f"{fase} === 'respuesta'")
            for n in (1, 2, 3):
                js("document.getElementById('pista').click()")
                esperar(f"document.querySelectorAll('#pistas li').length === {n}")
            foto("parcial-pista3", "pistas")
            escribir(modelos[1])
            time.sleep(0.8)
            js("document.getElementById('comprobar').click()")
            esperar(f"{fase} !== 'respuesta'")
            js("window.scrollTo(0, 0)")
            foto("parcial-correcta")
        except Exception as exc:
            error.append(repr(exc))
        finally:
            w.destroy()

    webview.start(recorrido, gui="edgechromium", http_server=True, private_mode=True)
    api._lector.cerrar()
    print(json.dumps({"capturas": hechas, "error": error}, ensure_ascii=False, indent=1))
    if not error:
        shutil.rmtree(temporal, ignore_errors=True)
    return 0 if hechas and not error else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else RAIZ / "docs" / "capturas"))
