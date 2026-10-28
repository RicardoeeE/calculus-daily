"""Medianoche a mitad de ejercicio, respuestas ilegibles y reclamaciones."""
import io
import json
from contextlib import redirect_stdout
from datetime import timedelta
from unittest import mock

import practica
from calculo import registro, servicio, sesion, tutela
from tests.test_servicio import FICHAS, Temporal


class TestMedianoche(Temporal):
    """Pista y fallo a las 23:58, registrar a las 00:01."""

    def setUp(self):
        super().setUp()
        self.noche = registro.ahora().replace(hour=23, minute=58, second=0)
        self.madrugada = self.noche + timedelta(minutes=3)
        with mock.patch.object(registro, "ahora", return_value=self.noche):
            item = self.s.cola()["ejercicios"][0]
        self.f, self.sem = item["ficha"], item["semilla"]
        self.v = FICHAS[self.f].variante(self.sem)

    def test_conserva_pistas_fallos_inicio_y_motivo(self):
        with mock.patch.object(registro, "ahora", return_value=self.noche), \
                mock.patch.object(servicio, "reloj", return_value=1000.0):
            self.s.mostrar(self.f, self.sem)
            self.s.pista(self.f, self.sem, 2)
            self.s.comprobar(self.f, self.sem, "0")
        with mock.patch.object(registro, "ahora", return_value=self.madrugada), \
                mock.patch.object(servicio, "reloj", return_value=1180.0):
            d = self.s.ejercicio(self.f, self.sem)
            self.assertEqual((d["pistas_vistas"], d["fallos"]), (2, 1))
            r = self.s.registrar(self.f, self.sem, 3, self.v.respuesta_modelo)
        self.assertEqual((r["pistas"], r["fallos"], r["segundos"], r["nota"]), (2, 1, 180, 2))
        e = registro.leer()[-1]
        self.assertNotEqual(e["motivo"], "fuera de cola")
        self.assertEqual(registro.fecha(e), self.madrugada.date())   # la hora real no se toca

    def test_revisor_sin_mostrar(self):
        """Por la linea de comandos no hay `mostrar`: la primera pista fija el dia."""
        with mock.patch.object(registro, "ahora", return_value=self.noche):
            self.s.pista(self.f, self.sem, 3)
        with mock.patch.object(registro, "ahora", return_value=self.madrugada):
            r = self.s.registrar(self.f, self.sem, 3, self.v.respuesta_modelo)
        self.assertEqual((r["pistas"], r["nota"]), (3, 2))

    def test_un_dia_despues_ya_no(self):
        with mock.patch.object(registro, "ahora", return_value=self.noche):
            self.s.pista(self.f, self.sem, 3)
        with mock.patch.object(registro, "ahora", return_value=self.noche + timedelta(days=2)):
            self.assertEqual(self.s.ejercicio(self.f, self.sem)["pistas_vistas"], 0)

    def test_la_cola_de_hoy_no_borra_lo_de_ayer(self):
        with mock.patch.object(registro, "ahora", return_value=self.noche):
            self.s.pista(self.f, self.sem, 2)
        with mock.patch.object(registro, "ahora", return_value=self.madrugada):
            self.s.cola()
            self.assertEqual(self.s.ejercicio(self.f, self.sem)["pistas_vistas"], 2)


class TestIlegible(Temporal):
    """Una respuesta que no se lee no es un fallo de nota 1."""

    def setUp(self):
        super().setUp()
        self.s = servicio.Sesion(FICHAS, cache=self.cache, seguro=False)

    def test_sesion_la_rechaza(self):
        with self.assertRaises(ValueError) as cm:
            self.s.registrar("D01", 0, 3, "4x^^^")
        self.assertIn("no se lee", str(cm.exception))
        self.assertEqual(registro.leer(), [])

    def test_ventana_recibe_ok_false(self):
        s = servicio.Sesion(FICHAS, cache=self.cache, seguro=True)
        r = s.registrar("D01", 0, 3, "4x^^^")
        self.assertFalse(r["ok"])
        self.assertIn("no se lee", r["error"])
        self.assertEqual(registro.leer(), [])

    def test_rendido_si_se_registra(self):
        self.assertEqual(self.s.registrar("D01", 0, 3, "4x^^^", rendido=True)["nota"], 1)

    def test_cli(self):
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()):
            practica.main(["registrar", "D01", "0", "--confianza", "3", "--respuesta", "4x^^^"])
        self.assertIn("No se registra", str(cm.exception.code))
        self.assertEqual(registro.leer(), [])


class TestReclamaciones(Temporal):
    """Reclamar tras ver la solucion daba nota 2; y `resolver` corrige la nota."""

    def setUp(self):
        super().setUp()
        self.s = servicio.Sesion(FICHAS, cache=self.cache, seguro=False)

    def test_reclamo_con_rendido_o_pista_4(self):
        with self.assertRaises(ValueError):
            self.s.registrar("D01", 0, 3, "4x^2", rendido=True, reclamo=True)
        self.s.pista("D01", 0, 4)
        with self.assertRaises(ValueError):
            self.s.registrar("D01", 0, 3, "4x^2", reclamo=True)
        with self.assertRaises(ValueError):
            sesion.registrar(FICHAS["D01"].variante(0), "4x^2", 3, 4, reclamo=True)
        self.assertEqual(registro.leer(), [])

    def _reclamar(self):
        r = self.s.registrar("D01", 0, 3, "4x^2", reclamo=True)
        self.assertEqual(r["nota"], 2)
        return tutela.pendientes()[0]["id"]

    def test_rechazar_deja_nota_1(self):
        id_ = self._reclamar()
        tutela.resolver(id_, "estaba mal: el exponente es 3", rechazar=True)
        self.assertEqual(tutela.pendientes(), [])
        entradas = registro.leer()
        self.assertEqual(len(entradas), 1)   # la correccion no cuenta como otro ejercicio
        self.assertEqual((entradas[0]["nota"], entradas[0]["correcto"]), (1, False))
        crudo = registro.leer(crudo=True)
        self.assertEqual(crudo[-1]["motivo"], "correccion")
        self.assertEqual(crudo[-1]["corrige"], crudo[0]["ts"])
        self.assertEqual(registro.fecha(entradas[0]), registro.fecha(crudo[0]))
        # FSRS la tiene en cuenta: el repaso se adelanta respecto a la nota 2.
        from calculo.planificador import estados, fecha_proxima
        con_2 = fecha_proxima(estados(crudo[:1])["D01"])
        con_1 = fecha_proxima(estados(entradas)["D01"])
        self.assertLessEqual(con_1, con_2)

    def test_aceptar_deja_nota_3(self):
        id_ = self._reclamar()
        tutela.resolver(id_, "el lector se equivoco", aceptar=True)
        e = registro.leer()[0]
        self.assertEqual((e["nota"], e["correcto"]), (3, True))

    def test_sin_decision_solo_cierra(self):
        id_ = self._reclamar()
        tutela.resolver(id_, "visto")
        self.assertEqual(registro.leer()[0]["nota"], 2)

    def test_queja_no_admite_decision(self):
        id_ = tutela.anotar("queja", texto="x")["id"]
        with self.assertRaises(ValueError):
            tutela.resolver(id_, "ok", rechazar=True)

    def test_cli_rechazar(self):
        id_ = self._reclamar()
        salida = io.StringIO()
        with redirect_stdout(salida):
            practica.main(["resolver", id_, "estaba mal", "--rechazar"])
        self.assertIn("rechazada", salida.getvalue())
        self.assertEqual(registro.leer()[0]["nota"], 1)
        notas = [n for n in tutela.leer_notas() if n["tipo"] == "resolucion"]
        self.assertEqual(notas[-1]["decision"], "rechazada")


if __name__ == "__main__":
    import unittest
    unittest.main()
