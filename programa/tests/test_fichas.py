"""Todas las fichas cargan y la clave de TODAS las combinaciones de parametros cuadra."""
import unittest

from calculo.fichas import cargar
from calculo.sesion import comprobar


class TestFichas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = cargar()

    def test_hay_fichas_de_los_dos_tipos(self):
        tipos = {f.tipo for f in self.fichas.values()}
        self.assertTrue({"integral", "derivada", "definida", "algebra", "parcial", "exacta", "potencial"} <= tipos)

    def test_basicas_incluidas(self):
        for id_ in ("I01", "I02", "I03", "I04", "I05", "D01", "D02", "D03", "D04", "D05"):
            self.assertIn(id_, self.fichas)

    def test_todas_las_claves(self):
        for ficha in self.fichas.values():
            for params in ficha.combinaciones():
                with self.subTest(ficha=ficha.id, params=params):
                    ficha.construir(params)  # lanza ErrorFicha si no cuadra

    def test_la_solucion_mostrada_se_acepta(self):
        """Lo que el motor ensena como solucion, tecleado tal cual, debe aprobarse."""
        for ficha in self.fichas.values():
            v = ficha.variante(semilla=1)
            with self.subTest(ficha=ficha.id, solucion=v.solucion_texto):
                self.assertTrue(comprobar(v, v.respuesta_modelo).correcto)

    def test_pistas(self):
        for ficha in self.fichas.values():
            v = ficha.variante(semilla=2)
            with self.subTest(ficha=ficha.id):
                self.assertEqual(len(ficha.pistas), 3)
                for nivel in (1, 2, 3, 4):
                    self.assertTrue(v.pista(nivel))

    def test_parciales_con_el_metodo_de_pon_x_igual_a_2(self):
        """Parciales: «la otra letra es un numero; pon x = 2». Con dos letras, la
        pista 2 o la 3 lleva el metodo (pon x = 2 o y = 2, deriva o integra con una
        letra, vuelve a poner la letra). Ninguna prueba con 1: con 1 desaparecen las
        potencias y no se ve de donde sale cada numero."""
        import re
        from calculo.expresiones import X, Y
        metodo = re.compile(r"\b[xy] = 2\b")
        vuelta = re.compile(r"vuelve a poner", re.IGNORECASE)
        con_uno = re.compile(r"\b(?:pon|haz|imagina|con)\s+[xy]\s*=\s*1\b", re.IGNORECASE)
        for ficha in self.fichas.values():
            if ficha.tipo not in ("parcial", "exacta", "potencial"):
                continue
            for params in ficha.combinaciones():
                v = ficha.construir(params)
                funciones = v.funcion if isinstance(v.funcion, tuple) else (v.funcion,)
                dos_letras = any({X, Y} <= f.free_symbols for f in funciones)
                pistas = [v.pista(n) for n in (1, 2, 3)]
                with self.subTest(ficha=ficha.id, params=params):
                    self.assertFalse([p for p in pistas if con_uno.search(p)])
                    if dos_letras:
                        self.assertTrue(any(metodo.search(p) and vuelta.search(p) for p in pistas[1:]), pistas)

    def test_variantes_deterministas(self):
        f = self.fichas["S-XEXP"]
        self.assertEqual(f.variante(7).enunciado, f.variante(7).enunciado)


class TestPistasNoRegalan(unittest.TestCase):
    """Las pistas 1-3 dan el ultimo PASO, no el resultado, y no usan
    letras que el alumno no ha visto. La pista 4 (pasos y solucion) si la ensena.

    Regalar = el texto de la pista contiene la solucion tal cual (sin espacios ni ·),
    o algun trozo matematico de la pista vale lo mismo que la solucion (sympy), aunque
    este sin operar: «x^(7+1)/(7+1)», «4·x^(4-1)», «C1 = ((-1) - 3·2)/(2 - 3)».
    No cuentan los numeros y letras sueltos (2, x), los trozos que repiten el enunciado
    ni, en algebra, las reescrituras del lado derecho mas largas que el."""

    SEMILLAS = (0, 1, 2)
    # ficha -> motivo. Una pista que regale por fuerza va aqui, justificada. Hoy vacia.
    LISTA_BLANCA = {}
    FUNCIONES = r"(?:arctan|arcsen|arccos|ln|sen|cos|tan|sec|log|sqrt|exp)"
    # Letras que siempre se entienden: variables (x, y, r de la caracteristica, u, v, t de
    # los cambios), constantes (e, i, π, C, C1...), funciones y nombres de clase (f, g, F, M,
    # N, W, I, A, B, D, φ, μ, α ± βi, y1, y2, r1, r2...) y palabras de una letra («o», «y»).
    SIEMPRE = (set("x y e i o u C d f g t v r A B D F I M N W α β φ μ π".split())
               | {"C1", "C2", "C3", "y1", "y2", "u1", "u2", "r1", "r2"})

    @classmethod
    def setUpClass(cls):
        import re
        cls.re = re
        cls.fichas = cargar()
        cls.matematico = re.compile(r"^(?:" + cls.FUNCIONES + r"|[\dxyCe()\[\]^+\-·*/.√|π±])+$")

    # ---------- solucion dentro de la pista ----------
    def _trozos(self, texto):
        re = self.re
        for pieza in re.split(r"[;:→,=¿?]|\b[Qq]ueda\b|\bes\b|\by\s(?=[a-z])", texto):
            seguidos = []
            for t in pieza.split() + ["#"]:
                letra = re.fullmatch(r"[a-zA-Z]", t.strip("()"))
                if (self.matematico.match(t) and (not letra or t.strip("()") == "x" or seguidos)) \
                        or (seguidos and t in "+-·/"):
                    seguidos.append(t)
                elif seguidos:
                    yield " ".join(seguidos).rstrip(".")
                    seguidos = []

    @staticmethod
    def _suelto(e):
        import sympy as sp
        if isinstance(e, sp.Mul) and len(e.args) == 2 and e.args[0] == -1:
            e = e.args[1]
        return isinstance(e, (sp.Symbol, sp.Integer)) or (e.is_number and len(str(e)) <= 2)

    def _objetivos(self, v):
        from calculo.expresiones import leer
        tipo, s = v.ficha.tipo, v.solucion
        if tipo == "algebra":
            objetivos = [(n, val, False) for n, val in s.items()]
            if v.ficha.identidad:
                todos = {**v.params, **{n: str(val) for n, val in s.items()}}
                derecha = leer(v.ficha.identidad[1].format(**todos))[0]
                if derecha.free_symbols:
                    objetivos.append(("lado derecho", derecha, True))
            return objetivos
        if tipo == "exacta":
            return [("∂M/∂y", s[0], False), ("∂N/∂x", s[1], False)]
        if tipo == "raices":
            return [("raiz", r, False) for r in s]
        return [("solucion", s, False)]

    def _iguales(self, trozo, objetivo, tipo):
        import sympy as sp
        from calculo.expresiones import X, Y
        from calculo.verificar import comparar
        try:
            if tipo in ("integral", "potencial"):   # salvo constante: se comparan derivadas
                if sp.diff(objetivo, X) == 0:
                    return False
                ok = comparar(sp.diff(trozo, X), sp.diff(objetivo, X))[0]
                return ok and (tipo == "integral" or comparar(sp.diff(trozo, Y), sp.diff(objetivo, Y))[0])
            return comparar(sp.sympify(trozo), sp.sympify(objetivo))[0]
        except Exception:
            return False

    def regalos(self, v, nivel):
        import sympy as sp
        from calculo.expresiones import leer
        texto = v.pista(nivel)
        plano = lambda t: self.re.sub(r"[\s·*]", "", t).replace("e^(x)", "e^x")
        hallados = []
        solucion = plano(v.respuesta_modelo)
        if len(solucion) > 2 and solucion in plano(texto):
            hallados.append(("tal cual", v.respuesta_modelo))
        for trozo in self._trozos(texto):
            try:
                valor = leer(trozo, variables="xyC")[0]
                crudo = leer(trozo, variables="xyC", evaluar=False)[0]
            except Exception:
                continue
            if self._suelto(crudo) or plano(trozo) in plano(v.enunciado):
                continue
            for nombre, objetivo, es_lado_derecho in self._objetivos(v):
                objetivo = sp.sympify(objetivo)
                if self._suelto(objetivo) and v.ficha.tipo != "algebra":
                    continue
                if es_lado_derecho and sp.count_ops(crudo) > sp.count_ops(objetivo) + 1:
                    continue
                if self._iguales(valor, objetivo, v.ficha.tipo):
                    hallados.append((nombre, trozo))
        return hallados

    def test_ninguna_pista_1_a_3_contiene_la_solucion(self):
        problemas = []
        for f in self.fichas.values():
            if f.id in self.LISTA_BLANCA:
                continue
            for semilla in self.SEMILLAS:
                v = f.variante(semilla)
                for nivel in (1, 2, 3):
                    r = self.regalos(v, nivel)
                    if r:
                        problemas.append((f.id, semilla, nivel, r, v.pista(nivel)))
        self.assertEqual(problemas, [])

    def test_el_detector_ve_los_regalos_de_antes(self):
        """Las pistas que regalan el resultado se detectan."""
        import copy
        casos = {"P-POT": "x^{n} → x^({n}+1)/({n}+1).", "D01": "4·x^(4-1).",
                 "PC-POT": "Resultado: {n}·x^{m}·y^({n}-1).", "AL-TAN": "tan({ang}) = sen({ang})/cos({ang}) = √3/3.",
                 "AL-LNEXP": "Queda ({a}) · e^(({b})x): k es lo que multiplica y m lo que acompana a x.",
                 "AL-SIS2": "C1 = (({b}) - ({r2})·({a}))/(({r1}) - ({r2})); despues C2 = ({a}) - C1."}
        params = {"P-POT": {"n": 7}, "D01": {}, "PC-POT": {"m": 2, "n": 3}, "AL-TAN": {"ang": "π/6"},
                  "AL-LNEXP": {"a": 3, "b": -4}, "AL-SIS2": {"r1": 1, "r2": 3, "a": 1, "b": 0}}
        for fid, pista in casos.items():
            f = copy.copy(self.fichas[fid])
            f.pistas = [f.pistas[0], f.pistas[1], pista]
            with self.subTest(ficha=fid):
                self.assertTrue(self.regalos(f.construir(params[fid]), 3))

    # ---------- letras sin definir ----------
    def _letras(self, texto):
        re = self.re
        for m in re.finditer(r"(?<![A-Za-zÁ-úñ_\d])([A-Za-zα-ω])(\d?)(?![A-Za-zÁ-úñ_\d])", texto):
            yield m.group(1) + m.group(2), m.start(), m.end()
        for m in re.finditer(r"(?<![A-Za-zÁ-úñ_])([a-z])[xy](?![A-Za-zÁ-úñ_])", texto):  # «ax», «kx», «wx»
            yield m.group(1), m.start(), m.end()

    @staticmethod
    def _es_la_preposicion_a(texto, i, j):
        """«multiplica a dx» frente a «(2a + s)» o «a ± b i»: la letra va pegada a la cuenta."""
        cuenta = set("0123456789(^·*/+-±=)")
        return (texto[i - 1:i] not in cuenta or i == 0) and texto[j:j + 1] not in cuenta \
            and not texto[j:].startswith(" ±") and not texto[:i].endswith("± ")

    def letras_sin_definir(self, v, nivel):
        """Letras sueltas de la pista que no estan en SIEMPRE, ni en el enunciado, ni son
        los valores que se piden (algebra), ni se definen en una pista («con c = 3»)."""
        texto = v.pista(nivel)
        definidas = set(self.SIEMPRE) | set(v.ficha.valores) | {t for t, _, _ in self._letras(v.enunciado)}
        for n in (1, 2, 3):
            definidas |= set(self.re.findall(r"(?<![A-Za-z])([A-Za-z]\d?) = ", v.pista(n)))
        return [t for t, i, j in self._letras(texto)
                if t not in definidas and not (t == "a" and self._es_la_preposicion_a(texto, i, j))]

    def test_ninguna_pista_usa_letras_sin_definir(self):
        problemas = []
        for f in self.fichas.values():
            for semilla in self.SEMILLAS:
                v = f.variante(semilla)
                for nivel in (1, 2, 3):
                    raras = self.letras_sin_definir(v, nivel)
                    if raras:
                        problemas.append((f.id, nivel, raras, v.pista(nivel)))
        self.assertEqual(problemas, [])

    def test_el_detector_ve_las_letras_de_antes(self):
        import copy
        casos = {"T2X-YP-RES": ("Sustituye y_p = A x e^(ax): A (2a + s) = 1, despeja A.", {"a": 3, "b": -1}),
                 "T2X-EU-GEN": ("Prueba y = x^r: da r(r - 1) + s r + p = 0.", {"r1": 3, "r2": -2}),
                 "R-LOGIST": ("Con x = 0 sale A = 1/a; la otra constante, con x = a/b.", {"a": 1, "b": 3}),
                 "S-EXPMIX": ("Mezcla a^x y a^(-x): todo se puede escribir con a^x.", {"a": 3})}
        for fid, (pista, params) in casos.items():
            f = copy.copy(self.fichas[fid])
            f.pistas = [pista, f.pistas[1], f.pistas[2]]
            with self.subTest(ficha=fid):
                self.assertTrue(self.letras_sin_definir(f.construir(params), 1))
        # y la preposicion no cuenta
        f = copy.copy(self.fichas["EX-NO"])
        f.pistas = ["M es lo que multiplica a dx.", f.pistas[1], f.pistas[2]]
        self.assertEqual(self.letras_sin_definir(f.construir({}), 1), [])


if __name__ == "__main__":
    unittest.main()
