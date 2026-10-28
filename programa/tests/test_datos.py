"""Proteccion de los datos (calculo/datos.py), escritura comprobada del
registro y arranque sin consola (pythonw + respaldo a la terminal).

Todo en carpetas temporales: las copias van a <tmp>/.copias, nunca a
%LOCALAPPDATA%. Ninguna prueba abre ventanas ni consolas."""
import errno
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import practica
from calculo import datos, doctor, registro, rutas, sesion

RAIZ = rutas.PROGRAMA   # donde esta practica.py (sys.path y cwd de los subprocesos)


def entrada(ts, ficha="I01", semilla=1, nota=3, **extra):
    return {"ts": ts, "ficha": ficha, "semilla": semilla, "nota": nota, **extra}


class Carpeta(unittest.TestCase):
    """Una carpeta de datos temporal con registro.RUTA apuntando a ella."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="calculo-datos-"))
        self.ruta = self.tmp / "registro.jsonl"
        self.parche = mock.patch.object(registro, "RUTA", self.ruta)
        self.parche.start()

    def tearDown(self):
        self.parche.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escribir(self, *entradas, nombre="registro.jsonl"):
        for e in entradas:
            registro.anadir(e, self.tmp / nombre)

    def lineas(self, nombre="registro.jsonl"):
        return [x for x in (self.tmp / nombre).read_text(encoding="utf-8").splitlines() if x.strip()]


class TestCopias(Carpeta):
    def test_copia_verificada_y_solo_si_cambia(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"))
        tutela_ = self.tmp / "notas.jsonl"
        registro.anadir({"id": "S-1", "ts": "2026-10-27T18:10:00+01:00", "tipo": "sensacion"}, tutela_)
        r = datos.copiar("prueba", hoy=date(2026, 10, 27))
        self.assertTrue(r["hecha"])
        self.assertEqual(r["carpeta"], self.tmp / ".copias" / "2026-10-27")   # nunca dentro del repo
        m = datos.ultima_copia()
        self.assertEqual(set(m["ficheros"]), {"registro.jsonl", "notas.jsonl"})
        self.assertTrue(datos.verificar_copia(m))
        self.assertFalse(datos.copiar("otra vez", hoy=date(2026, 10, 27))["hecha"])   # nada cambio
        self.escribir(entrada("2026-10-27T18:20:00+01:00", "I02"))
        r = datos.copiar("cierre", hoy=date(2026, 10, 27))
        self.assertTrue(r["hecha"])
        self.assertEqual(r["carpeta"].name, "2026-10-27")   # solo se anadio: la del dia se renueva
        self.assertEqual(datos.ultima_copia()["ficheros"]["registro.jsonl"]["lineas"], 2)
        # una copia manipulada no pasa la verificacion
        (r["carpeta"] / "registro.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertFalse(datos.verificar_copia(datos.ultima_copia()))

    def test_ruta_de_verdad_fuera_del_repo(self):
        with mock.patch.dict(os.environ, {"CALCULO_DIARIO_COPIAS": ""}), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\X\AppData\Local"}):
            c = datos.carpeta_copias(datos.DATOS)
        self.assertEqual(c, Path(r"C:\X\AppData\Local") / "calculo-diario" / "copias")
        self.assertNotIn(str(rutas.RAIZ).lower(), str(c).lower())

    def test_rotacion_30_dias_y_una_por_mes(self):
        raiz = self.tmp / ".copias"
        hoy = date(2026, 10, 28)
        nombres = ["2026-10-27", "2026-09-29", "2026-09-28", "2026-09-27_101010", "2026-09-27",
                   "2026-09-02", "2026-08-15", "2026-08-31", "2026-08-31_120000", "2025-12-01"]
        for n in nombres:
            (raiz / n).mkdir(parents=True)
            (raiz / n / "manifiesto.json").write_text(json.dumps(
                {"ts": n[:10] + "T10:00:00+01:00", "origen": str(self.tmp.resolve()), "ficheros": {}}),
                encoding="utf-8")
        ajena = raiz / "2026-01-01"   # copia de otra carpeta: no se toca
        ajena.mkdir()
        (ajena / "manifiesto.json").write_text(json.dumps({"ts": "2026-01-01", "origen": "otra", "ficheros": {}}))
        borradas = {c.name for c in datos.rotar(hoy=hoy)}
        quedan = {c.name for c in raiz.iterdir()}
        # dentro de 30 dias (desde 2026-09-29) todas; antes, la mas nueva de cada mes
        self.assertEqual(quedan, {"2026-10-27", "2026-09-29", "2026-09-28", "2026-08-31_120000", "2025-12-01",
                                  "2026-01-01"})
        self.assertEqual(borradas, {"2026-09-27_101010", "2026-09-27", "2026-09-02", "2026-08-15", "2026-08-31"})


class TestPerdidaYRecuperacion(Carpeta):
    def preparar(self):
        self.escribir(*(entrada(f"2026-10-2{d}T18:00:00+01:00", f"I0{d}") for d in range(1, 6)))
        datos.copiar("arranque", hoy=date(2026, 10, 25))

    def test_perdida_detectada_y_recuperada_sin_borrar(self):
        self.preparar()
        todas = self.lineas()
        # se pierden la 2 y la 4 (p. ej. una sincronizacion que pisa el fichero) y llega una nueva
        quedan = [todas[0], todas[2], todas[4]]
        self.ruta.write_text("\n".join(quedan) + "\n", encoding="utf-8")
        self.escribir(entrada("2026-10-28T09:00:00+01:00", "I09"))
        perdidas = datos.faltan()
        self.assertEqual(perdidas, {"registro.jsonl": [todas[1], todas[3]]})
        r = datos.copiar("cierre")
        self.assertFalse(r["hecha"])   # la copia buena no se pisa ni queda vieja sin avisar
        self.assertIn("faltan", r["motivo"])
        self.assertEqual(datos.recuperar(), {"registro.jsonl": 2})
        ahora = self.lineas()
        self.assertEqual(ahora[:5], todas)   # union ordenada por fecha: vuelven a su sitio
        self.assertEqual(len(ahora), 6)
        self.assertEqual(json.loads(ahora[-1])["ficha"], "I09")   # lo nuevo sigue
        self.assertEqual(datos.faltan(), {})
        antes = [m for m in datos.copias() if m["motivo"] == datos.ANTES_DE_RECUPERAR]
        self.assertEqual(len(antes), 1)   # la version de antes de recuperar queda guardada
        self.assertEqual(antes[0]["ficheros"]["registro.jsonl"]["lineas"], 4)

    def test_registro_borrado_entero(self):
        self.preparar()
        self.ruta.unlink()
        preguntas = []
        avisos = datos.al_arrancar(preguntar=lambda t: preguntas.append(t) or True, git=False)
        self.assertIn("Faltan 5 lineas", preguntas[0])
        self.assertIn("Recuperadas 5 lineas", avisos[0])
        self.assertEqual(len(registro.leer()), 5)

    def test_si_no_se_quiere_recuperar_no_se_toca_nada(self):
        self.preparar()
        self.ruta.write_text(self.lineas()[0] + "\n", encoding="utf-8")
        avisos = datos.al_arrancar(preguntar=lambda t: False, git=False)
        self.assertEqual(len(avisos), 1)
        self.assertIn("Faltan 4 lineas", avisos[0])
        self.assertIn("datos --recuperar", avisos[0])
        self.assertEqual(len(self.lineas()), 1)
        # y se sigue avisando en el siguiente arranque (la copia de referencia no cambia)
        self.assertIn("Faltan 4 lineas", datos.al_arrancar(git=False)[0])
        ok = dict((t, o) for o, t in datos.resumen(git=False))
        self.assertTrue(any(o is False and "faltan 4 lineas" in t for t, o in ok.items()))

    def test_sin_copia_no_hay_perdida(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"))
        self.assertEqual(datos.faltan(), {})
        self.assertEqual(datos.al_arrancar(git=False), [])
        self.assertIsNotNone(datos.ultima_copia())   # y ya hay copia


class TestLineasDanadas(Carpeta):
    def test_se_apartan_sin_borrar(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"))
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write('{"ts": "2026-10-27T18:05:00+01:00", "fich')   # corte a mitad de escritura
        self.escribir(entrada("2026-10-27T18:09:00+01:00", "I02"))
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write('{"ts": "2026-10-27T18:10:00+01:00", "ficha": "I03", "nota": 9}\n')   # nota imposible
        datos.copiar("antes", hoy=date(2026, 10, 27))
        avisos = datos.al_arrancar(git=False)
        self.assertEqual(len(avisos), 1, avisos)
        self.assertIn("2 lineas danadas de registro.jsonl", avisos[0])
        self.assertEqual([e["ficha"] for e in registro.leer(estricto=True)], ["I01", "I02"])
        apartado = self.tmp / f"apartado-{date.today().isoformat()}.jsonl"
        self.assertEqual(len(apartado.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(datos.faltan(), {})   # lo apartado no cuenta como perdido
        self.assertEqual(datos.al_arrancar(git=False), [])   # la segunda vez, nada que decir
        textos = [t for _, t in datos.resumen(git=False)]
        self.assertTrue(any("2 lineas apartadas" in t for t in textos), textos)


class TestRevisarRegistro(Carpeta):
    def test_duplicados_futuros_y_correcciones(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"),
                      entrada("2026-10-27T18:05:00+01:00"),                  # duplicado sin forzar
                      entrada("2026-10-27T18:06:00+01:00", forzado=True),    # repetido a proposito
                      entrada("2026-10-27T18:07:00+01:00", motivo=registro.CORRECCION, corrige="nada"),
                      entrada("2099-01-01T10:00:00+01:00", "I02"))
        rev = datos.revisar_registro()
        self.assertEqual(rev["duplicados"], [("I01", 1, date(2026, 10, 27))])
        self.assertEqual((rev["futuros"], rev["huerfanas"], rev["intentos"]), (1, 1, 4))

    def test_forzar_queda_marcado(self):
        from calculo.fichas import cargar
        v = cargar()["I01"].variante(1)
        sesion.registrar(v, v.respuesta_modelo, 3, 0, ruta=self.ruta)
        sesion.registrar(v, v.respuesta_modelo, 3, 0, ruta=self.ruta, forzar=True)
        e = registro.leer(self.ruta)
        self.assertNotIn("forzado", e[0])
        self.assertTrue(e[1]["forzado"])
        self.assertEqual(datos.revisar_registro(self.ruta)["duplicados"], [])


class TestEscrituraComprobada(Carpeta):
    def test_disco_lleno_no_corrompe(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"))
        antes = self.ruta.read_bytes()
        abrir = open

        def abrir_lleno(ruta, modo="r", *a, **k):
            f = abrir(ruta, modo, *a, **k)
            if "a" in modo:
                escribir = f.write

                def a_medias(texto):
                    escribir(texto[: len(texto) // 2])
                    f.flush()
                    raise OSError(errno.ENOSPC, "No space left on device")
                f.write = a_medias
            return f
        with mock.patch("calculo.registro.open", abrir_lleno, create=True), \
                mock.patch.object(registro.time, "sleep"):
            with self.assertRaises(registro.ErrorRegistro) as e:
                registro.anadir(entrada("2026-10-27T18:05:00+01:00", "I02"), self.ruta)
        self.assertIn("el disco esta lleno", str(e.exception))
        self.assertIn("Lo anterior sigue intacto", str(e.exception))
        self.assertEqual(self.ruta.read_bytes(), antes)   # sin media linea
        self.assertFalse(self.ruta.with_name("registro.jsonl.lock").exists())
        self.escribir(entrada("2026-10-27T18:06:00+01:00", "I03"))   # y despues se escribe bien
        self.assertEqual([e["ficha"] for e in registro.leer(estricto=True)], ["I01", "I03"])

    def test_fsync_falla_se_reintenta(self):
        reales = os.fsync
        llamadas = []

        def fsync(fd):
            llamadas.append(fd)
            if len(llamadas) == 1:
                raise OSError(errno.EIO, "fallo de E/S")
            return reales(fd)
        with mock.patch.object(registro.os, "fsync", fsync), mock.patch.object(registro.time, "sleep"):
            registro.anadir(entrada("2026-10-27T18:00:00+01:00"), self.ruta)
        self.assertEqual(len(llamadas), 2)
        self.assertEqual(len(self.lineas()), 1)   # una sola linea, no dos

    def test_permiso_denegado(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"))
        antes = self.ruta.read_bytes()
        os.chmod(self.ruta, stat.S_IREAD)
        try:
            with mock.patch.object(registro.time, "sleep"), self.assertRaises(registro.ErrorRegistro) as e:
                registro.anadir(entrada("2026-10-27T18:05:00+01:00", "I02"), self.ruta)
        finally:
            os.chmod(self.ruta, stat.S_IREAD | stat.S_IWRITE)
        self.assertIn("permiso denegado", str(e.exception))
        self.assertEqual(self.ruta.read_bytes(), antes)

    def test_relectura_que_no_cuadra(self):
        reales = os.fsync

        def fsync_y_pisar(fd):   # alguien trunca el fichero justo despues de escribir
            reales(fd)
            os.ftruncate(fd, 0)
        with mock.patch.object(registro.os, "fsync", fsync_y_pisar), mock.patch.object(registro.time, "sleep"), \
                self.assertRaises(registro.ErrorRegistro) as e:
            registro.anadir(entrada("2026-10-27T18:00:00+01:00"), self.ruta)
        self.assertIn("no aparece al releer", str(e.exception))


ESCRITOR = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[2])
    from calculo import registro
    i = 0
    while True:
        i += 1
        registro.anadir({"ts": "2026-10-27T18:00:00+01:00", "ficha": "I01", "semilla": i, "nota": 3,
                         "relleno": "x" * 4000}, sys.argv[1])
""")


class TestMatarAMitad(Carpeta):
    def test_matar_mientras_escribe(self):
        """terminate() (TerminateProcess) en mitad de un bucle de escrituras: el
        registro sigue legible y como mucho la ultima linea queda apartada."""
        guion = self.tmp / "escritor.py"
        guion.write_text(ESCRITOR, encoding="utf-8")
        for espera in (0.6, 0.9, 1.3):
            self.ruta.unlink(missing_ok=True)
            p = subprocess.Popen([sys.executable, "-B", str(guion), str(self.ruta), str(RAIZ)])
            fin = time.monotonic() + 20
            while not self.ruta.exists() and time.monotonic() < fin:
                time.sleep(0.05)
            time.sleep(espera)
            p.terminate()
            p.wait(10)
            todas = [x for x in self.ruta.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
            validas = registro.leer(self.ruta)
            self.assertGreater(len(validas), 0)
            self.assertGreaterEqual(len(validas), len(todas) - 1)   # como mucho la ultima, rota
            apartadas = datos.apartar_danadas()
            self.assertLessEqual(sum(apartadas.values()), 1)
            self.assertEqual(len(registro.leer(self.ruta, estricto=True)), len(validas))
            semillas = [e["semilla"] for e in validas]
            self.assertEqual(semillas, list(range(1, len(semillas) + 1)))   # ninguna perdida por el medio
            # el cerrojo del proceso muerto no bloquea la siguiente escritura
            self.escribir(entrada("2026-10-27T19:00:00+01:00", "I02"))
            for f in self.tmp.glob("apartado-*.jsonl"):
                f.unlink()


class TestResumenYDoctor(Carpeta):
    def test_resumen_llano(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"), entrada("2026-10-27T18:05:00+01:00", "I02"))
        textos = [t for _, t in datos.resumen(git=False)]
        self.assertIn("datos: 2 intentos guardados en usuario/datos/registro.jsonl", textos)
        self.assertTrue(any("aun no hay ninguna copia" in t for t in textos))
        datos.copiar("arranque")
        r = datos.resumen(git=False)
        self.assertTrue(any(ok is True and "comprobada (SHA256 bien)" in t and "(hoy)" in t for ok, t in r), r)

    def test_orden_datos(self):
        self.escribir(entrada("2026-10-27T18:00:00+01:00"))
        salida = io.StringIO()
        with redirect_stdout(salida), mock.patch.object(datos, "sin_subir", return_value=(0, 0)), \
                self.assertRaises(SystemExit) as fin:
            practica.main(["datos", "--copiar"])
        self.assertEqual(fin.exception.code, 0)
        texto = salida.getvalue()
        self.assertIn("Copia hecha en", texto)
        self.assertIn("1 intento guardado", texto)
        self.assertIn("Tus datos estan bien.", texto)

    def test_gitignore_no_excluye_datos(self):
        self.assertEqual(datos.ignorados(), [])

    def test_sin_subir(self):
        hace = time.time()
        r = subprocess.CompletedProcess([], 0, stdout=f"{int(hace - 3 * 86400)}\n{int(hace)}\n", stderr="")
        with mock.patch.object(datos, "_git", return_value=r):
            self.assertEqual(datos.sin_subir(hace), (2, 3))

    def test_doctor_rapido_sin_git(self):
        textos = [t for _, t in doctor.revisar(rapido=True)]
        self.assertTrue(any("fichas cargadas" in t for t in textos))
        self.assertFalse(any(t.startswith("remoto") or t.startswith("datos:") for t in textos))

    def test_cerrar_hace_copia(self):
        from calculo.fichas import cargar
        v = cargar()["I01"].variante(1)
        sesion.registrar(v, v.respuesta_modelo, 3, 0, ruta=self.ruta)
        sesion.cerrar(registro.ahora().date(), cargar(), git=False, ruta=self.ruta, diario=self.tmp / "d.md")
        self.assertIsNotNone(datos.ultima_copia())


class TestArranqueSinConsola(unittest.TestCase):
    def args(self, **k):
        base = {"minimo": False, "prueba": False, "captura": None, "respaldo_terminal": True}
        return mock.Mock(**{**base, **k})

    def test_respaldo_si_no_abre(self):
        from calculo import ventana
        with mock.patch.object(ventana, "abrir", return_value=ventana.SIN_VENTANA), \
                mock.patch.object(practica, "_abrir_terminal") as terminal, redirect_stdout(io.StringIO()):
            self.assertEqual(practica._ventana(self.args(minimo=True)), 3)
        terminal.assert_called_once_with(True)

    def test_sin_respaldo_si_abre_o_es_prueba(self):
        from calculo import ventana
        for codigo, extra in ((0, {}), (3, {"prueba": True}), (3, {"respaldo_terminal": False})):
            with mock.patch.object(ventana, "abrir", return_value=codigo), \
                    mock.patch.object(practica, "_abrir_terminal") as terminal, redirect_stdout(io.StringIO()):
                practica._ventana(self.args(**extra))
            terminal.assert_not_called()

    def test_respaldo_si_falta_pywebview(self):
        with mock.patch.dict(sys.modules, {"webview": None}), \
                mock.patch.object(practica, "_abrir_terminal") as terminal, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as fin:
                practica.main(["ventana", "--respaldo-terminal"])
        self.assertEqual(fin.exception.code, 3)
        terminal.assert_called_once()

    def test_abrir_terminal_consola_nueva(self):
        with mock.patch.object(practica.subprocess, "Popen") as popen, redirect_stdout(io.StringIO()):
            practica._abrir_terminal(minimo=True)
        args, k = popen.call_args
        self.assertEqual(args[0][:2], ["cmd.exe", "/c"])
        self.assertTrue(args[0][2].endswith("Terminal.bat"))
        self.assertEqual(args[0][3:], ["--minimo"])
        self.assertEqual(k["creationflags"], subprocess.CREATE_NEW_CONSOLE)

    def test_pythonw_sin_stdout_va_al_log(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None), \
                    mock.patch.object(practica, "CACHE", tmp / ".cache"):
                practica._sin_consola()
                print("hola desde pythonw")
                print("error", file=sys.stderr)
            log = (tmp / ".cache" / "servicio.log").read_text(encoding="utf-8")
            self.assertIn("hola desde pythonw", log)
            self.assertIn("error", log)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pythonw_de_verdad_sin_consola(self):
        """El proceso real con pythonw: `racha` imprime sin romperse (stdout None)."""
        pyw = Path(sys.executable).with_name("pythonw.exe")
        if not pyw.exists():
            self.skipTest("sin pythonw")
        tmp = Path(tempfile.mkdtemp())
        try:
            guion = tmp / "g.py"
            guion.write_text(textwrap.dedent(f"""
                import sys
                sys.path.insert(0, {str(RAIZ)!r})
                import practica
                practica.CACHE = __import__("pathlib").Path({str(tmp / '.cache')!r})
                practica._sin_consola()
                print("impreso sin consola")
                sys.stdout.write("y con write\\n")
            """), encoding="utf-8")
            r = subprocess.run([str(pyw), str(guion)], cwd=RAIZ, timeout=60)
            self.assertEqual(r.returncode, 0)
            log = (tmp / ".cache" / "servicio.log").read_text(encoding="utf-8")
            self.assertIn("impreso sin consola", log)
            self.assertIn("y con write", log)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_git_de_cerrar_sin_consola(self):
        with mock.patch.object(sesion.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            sesion._git(date.today(), 1)
        self.assertEqual(run.call_args.kwargs.get("creationflags"), subprocess.CREATE_NO_WINDOW)


class TestBats(unittest.TestCase):
    def test_terminal_pasa_argumentos(self):
        texto = (rutas.RAIZ / "otras-opciones" / "Terminal.bat").read_text(encoding="utf-8")
        self.assertIn("practica.py hoy %*", texto)

    def test_practicar_usa_doctor_rapido(self):
        texto = (rutas.RAIZ / "Practicar.bat").read_text(encoding="utf-8")
        comprobar = texto[texto.index(":comprobar"):texto.index(":practicar")]
        self.assertEqual(comprobar.count("practica.py doctor --rapido >nul"), 2)

    def test_comprobar_datos_bat(self):
        datos_ = (rutas.RAIZ / "otras-opciones" / "Comprobar-datos.bat").read_bytes()
        self.assertEqual(datos_.count(b"\n"), datos_.count(b"\r\n"))
        texto = datos_.decode("utf-8")
        self.assertIn("chcp 65001 >nul <nul", texto)
        self.assertIn("practica.py datos", texto)


if __name__ == "__main__":
    unittest.main()
