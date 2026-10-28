"""Prueba de nivel (seleccion adaptativa, registro, progreso, modo revisor, sesion)."""
import builtins
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import practica
from calculo import planificador, registro, rutas, sesion, tutela
from calculo.fichas import cargar
from calculo.planificador import (
    NIVEL_LIMITE, cola, dominio, escalon_abierto, nivel_disponible, peldanos_nivel, progreso, resumen_nivel,
    siguiente_nivel,
)

FICHAS = cargar()
MALA = "x^99"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.parches = [
            mock.patch.object(registro, "RUTA", self.tmp / "registro.jsonl"),
            mock.patch.object(sesion, "DIARIO", self.tmp / "sesiones.md"),
            mock.patch.object(practica, "CACHE", self.tmp / ".cache"),
            mock.patch.object(tutela, "NOTAS", self.tmp / "notas.jsonl"),
            mock.patch.object(tutela, "REVISIONES", self.tmp / "revisiones"),
        ]
        for p in self.parches:
            p.start()
        self.dia = date.today()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def siguiente(self, n=10):
        return siguiente_nivel(FICHAS, registro.leer(), self.dia, n)

    def hacer(self, x, bien=True, pistas=0, motivo="nivel"):
        v = x.ficha.variante(x.semilla)
        resp = v.respuesta_modelo if bien else MALA
        if not bien and sesion.comprobar(v, MALA).error:
            # Una respuesta ilegible ya no se registra; el fallo es un «no lo se».
            return sesion.registrar(v, None, 3, pistas, 30, rendido=True, motivo=motivo)[0]
        return sesion.registrar(v, resp, 3, pistas, 30, motivo=motivo)[0]

    def prueba(self, fallan=(), n=10):
        """Recorre la prueba entera; `fallan`: grupos en los que se falla siempre. Devuelve las fichas."""
        vistas = []
        while (x := self.siguiente(n)) is not None:
            vistas.append(x.ficha)
            self.hacer(x, bien=x.ficha.grupo not in fallan)
        return vistas


class TestSeleccion(Base):
    def test_empieza_por_el_escalon_1_de_cada_grupo(self):
        grupos = []
        for _ in range(4):
            x = self.siguiente()
            self.assertEqual(x.motivo, "nivel")
            self.assertEqual(x.ficha.escalon, 1)
            grupos.append(x.ficha.grupo)
            self.hacer(x)
        self.assertEqual(grupos, ["algebra", "derivada", "integral", "parcial"])

    def test_todo_acertado_sube_y_se_para_en_10(self):
        vistas = self.prueba()
        self.assertEqual(len(vistas), 10)
        self.assertIsNone(self.siguiente())
        por_grupo = {g: [f.escalon for f in vistas if f.grupo == g] for g in planificador.GRUPOS_NIVEL}
        self.assertEqual(por_grupo["algebra"], [1])                 # solo tiene un escalon
        self.assertEqual(por_grupo["derivada"], [1, 1, 2])           # el escalon 1 pide 2 aciertos (la mitad de 3)
        self.assertEqual(por_grupo["integral"], [1, 1, 2])
        self.assertEqual(por_grupo["parcial"], [1, 2, 3])
        for g in ("derivada", "integral"):                           # tecnicas distintas en el mismo escalon
            e1 = [f.tecnica for f in vistas if f.grupo == g and f.escalon == 1]
            self.assertEqual(len(set(e1)), 2)
        self.assertTrue(all(not f.larga and not f.requiere for f in vistas))

    def test_un_fallo_detiene_ese_grupo(self):
        vistas = self.prueba(fallan=("derivada",))
        self.assertEqual(sum(1 for f in vistas if f.grupo == "derivada"), 1)
        # Los demas siguen hasta llenar los 10.
        self.assertEqual(len(vistas), 10)

    def test_todo_fallado_son_4_ejercicios(self):
        vistas = self.prueba(fallan=planificador.GRUPOS_NIVEL)
        self.assertEqual(len(vistas), 4)
        self.assertEqual(sorted(f.grupo for f in vistas), sorted(planificador.GRUPOS_NIVEL))

    def test_un_acierto_con_pistas_no_vale(self):
        x = self.siguiente()
        self.assertEqual(x.ficha.grupo, "algebra")
        self.hacer(x, bien=True, pistas=1)
        detenido, superadas, _, _ = planificador._estado_nivel(FICHAS, registro.leer(), "algebra")
        self.assertTrue(detenido)
        self.assertEqual(superadas, set())
        self.assertNotEqual(self.siguiente().ficha.grupo, "algebra")
        self.assertEqual(progreso(FICHAS, registro.leer()).por_nivel, set())

    def test_n_menor_limita(self):
        self.assertEqual(len(self.prueba(n=5)), 5)

    def test_determinista_y_puede_repetirse_la_llamada(self):
        a, b = self.siguiente(), self.siguiente()
        self.assertEqual((a.ficha.id, a.semilla), (b.ficha.id, b.semilla))

    def test_continua_donde_se_dejo(self):
        for _ in range(3):
            self.hacer(self.siguiente())
        x = self.siguiente()                                       # el cuarto: parcial
        self.assertEqual(x.ficha.grupo, "parcial")

    def test_peldanos(self):
        p = {g: [(e, k) for e, k, _ in peldanos_nivel(FICHAS, g)] for g in planificador.GRUPOS_NIVEL}
        self.assertEqual(p["algebra"], [(1, 1)])
        self.assertEqual(p["derivada"][0], (1, 2))
        self.assertEqual(p["integral"][:3], [(1, 2), (2, 1), (3, 1)])
        self.assertEqual(p["parcial"][-1], (6, 2))


class TestDisponibilidad(Base):
    def test_solo_con_menos_de_20_intentos(self):
        self.assertTrue(nivel_disponible([])[0])
        reales = [{"motivo": ""}] * (NIVEL_LIMITE - 1)
        self.assertTrue(nivel_disponible(reales)[0])
        ok, motivo = nivel_disponible(reales + [{"motivo": ""}])
        self.assertFalse(ok)
        self.assertIn("20", motivo)

    def test_los_intentos_de_la_prueba_no_cuentan(self):
        entradas = [{"motivo": ""}] * 15 + [{"motivo": "nivel"}] * 10
        self.assertTrue(nivel_disponible(entradas)[0])


class TestProgreso(Base):
    def test_no_gasta_cupo(self):
        antes = [x.ficha.id for x in cola(FICHAS, [], self.dia)]
        self.prueba()
        despues = cola(FICHAS, registro.leer(), self.dia)
        self.assertEqual(len(despues), 5)
        self.assertEqual(len(antes), 5)
        self.assertTrue(all(e["motivo"] == "nivel" and e["pistas"] == 0 for e in registro.leer()))

    def test_acertar_en_la_prueba_abre_escalones_sin_dominar(self):
        self.assertEqual(escalon_abierto(FICHAS, [], "integral"), 1)
        self.prueba()
        log = registro.leer()
        prog = progreso(FICHAS, log)
        # derivadas e integrales: pasaron el escalon 1 (2 tecnicas) -> abren el 2; parciales el 3 (1.o, 2.o superados)
        self.assertGreaterEqual(prog.escalon["derivada"], 2)
        self.assertGreaterEqual(prog.escalon["integral"], 2)
        self.assertGreaterEqual(prog.escalon["parcial"], 3)
        self.assertEqual(prog.dominadas, set())                     # «dominada» no se toca
        self.assertTrue(prog.por_nivel)
        for t in prog.por_nivel:
            self.assertFalse(dominio(log, t, FICHAS).dominada)
        self.assertTrue(prog.foco_apagado is False)                 # el foco sigue encendido

    def test_el_foco_no_se_apaga_por_la_prueba(self):
        self.prueba()
        self.assertTrue(planificador.foco_activo(FICHAS, registro.leer()))

    def test_sin_aciertos_no_abre_nada(self):
        self.prueba(fallan=planificador.GRUPOS_NIVEL)
        prog = progreso(FICHAS, registro.leer())
        self.assertEqual(set(prog.escalon.values()), {1})
        self.assertEqual(prog.por_nivel, set())

    def test_el_progreso_nunca_retrocede(self):
        self.prueba()
        log = registro.leer()
        alcanzado = progreso(FICHAS, log).escalon
        # Un mal periodo despues: fallos en todo lo que se acerto.
        extra = []
        for i, e in enumerate(list(log) * 2):
            m = dict(e, ts=f"2030-01-{1 + i % 28:02d}T18:00:00+01:00", nota=1, correcto=False, motivo="", pistas=0)
            extra.append(m)
        despues = progreso(FICHAS, log + extra).escalon
        for g, e in alcanzado.items():
            self.assertGreaterEqual(despues[g], e, g)
        # Y, a cada paso del registro, el escalon abierto solo sube.
        previo = {g: 1 for g in alcanzado}
        for k in range(1, len(log + extra) + 1):
            actual = progreso(FICHAS, (log + extra)[:k]).escalon
            for g in previo:
                self.assertGreaterEqual(actual[g], previo[g])
            previo = actual

    def test_resumen(self):
        self.prueba(fallan=("integral",))
        r = resumen_nivel(FICHAS, registro.leer(), self.dia)
        self.assertEqual(r["ejercicios"], 10)
        self.assertTrue(r["grupos"]["integral"]["detenido"])
        self.assertEqual(r["grupos"]["integral"]["escalon_antes"], 1)
        self.assertGreaterEqual(r["grupos"]["derivada"]["escalon_despues"], 2)

    def test_informe_marca_competente_por_la_prueba(self):
        self.prueba()
        texto = sesion.informe(self.dia, FICHAS)
        self.assertIn("competente (prueba de nivel)", texto)


class TestModoRevisor(Base):
    def _cola(self, *extra):
        salida = io.StringIO()
        with redirect_stdout(salida):
            practica.main(["nivel", "--cola", *extra])
        return json.loads(salida.getvalue())

    def test_va_de_uno_en_uno_y_se_registra_con_motivo(self):
        primero = self._cola()
        self.assertEqual(len(primero), 1)
        x = primero[0]
        self.assertEqual((x["motivo"], x["numero"], x["maximo"], x["escalon"]), ("nivel", 1, 10, 1))
        self.assertEqual(self._cola()[0]["ficha"], x["ficha"])           # sin registrar, es el mismo
        self.assertEqual(practica.motivo_en_cola(self.dia, x["ficha"], x["semilla"]), "nivel")
        v = FICHAS[x["ficha"]].variante(x["semilla"])
        with redirect_stdout(io.StringIO()):
            practica.main(["registrar", x["ficha"], str(x["semilla"]), "--confianza", "3",
                           "--respuesta", v.respuesta_modelo])
        self.assertEqual(registro.leer()[0]["motivo"], "nivel")
        segundo = self._cola()[0]
        self.assertNotEqual(segundo["ficha"], x["ficha"])
        self.assertEqual(segundo["numero"], 2)

    def test_al_acabar_devuelve_lista_vacia_y_el_cierre_guarda_el_resumen(self):
        while self._cola():
            x = self._cola()[0]
            v = FICHAS[x["ficha"]].variante(x["semilla"])
            with redirect_stdout(io.StringIO()):
                practica.main(["registrar", x["ficha"], str(x["semilla"]), "--confianza", "4",
                               "--respuesta", v.respuesta_modelo])
        self.assertEqual(len(registro.leer()), 10)
        with redirect_stdout(io.StringIO()) as sal:
            practica.main(["cerrar", "--sin-git"])
        self.assertIn("Prueba de nivel", sal.getvalue())
        md = self.tmp / "revisiones" / f"{self.dia.isoformat()}_nivel.md"
        self.assertTrue(md.exists())
        self.assertIn("10/10", md.read_text(encoding="utf-8"))

    def test_no_se_ofrece_con_20_intentos_salvo_forzar(self):
        for i in range(20):
            registro.anadir({"ts": f"2026-10-{1 + i % 25:02d}T18:00:00+02:00", "ficha": "D01", "nota": 3,
                             "tecnica": "potencia"})
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(self._cola(), [])
        self.assertIn("--forzar", err.getvalue())
        self.assertEqual(len(self._cola("--forzar")), 1)


class TestSesion(Base):
    def _correr(self, responder, forzar=False, n=10):
        """`responder(x, v)`: texto del resultado ante el ejercicio actual."""
        salida = io.StringIO()

        def entrada(prompt):
            if "Confianza" in prompt:
                return "3"
            x = siguiente_nivel(FICHAS, registro.leer(), self.dia, n)
            return responder(x, x.ficha.variante(x.semilla))

        with mock.patch.object(builtins, "input", entrada), redirect_stdout(salida):
            practica.sesion_nivel(FICHAS, self.dia, n, forzar, git=False)
        return salida.getvalue()

    def test_sesion_completa_sin_pistas_correccion_al_final_e_informe(self):
        def responder(x, v):
            return "" if x.ficha.grupo == "integral" else v.respuesta_modelo

        texto = self._correr(responder)
        self.assertNotIn("Pista:", texto)
        self.assertNotIn("Correcto.", texto)
        self.assertLess(texto.index("[1/hasta 10]"), texto.index("Correccion:"))
        self.assertIn("FALLO", texto)
        self.assertIn("CORRECTO", texto)
        self.assertIn("aqui se detuvo", texto)
        self.assertIn("Tu escalera:", texto)
        log = registro.leer()
        self.assertTrue(all(e["motivo"] == "nivel" and e["pistas"] == 0 for e in log))
        self.assertEqual(sum(1 for e in log if e["grupo"] == "integral"), 1)
        md = self.tmp / "revisiones" / f"{self.dia.isoformat()}_nivel.md"
        self.assertTrue(md.exists())
        contenido = md.read_text(encoding="utf-8")
        self.assertIn("Prueba de nivel", contenido)
        self.assertIn("(se detuvo)", contenido)
        self.assertIn("Solucion:", contenido)
        # La revision semanal no confunde el resumen con una revision.
        self.assertIsNone(tutela.ultima_revision())

    def test_parar_y_seguir_el_mismo_dia(self):
        respuestas = iter(["3", "", "3", "", "q"])      # 2 ejercicios en blanco (fallo), y para en el tercero
        # El algebra y las derivadas fallan en blanco: quedan 2 grupos detenidos.
        with mock.patch.object(builtins, "input", lambda p: next(respuestas)), redirect_stdout(io.StringIO()) as sal:
            practica.sesion_nivel(FICHAS, self.dia, 10, False, git=False)
        self.assertIn("Prueba parada", sal.getvalue())
        self.assertEqual(len(registro.leer()), 2)
        x = self.siguiente()
        self.assertEqual(x.ficha.grupo, "integral")      # continua con el tercer grupo

    def test_resultado_ilegible_se_vuelve_a_pedir_sin_corregir(self):
        respuestas = iter(["3", "(((", "q"])
        with mock.patch.object(builtins, "input", lambda p: next(respuestas)), redirect_stdout(io.StringIO()) as sal:
            practica.sesion_nivel(FICHAS, self.dia, 10, False, git=False)
        self.assertIn("No lo leo", sal.getvalue())
        self.assertEqual(registro.leer(), [])

    def test_no_se_ofrece_con_muchos_intentos(self):
        for i in range(20):
            registro.anadir({"ts": f"2026-10-{1 + i % 25:02d}T18:00:00+02:00", "ficha": "D01", "nota": 3,
                             "tecnica": "potencia"})
        with redirect_stdout(io.StringIO()) as sal:
            practica.sesion_nivel(FICHAS, self.dia, 10, False, git=False)
        self.assertIn("--forzar", sal.getvalue())
        self.assertEqual(len(registro.leer()), 20)


class TestLanzadorYDatos(unittest.TestCase):
    def test_lanzador(self):
        b = (rutas.RAIZ / "otras-opciones" / "Prueba-nivel.bat").read_bytes()
        self.assertIn(b"\r\n", b)
        self.assertNotIn(b"\n", b.replace(b"\r\n", b""))
        self.assertIn(b"chcp 65001 >nul <nul", b)
        self.assertIn(b"-m venv .venv", b)
        self.assertIn(b"practica.py nivel", b)

    def test_las_revisiones_se_suben_con_el_cierre(self):
        self.assertIn("usuario/revisiones", sesion._DATOS)

    def test_nivel_es_motivo_extra(self):
        self.assertIn("nivel", planificador.MOTIVOS_EXTRA)


if __name__ == "__main__":
    unittest.main()
