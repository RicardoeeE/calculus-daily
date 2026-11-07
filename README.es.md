<div align="center">

# ∫ Calculus Daily

**Diez minutos de cálculo al día, programados con FSRS y corregidos con SymPy — sin conexión, en tu ordenador.**

Práctica diaria de derivadas, integrales, derivadas parciales y EDOs: elige lo que toca hoy, genera una variante nueva de cada ejercicio, corrige el resultado escrito como en clase y te dice *por qué* falla.

[![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-green.svg)](LICENSE)
[![Pruebas](https://img.shields.io/badge/pruebas-485%20en%20verde%20%C2%B7%203%20omitidas-brightgreen.svg)](README.md#tests)
[![Plataforma](https://img.shields.io/badge/plataforma-Windows%20(probado)-0078D6?logo=windows&logoColor=white)](#empezar)
[![Sin conexión](https://img.shields.io/badge/sin%20conexi%C3%B3n-sin%20cuenta%20ni%20nube-555.svg)](README.md#engineering-highlights)

[English](README.md) · [Notas de diseño (EN)](programa/docs/DESIGN.md) · por [Ricardo Eiras](https://github.com/RicardoeeE) — estudiante de Ingeniería Mecánica

<img src="programa/docs/capturas/demo.gif" alt="Una sesión: ejemplo resuelto, confianza, vista previa «He leído», pistas, solución, una parcial corregida y una lección guiada" width="760">

</div>

## Por qué

- **Las tarjetas de memoria no entrenan procedimientos.** → Cada ficha es una *familia* con parámetros: cada repaso es una variante nueva.
- **Ponerse nota a uno mismo tiene sesgo.** → La nota sale de hechos (acierto, pistas, intentos fallidos, tiempo, confianza) y FSRS decide el próximo repaso.
- **«Mal» no enseña nada.** → Se acepta cualquier forma equivalente y se nombra el error típico (cadena, factor, signo, límites al revés…).

## Qué trae

- 🗓️ Repaso espaciado FSRS: 5 ejercicios al día (2 el día mínimo), sin pasarse nunca del cupo.
- 🎲 172 fichas de 25 técnicas, 87 de ellas con parámetros; todas las claves comprobadas con SymPy.
- ✅ Corrección simbólica y por muestreo; avisos de `+C` y de `ln|x|`.
- ✍️ Se escribe como en el papel (`e^2x/2 + C`, `x sen x`, `2±3i`) con vista previa en KaTeX.
- 📖 Lecciones de 7 técnicas clave: teoría, forma tipo, errores típicos, 2-3 ejemplos y un ejemplo guiado con opciones que explican por qué están bien o mal.
- 🪜 Tres pistas graduadas, solución paso a paso y ejemplos resueltos con huecos.
- 📈 Dominio por técnica (Beta-Binomial), escalera de técnicas y repetición implícita.
- 📝 Con un examen cerca, un botón en la ventana da rondas extra solo de sus técnicas; simulacro cronometrado y prueba de nivel en la terminal.
- 📐 Diseño de libro de matemáticas, claro y oscuro, que se adapta a cualquier ancho.
- 🔒 Datos en JSON Lines que solo se amplían, con cerrojo, copias verificadas con SHA-256 y git.

## Empezar

1. `git clone https://github.com/RicardoeeE/calculus-daily.git` (probado con Python 3.13; `doctor` admite 3.11 o superior).
2. **Windows:** doble clic en `Practicar.bat` (la primera vez prepara el entorno, unos 3 min). **Cualquier sistema:** `python -m venv .venv`, instala `programa/requirements.txt` y `programa/requirements-ventana.txt`, y ejecuta `python programa/practica.py ventana` (o `hoy` para la terminal).
3. Elige tu confianza (1-5), resuelve en papel, escribe solo el resultado y pulsa Enter.

La ventana está probada en Windows; en Linux y macOS funciona la terminal y la ventana no está probada.

## Cómo funciona

```mermaid
flowchart LR
    A[(registro.jsonl)] --> B[FSRS y dominio]
    B --> C[Cola del día]
    C --> D[Variante nueva]
    D --> E[Tu respuesta]
    E --> F{Corrección SymPy}
    F -- mal --> G[Diagnóstico y pistas]
    G --> E
    F -- bien / me rindo --> H[Nota 1-4]
    H --> A
```

Los detalles (nota objetiva, FSRS, dominio, grafo de técnicas, protección de datos) están en las [notas de diseño](programa/docs/DESIGN.md) y en el [README en inglés](README.md#engineering-highlights). Para elegir técnica antes de integrar: [hoja de reconocimiento](programa/docs/hoja-reconocer.md).

## Pruebas

```bash
.venv\Scripts\python.exe programa\herramientas\pruebas.py                         # 488 pruebas (485 en verde, 3 omitidas), sin ventanas, unos 8 min
.venv\Scripts\python.exe programa\practica.py ventana --prueba                   # humo de la ventana
```

## Licencia

Código: [MIT](LICENSE) © 2026 Ricardo Eiras. Documentación de `programa/docs/`: CC BY 4.0. KaTeX: MIT.

<div align="center">

**Si te ayuda a estudiar, dale una ⭐**

</div>
