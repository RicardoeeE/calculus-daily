"""Grafo de tecnicas y repeticion implicita (revisiones virtuales de FSRS)."""
import copy
import random
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from calculo import planificador, registro, sesion
from calculo.fichas import ErrorFicha, cargar, cargar_grafo
from calculo.planificador import (
    calibracion, cola, dominio, estados, fecha_proxima, progreso, repasos_ahorrados, retenibilidad,
)

FICHAS = cargar()
D0 = date(2026, 11, 2)


def intento(ficha_id, dia, nota, motivo="", hora=18):
    f = FICHAS[ficha_id]
    ts = datetime.combine(dia, time(hora)).astimezone().isoformat()
    e = {"ts": ts, "ficha": f.id, "tipo": f.tipo, "grupo": f.grupo, "tecnica": f.tecnica,
         "nota": nota, "correcto": nota > 1, "pistas": 0}
    if motivo:
        e["motivo"] = motivo
    return e


def due(log, ficha_id, grafo=None):
    return estados(log, grafo)[ficha_id].due


class TestGrafo(unittest.TestCase):
    def test_el_grafo_real_carga_y_tiene_las_aristas_esperadas(self):
        g = cargar_grafo()
        self.assertEqual(set(g["partes"]), {"lineal", "potencia"})
        self.assertEqual(g["sustitucion"], ("cadena",))
        self.assertEqual(set(g["parcial_cadena"]), {"cadena", "producto"})
        self.assertEqual(g["exactitud"], ("constante",))
        self.assertEqual(g["potencial"], ("constante",))
        self.assertEqual(g["pvi"], ("caracteristica",))
        self.assertEqual(set(g["comprobar_solucion"]), {"producto", "cadena"})

    def test_toda_tecnica_nombrada_existe(self):
        tecnicas = {f.tecnica for f in FICHAS.values()}
        for t, contenidas in cargar_grafo().items():
            self.assertIn(t, tecnicas)
            self.assertTrue(set(contenidas) <= tecnicas, t)

    def _grafo(self, texto):
        carpeta = Path(tempfile.mkdtemp())
        (carpeta / "grafo.toml").write_text(texto, encoding="utf-8")
        return cargar_grafo(carpeta, FICHAS)

    def test_sin_fichero_es_vacio(self):
        self.assertEqual(cargar_grafo(Path(tempfile.mkdtemp()), FICHAS), {})

    def test_tecnica_inexistente(self):
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\ninventada = ["producto"]\n')
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\npartes = ["inventada"]\n')

    def test_ciclos_y_autoaristas(self):
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\npartes = ["producto"]\nproducto = ["partes"]\n')
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\npartes = ["sustitucion"]\nsustitucion = ["cadena"]\ncadena = ["partes"]\n')
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\npartes = ["partes"]\n')

    def test_formato_malo(self):
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\npartes = "producto"\n')
        with self.assertRaises(ErrorFicha):
            self._grafo('[contiene]\npartes = ["producto", "producto"]\n')

    def test_un_grafo_valido_distinto(self):
        g = self._grafo('[contiene]\npartes = ["producto", "cadena"]\n')
        self.assertEqual(g, {"partes": ("producto", "cadena")})


class TestImplicita(unittest.TestCase):
    PRODUCTO = "P-EXPLIN"   # contenida en partes (partes integra dv con un cambio lineal)
    PRODUCTO2 = "P-COSLIN"
    PARTES = "PA-XEXP"

    def test_ficha_de_producto_vencida_se_aplaza_tras_acertar_partes(self):
        base = [intento(self.PRODUCTO, D0, 3)]
        vence = fecha_proxima(estados(base)[self.PRODUCTO])
        dia = vence + timedelta(days=6)               # vencida desde hace 6 dias
        log = base + [intento(self.PARTES, dia, 3)]
        sin = estados(log, {})[self.PRODUCTO]
        con = estados(log)[self.PRODUCTO]
        self.assertEqual(fecha_proxima(sin), vence)
        self.assertGreater(fecha_proxima(con), dia)   # ya no esta vencida
        self.assertGreater(con.stability, sin.stability)
        self.assertEqual(repasos_ahorrados(log, dia), 1)

    def test_no_se_toca_si_no_estaba_vencida(self):
        base = [intento(self.PRODUCTO, D0, 3)]
        vence = fecha_proxima(estados(base)[self.PRODUCTO])
        log = base + [intento(self.PARTES, vence - timedelta(days=1), 3)]
        self.assertEqual(due(log, self.PRODUCTO), due(log, self.PRODUCTO, {}))
        self.assertEqual(estados(log)[self.PRODUCTO].stability, estados(log, {})[self.PRODUCTO].stability)
        self.assertEqual(repasos_ahorrados(log, vence), 0)

    def test_no_se_toca_con_nota_2(self):
        base = [intento(self.PRODUCTO, D0, 3)]
        dia = fecha_proxima(estados(base)[self.PRODUCTO]) + timedelta(days=6)
        for nota in (1, 2):
            log = base + [intento(self.PARTES, dia, nota)]
            self.assertEqual(due(log, self.PRODUCTO), due(log, self.PRODUCTO, {}), nota)
        log = base + [intento(self.PARTES, dia, 4)]       # un 4 si cuenta
        self.assertGreater(due(log, self.PRODUCTO), due(log, self.PRODUCTO, {}))

    def test_no_crea_tarjetas_de_fichas_nunca_vistas(self):
        log = [intento(self.PARTES, D0, 3), intento(self.PARTES, D0 + timedelta(days=30), 3)]
        self.assertEqual(set(estados(log)), {self.PARTES})
        # Tampoco cuenta una ficha de la contenida que solo se ve despues del acierto.
        log = [intento(self.PARTES, D0, 3), intento(self.PRODUCTO, D0 + timedelta(days=30), 3)]
        self.assertEqual(estados(log)[self.PRODUCTO].last_review, planificador._momento(log[1]))
        self.assertEqual(repasos_ahorrados(log, D0 + timedelta(days=30)), 0)

    def test_el_simulacro_no_cuenta(self):
        base = [intento(self.PRODUCTO, D0, 3)]
        dia = fecha_proxima(estados(base)[self.PRODUCTO]) + timedelta(days=6)
        log = base + [intento(self.PARTES, dia, 3, motivo="simulacro")]
        self.assertEqual(due(log, self.PRODUCTO), due(log, self.PRODUCTO, {}))
        # El examen y la prueba de nivel son intentos reales: si cuentan.
        for motivo in ("examen", "nivel", "repaso"):
            log = base + [intento(self.PARTES, dia, 3, motivo=motivo)]
            self.assertGreater(due(log, self.PRODUCTO), due(log, self.PRODUCTO, {}), motivo)

    def test_determinista(self):
        log = [intento(self.PRODUCTO, D0, 3), intento(self.PRODUCTO2, D0 + timedelta(days=1), 3),
               intento(self.PARTES, D0 + timedelta(days=20), 3), intento("PA-XCOS", D0 + timedelta(days=22), 4)]
        a, b = estados(log), estados(list(reversed(log)))
        self.assertEqual(set(a), set(b))
        for fid in a:
            self.assertEqual((a[fid].due, a[fid].stability, a[fid].difficulty),
                             (b[fid].due, b[fid].stability, b[fid].difficulty))
        c = estados(copy.deepcopy(log))
        self.assertEqual({k: v.due for k, v in a.items()}, {k: v.due for k, v in c.items()})

    def test_como_mucho_una_ficha_por_tecnica_contenida_y_por_entrada_la_menos_recordada(self):
        log = [intento(self.PRODUCTO, D0, 3), intento(self.PRODUCTO2, D0 + timedelta(days=3), 3)]
        dia = D0 + timedelta(days=30)
        momento = planificador._mediodia(dia)
        r = {fid: planificador.PLANIFICADOR.get_card_retrievability(estados(log)[fid], momento)
             for fid in (self.PRODUCTO, self.PRODUCTO2)}
        menos = min(r, key=r.get)
        mas = max(r, key=r.get)
        log.append(intento(self.PARTES, dia, 3))
        con, sin = estados(log), estados(log, {})
        self.assertGreater(con[menos].due, sin[menos].due)
        self.assertEqual(con[mas].due, sin[mas].due)
        # Un segundo acierto de partes otro dia mueve la que quedaba.
        log.append(intento("PA-XCOS", dia + timedelta(days=1), 3))
        # (la segunda, si sigue vencida; si no, no se toca: nunca mas de una por entrada)
        con2 = estados(log)
        movidas = sum(1 for fid in (self.PRODUCTO, self.PRODUCTO2) if con2[fid].due > estados(log, {})[fid].due)
        self.assertLessEqual(movidas, 2)
        self.assertEqual(len(planificador._reproducir(log)[1]), movidas)

    def test_solo_un_nivel_no_es_transitivo(self):
        g = {"partes": ("producto",), "producto": ("potencia",)}
        log = [intento("D01", D0, 3), intento("DPR-XEXP", D0, 3)]
        dia = D0 + timedelta(days=30)
        self.assertEqual(FICHAS["D01"].tecnica, "potencia")
        log.append(intento(self.PARTES, dia, 3))
        con, sin = estados(log, g), estados(log, {})
        self.assertGreater(con["DPR-XEXP"].due, sin["DPR-XEXP"].due)
        self.assertEqual(con["D01"].due, sin["D01"].due)          # la de potencia no se toca
        # Si el acierto es de producto, entonces si se mueve la de potencia.
        log.append(intento("DPR-XEXP", dia + timedelta(days=1), 3))
        self.assertGreater(estados(log, g)["D01"].due, estados(log, {})["D01"].due)

    def test_no_cuenta_como_intento_para_dominio_progreso_ni_calibracion(self):
        base = [intento(self.PRODUCTO, D0, 3)]
        dia = fecha_proxima(estados(base)[self.PRODUCTO]) + timedelta(days=6)
        log = base + [intento(self.PARTES, dia, 3), intento(self.PRODUCTO, dia + timedelta(days=9), 3)]
        original = copy.deepcopy(log)
        d = dominio(log, "lineal", FICHAS)
        self.assertEqual((d.intentos, d.aciertos), (2, 2.0))       # solo los reales
        self.assertEqual(calibracion(log)[0], 1)                    # un unico repaso real de PRODUCTO
        self.assertEqual(progreso(FICHAS, log).dominadas, set())
        self.assertEqual(log, original)                             # el registro no se toca
        self.assertEqual(repasos_ahorrados(log, dia + timedelta(days=9)), 1)

    def test_ahorro_solo_cuenta_los_ultimos_30_dias(self):
        base = [intento(self.PRODUCTO, D0, 3)]
        dia = fecha_proxima(estados(base)[self.PRODUCTO]) + timedelta(days=6)
        log = base + [intento(self.PARTES, dia, 3)]
        self.assertEqual(repasos_ahorrados(log, dia + timedelta(days=29)), 1)
        self.assertEqual(repasos_ahorrados(log, dia + timedelta(days=30)), 0)
        self.assertEqual(repasos_ahorrados(log, dia, grafo={}), 0)

    def test_la_cola_ve_el_aplazamiento(self):
        base = [intento("P-EXPLIN", D0, 3)]
        dia = fecha_proxima(estados(base)["P-EXPLIN"]) + timedelta(days=6)
        sin_acierto = cola(FICHAS, base, dia, calendario="no-existe.toml")
        self.assertIn("P-EXPLIN", [x.ficha.id for x in sin_acierto])
        con = base + [intento(self.PARTES, dia - timedelta(days=1), 3)]
        # Se acierta partes ayer: hoy el repaso de producto ya no esta vencido.
        hoy = cola(FICHAS, con, dia, calendario="no-existe.toml")
        self.assertNotIn(("P-EXPLIN", "repaso"), [(x.ficha.id, x.motivo) for x in hoy])


class TestImplicitaInforme(unittest.TestCase):
    def test_informe_muestra_los_repasos_ahorrados(self):
        tmp = Path(tempfile.mkdtemp())
        ruta = tmp / "registro.jsonl"
        base = [intento("P-EXPLIN", D0, 3)]
        dia = fecha_proxima(estados(base)["P-EXPLIN"]) + timedelta(days=3)
        for e in base + [intento("PA-XEXP", dia, 3)]:
            registro.anadir(e, ruta)
        texto = sesion.informe(dia, FICHAS, ruta=ruta)
        self.assertIn("Repeticion implicita: 1 repasos aplazados en los ultimos 30 dias", texto)
        vacio = sesion.informe(dia, FICHAS, ruta=tmp / "nada.jsonl")
        self.assertIn("Repeticion implicita: 0 repasos", vacio)


class TestImplicitaSimulacion(unittest.TestCase):
    """La misma simulacion de 100 dias, con y sin repeticion implicita: no empeora la carga."""

    def _correr(self, grafo):
        rng = random.Random(2026)
        log, retrasos = [], []
        inicio = date(2026, 10, 27)
        with mock.patch.object(planificador, "_grafo_defecto", lambda: grafo):
            for d in range(100):
                dia = inicio + timedelta(d)
                if rng.random() < 0.25:
                    continue
                hoy = cola(FICHAS, log, dia)
                tarjetas = estados(log)
                for x in hoy:
                    if x.motivo == "repaso":
                        retrasos.append((dia - fecha_proxima(tarjetas[x.ficha.id])).days)
                    p = min(0.95, 0.55 + 0.004 * d)
                    n = rng.choices([1, 2, 3, 4], weights=[1 - p, 0.15, p - 0.05, 0.05])[0]
                    log.append(intento(x.ficha.id, dia, n))
        return log, retrasos

    def test_no_empeora_la_carga(self):
        grafo = cargar_grafo()
        _, con = self._correr(grafo)
        _, sin = self._correr({})
        medio = lambda r: sum(r) / len(r)
        print(f"\n  implicita: repasos {len(sin)} -> {len(con)}, retraso medio {medio(sin):.2f} -> {medio(con):.2f} d, "
              f"maximo {max(sin)} -> {max(con)} d")
        self.assertLessEqual(len(con), len(sin))
        self.assertLessEqual(medio(con), medio(sin) + 0.05)


if __name__ == "__main__":
    unittest.main()
