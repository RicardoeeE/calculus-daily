"""Regresiones: lector, etiquetas, registro, tutela, git, progreso y cola."""
import builtins
import io
import json
import random
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

import sympy as sp

import practica
from calculo import registro, sesion, tutela
from calculo.expresiones import X, leer
from calculo.fichas import cargar
from calculo.planificador import (
    PLANIFICADOR, abiertas_por_examen, cola, cupos, dominio, estados, fecha_proxima, progreso,
)
from calculo.sesion import YaRegistrado, cerrar, comprobar, informe, registrar
from tests.test_planificador import entrada

FICHAS = cargar()


class TestLector(unittest.TestCase):
    """Como teclea un alumno de verdad."""

    def test_productos_sin_parentesis(self):
        for texto, esperado in {
            "sen x cos x": sp.sin(X) * sp.cos(X), "2 sen x cos x": 2 * sp.sin(X) * sp.cos(X),
            "ln x · x": X * sp.log(X), "tg x sec x": sp.tan(X) * sp.sec(X),
            "cos x sen x": sp.sin(X) * sp.cos(X),
        }.items():
            with self.subTest(texto=texto):
                self.assertEqual(sp.simplify(leer(texto)[0] - esperado), 0)

    def test_exponencial_sin_parentesis(self):
        for texto, esperado in {"e^2x": sp.exp(2 * X), "e^-4x": sp.exp(-4 * X), "x e^3x": X * sp.exp(3 * X),
                                "e^x^2": sp.exp(X**2), "3e^x": 3 * sp.exp(X)}.items():
            with self.subTest(texto=texto):
                self.assertEqual(sp.simplify(leer(texto)[0] - esperado), 0)

    def test_pegado_pi_coma_y_constante(self):
        for texto, esperado in {"senx+xcosx": sp.sin(X) + X * sp.cos(X), "sen2x": sp.sin(2 * X),
                                "lnx": sp.log(X), "cos3x": sp.cos(3 * X), "π/4": sp.pi / 4,
                                "2,5x": sp.Rational(5, 2) * X}.items():
            with self.subTest(texto=texto):
                self.assertEqual(sp.simplify(leer(texto)[0] - esperado), 0)
        for texto in ("ln|x| + c", "C + ln|x|", "ln|x| - C"):
            self.assertTrue(leer(texto, quitar_constante=True)[1], texto)

    def test_primitiva_de_libro(self):
        v = FICHAS["T-SEN2"].construir({})
        self.assertTrue(comprobar(v, "x/2 - (sen(3x) cos(3x))/6 + C").correcto)
        v = FICHAS["P-EXPLIN"].construir({"a": 2})
        self.assertTrue(comprobar(v, "e^2x/2 + C").correcto)

    def test_potencial_con_igual_c(self):
        v = FICHAS["PO-POLI"].construir({"a": 1, "b": 1, "c": 2})
        for texto in ("x^2 y^2 + x + 2y = C", "F = x^2 y^2 + x + 2y", "F(x, y) = x^2y^2 + x + 2y + C"):
            self.assertTrue(comprobar(v, texto).correcto, texto)

    def test_he_leido(self):
        r = comprobar(FICHAS["I02"].construir({}), "ln|x| + C")
        self.assertEqual(r.leido, "ln|x| + C")


class TestEtiquetas(unittest.TestCase):
    """Con nombres se empareja por nombre, no por orden."""

    def test_algebra(self):
        v = FICHAS["AL-CUAD"].construir({"h": 1, "k": 9})
        self.assertTrue(comprobar(v, "k = 9, h = 1").correcto)
        self.assertFalse(comprobar(v, "k = 1, h = 9").correcto)
        v = FICHAS["AL-FRAC"].construir({"n": 1, "p": 1, "q": -1})
        self.assertTrue(comprobar(v, "A = 0,5, B = -0,5").correcto)

    def test_exacta(self):
        v = FICHAS["EX-NO"].construir({})
        self.assertTrue(comprobar(v, "∂N/∂x = 3x^2, ∂M/∂y = x").correcto)
        self.assertFalse(comprobar(v, "∂N/∂x = x, ∂M/∂y = 3x^2").correcto)
        self.assertTrue(comprobar(FICHAS["EX-EXP"].construir({}), "2xe^(x^2) = 2xe^(x^2)").correcto)


class TestDatos(unittest.TestCase):
    """Registro y diario sin duplicados; Ctrl+C; pistas anotadas."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.parches = [mock.patch.object(registro, "RUTA", self.tmp / "registro.jsonl"),
                        mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
                        mock.patch.object(practica, "CACHE", self.tmp / ".cache"),
                        mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
                        mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones")]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def test_registrar_dos_veces(self):
        v = FICHAS["I01"].variante(1)
        registrar(v, "x^2/2 + C", 3, 0)
        with self.assertRaises(YaRegistrado):
            registrar(v, "x^2/2 + C", 3, 0)
        self.assertEqual(len(registro.leer()), 1)

    def test_cerrar_dos_veces_no_duplica(self):
        registrar(FICHAS["I01"].variante(1), "x^2/2 + C", 3, 0)
        dia = date.today()
        cerrar(dia, FICHAS, git=False)
        registrar(FICHAS["I02"].variante(1), "ln|x| + C", 3, 0)
        cerrar(dia, FICHAS, git=False)
        texto = (self.tmp / "sesiones.md").read_text(encoding="utf-8")
        self.assertEqual(texto.count(f"## {dia.isoformat()} - Practica (motor)"), 1)
        self.assertIn("2 ejercicios", texto)

    def test_ctrl_c_cierra_lo_hecho(self):
        respuestas = iter(["3"])

        def entrada_teclado(_):
            try:
                return next(respuestas)
            except StopIteration:
                raise KeyboardInterrupt
        with mock.patch.object(builtins, "input", entrada_teclado), redirect_stdout(io.StringIO()) as out:
            practica.sesion_interactiva(FICHAS, date.today(), minimo=True, git=False)
        self.assertIn("Sesion parada", out.getvalue())

    def test_pistas_anotadas_por_el_motor(self):
        def correr(*args):
            with redirect_stdout(io.StringIO()) as out:
                practica.main(list(args))
            return out.getvalue()
        x = next(c for c in json.loads(correr("cola")) if c["tipo"] == "integral")
        correr("pista", x["ficha"], str(x["semilla"]), "4")
        v = FICHAS[x["ficha"]].variante(x["semilla"])
        r = json.loads(correr("registrar", x["ficha"], str(x["semilla"]), "--confianza", "3",
                              "--pistas", "0", "--respuesta", v.respuesta_modelo))
        self.assertEqual(r["pistas"], 4)
        self.assertEqual(r["nota"], 1)  # vio la solucion: no cuenta como acierto
        self.assertNotEqual(registro.leer()[0]["motivo"], "")


class TestTutela(TestDatos):
    """Modo independiente: reclamaciones, quejas, sensaciones y revision semanal."""

    def test_reclamacion(self):
        v = FICHAS["I01"].variante(1)
        e, _ = registrar(v, "x*x/2 + 0", 3, 0, reclamo=True)  # es correcta: no hace falta reclamar
        self.assertNotIn("reclamo", e)
        v2 = FICHAS["I02"].variante(1)
        e, _ = registrar(v2, "ln(x)·1", 3, 0, reclamo=True)  # correcta salvo |x|: se acepta con aviso
        self.assertTrue(e["correcto"])
        v3 = FICHAS["I03"].variante(1)
        e, _ = registrar(v3, "x + 2 ln x - 1 + 1/x", 3, 0, reclamo=True)
        self.assertTrue(e["reclamo"])
        self.assertEqual(e["nota"], 2)  # provisional: no cuenta como fallo
        pend = tutela.pendientes()
        self.assertEqual([p["tipo"] for p in pend], ["reclamo"])
        tutela.resolver(pend[0]["id"], "era un error suyo: sobra 1/x")
        self.assertEqual(tutela.pendientes(), [])

    def test_queja_y_revision(self):
        tutela.anotar("queja", texto="el ejercicio 3 era demasiado largo")
        dia = date.today()
        for d in range(4):
            registrar(FICHAS["P-POT"].variante(d), "x^3/3", 3, 0)
            # simula dias distintos moviendo la fecha de la ultima linea
            lineas = (self.tmp / "registro.jsonl").read_text(encoding="utf-8").splitlines()
            e = json.loads(lineas[-1])
            e["ts"] = datetime.combine(dia - timedelta(days=d + 1), time(18)).astimezone().isoformat()
            lineas[-1] = json.dumps(e)
            (self.tmp / "registro.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        tutela.anotar("sensacion", valor=2, texto="cansado")
        self.assertTrue(tutela.toca_revision(dia, registro.leer()))
        texto = tutela.revision(dia, FICHAS)
        self.assertIn("demasiado largo", texto)
        self.assertIn("cansado", texto)
        self.assertTrue((self.tmp / "revisiones" / f"{dia.isoformat()}.md").exists())
        self.assertFalse(tutela.toca_revision(dia, registro.leer()))


class TestDiagnostico(unittest.TestCase):
    def test_errores_tipicos(self):
        from calculo.diagnostico import diagnosticar
        casos = [
            ("S-X3EXP", {}, "e^(x^4) + C", "falta dividir entre 4"),
            ("P-SENLIN", {"a": 3}, "cos(3x)/3 + C", "signo"),
            ("I01", {}, "1", "derivado en vez de integrar"),
            ("DC-EXP", {"a": 1, "b": 1}, "e^(x^2 + x)", "cadena"),
            ("DPR-XSEN", {"n": 1, "a": 1}, "cos(x)", "f'·g + f·g'"),
            ("PC-POLI-Y", {"a": 3, "b": 1, "c": 2}, "6xy + y^3 + 2", "respecto a x"),
            ("DF-ISOTERMO", {"k": 2, "v1": 1, "v2": 3}, "-2 ln 3", "signo cambiado"),
            ("AL-CUAD", {"h": 3, "k": 4}, "-3, 4", "solo falla el signo"),
            ("T2-CAR-REAL", {"r1": 2, "r2": -3}, "-2, 3", "Signos cambiados"),
        ]
        for fid, p, resp, clave in casos:
            with self.subTest(ficha=fid):
                texto = " ".join(diagnosticar(FICHAS[fid].construir(p), resp))
                self.assertIn(clave, texto)


class TestGit(unittest.TestCase):
    """No subir marcas de conflicto; commit solo de los datos."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.raiz, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.raiz, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.raiz, check=True)
        (self.raiz / "otro.md").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "otro.md"], cwd=self.raiz, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "inicio"], cwd=self.raiz, check=True)

    def test_marcas_de_conflicto(self):
        (self.raiz / "usuario" / "datos").mkdir(parents=True)
        (self.raiz / "usuario" / "datos" / "registro.jsonl").write_text("<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> x\n", encoding="utf-8")
        with mock.patch.object(sesion, "RAIZ", self.raiz):
            mensaje = sesion._git(date.today(), 1)
        self.assertIn("marcas de conflicto", mensaje)

    def test_commit_solo_de_los_datos(self):
        (self.raiz / "usuario" / "datos").mkdir(parents=True)
        (self.raiz / "usuario" / "datos" / "registro.jsonl").write_text("{}\n", encoding="utf-8")
        (self.raiz / "otro.md").write_text("cambio ajeno", encoding="utf-8")
        subprocess.run(["git", "add", "otro.md"], cwd=self.raiz, check=True)
        with mock.patch.object(sesion, "RAIZ", self.raiz):
            mensaje = sesion._git(date.today(), 1)
        self.assertIn("commit hecho", mensaje)
        cambiados = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=self.raiz,
                                   capture_output=True, text=True).stdout.split()
        self.assertEqual(cambiados, ["usuario/datos/registro.jsonl"])


class TestEscalera(unittest.TestCase):
    """Un alumno con poco acierto avanza, no retrocede y ninguna tecnica queda bloqueada."""

    def simular(self, dias, semilla=1, saltar=0.25):
        rng = random.Random(semilla)
        log, hechos = [], []
        inicio = date(2026, 11, 1)
        for d in range(dias):
            dia = inicio + timedelta(d)
            if rng.random() < saltar:
                continue
            hoy = cola(FICHAS, log, dia, calendario="no-existe.toml")
            hechos.append(len(hoy))
            for x in hoy:
                p = min(0.9, 0.55 + 0.0035 * d)  # alumno que mejora poco a poco
                u = rng.random()
                nota = 3 if u < p else (2 if u < p + 0.1 else 1)
                log.append(entrada(x.ficha, dia, nota))
        return log, hechos

    def test_alumno_flojo_avanza(self):
        log, hechos = self.simular(240)
        prog = progreso(FICHAS, log)
        self.assertGreaterEqual(prog.escalon["integral"], 3, prog.escalon)  # llega a partes
        self.assertGreaterEqual(sum(hechos) / len(hechos), 4.5)  # usa el cupo de 5

    def test_no_retrocede(self):
        a, b = FICHAS["P-POT"], FICHAS["I01"]
        d0 = date(2026, 11, 1)
        log = [entrada([a, b][i % 2], d0 + timedelta(i), 3) for i in range(4)]
        log += [entrada(FICHAS["L-RAIZ3"], d0, 3), entrada(FICHAS["L-LOGNEG"], d0, 3)] * 2
        alto = progreso(FICHAS, log).escalon["integral"]
        self.assertGreaterEqual(alto, 2)
        log += [entrada(a, d0 + timedelta(10 + i), 1) for i in range(6)]
        self.assertEqual(progreso(FICHAS, log).escalon["integral"], alto)

    def test_tecnica_de_una_ficha(self):
        f = FICHAS["DL-XSEN"]  # logaritmica: una sola ficha, una sola variante
        log = [entrada(f, date(2026, 11, 1) + timedelta(i), 3) for i in range(4)]
        self.assertTrue(dominio(log, "logaritmica", FICHAS).dominada)


class TestFechas(unittest.TestCase):
    """El intervalo no depende de la hora del dia."""

    def test_hora_no_cambia_intervalo(self):
        f = FICHAS["I01"]
        proximas = []
        for hora in (9, 21):
            log = [entrada(f, date(2026, 11, 1), 3, hora=20), entrada(f, date(2026, 11, 3), 3, hora=hora)]
            proximas.append(fecha_proxima(estados(log)["I01"]))
        self.assertEqual(proximas[0], proximas[1])


class TestCola(unittest.TestCase):
    """Examenes, requisitos, foco y orden de la cola."""

    def test_examen_abre_tecnicas(self):
        self.assertIn("caracteristica", abiertas_por_examen(date(2026, 10, 27)))
        self.assertNotIn("caracteristica", abiertas_por_examen(date(2026, 10, 1)))

    def test_requisitos(self):
        hoy = cola(FICHAS, [], date(2026, 10, 27))
        self.assertNotIn("PP-PROD-X", {x.ficha.id for x in hoy})
        self.assertEqual(FICHAS["PP-PROD-X"].requiere, ["comprobar_solucion"])

    def test_empieza_por_lo_seguro(self):
        log = [entrada(FICHAS["D01"], date(2026, 10, 15), 3)]
        hoy = cola(FICHAS, log, date(2026, 10, 27))
        self.assertEqual(hoy[0].ficha.id, "D01")

    def test_repaso_con_foco(self):
        """Un repaso vencido de un grupo sin plaza (derivadas en foco) sale igual."""
        log = [entrada(FICHAS["D01"], date(2026, 10, 15), 3)]
        self.assertIn("D01", {x.ficha.id for x in cola(FICHAS, log, date(2026, 10, 27))})

    def test_informe_con_parciales(self):
        with mock.patch.object(registro, "RUTA", Path(tempfile.mkdtemp()) / "r.jsonl"):
            texto = informe(date(2026, 10, 27), FICHAS)
        self.assertIn("PARCIALES Y EDOS", texto)
        self.assertIn("P2 EDOs", texto)


class TestOrdenSuperior(unittest.TestCase):
    """Fichas y verificadores de las EDOs de orden superior."""

    def test_raices(self):
        v = FICHAS["T2-CAR-COMP"].construir({"a": 2, "b": 3})
        for texto in ("2±3i", "2+3i, 2-3i", "2-3i; 2+3i"):
            self.assertTrue(comprobar(v, texto).correcto, texto)
        self.assertFalse(comprobar(v, "3±2i").correcto)

    def test_solucion_general(self):
        v = FICHAS["T2-GEN-REAL"].construir({"r1": 2, "r2": -3})
        self.assertTrue(comprobar(v, "y = c1e^(-3x) + c2 e^(2x)").correcto)
        r = comprobar(v, "C1 e^(2x) + C2 e^(2x)")
        self.assertFalse(r.correcto)
        self.assertIn("proporcionales", r.avisos[0])

    def test_hay_fichas_de_la_p2(self):
        tecnicas = {f.tecnica for f in FICHAS.values()}
        for t in ("caracteristica", "comprobar_solucion", "wronskiano", "forma_yp", "pvi"):
            self.assertIn(t, tecnicas)


if __name__ == "__main__":
    unittest.main()
