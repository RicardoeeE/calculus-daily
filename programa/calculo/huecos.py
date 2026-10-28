"""Ejemplos con huecos (retirada progresiva): cuantos pasos se ocultan segun los aciertos."""

HUECO = "____"
MAX_HUECOS = 2
SIN_EJEMPLO = 3   # aciertos desde los que ya no se ensena ejemplo


def _cuenta(e):
    """Intentos que dicen algo de si se sabe la tecnica: no los de simulacro (sin
    pistas ni ejemplo, otra cosa) ni los de la prueba de nivel sin acierto (un «no
    lo se» de quien nunca la aprendio no es un intento de verdad)."""
    if e.get("motivo") == "simulacro":
        return False
    if e.get("motivo") == "nivel":
        return e.get("nota", 0) >= 3
    return True


def huecos_de(entradas, tecnica):
    """Pasos a ocultar en el ejemplo de la tecnica:
    - None (sin ejemplo) desde SIN_EJEMPLO aciertos;
    - 0 (ejemplo completo) si nunca se acerto o si el ultimo intento fue fallo o
      rendicion (nota 1): quien acaba de fallar necesita el ejemplo entero, no uno
      mas dificil que quien nunca lo intento;
    - si no, tantos huecos como aciertos (1 o 2)."""
    propios = [e for e in entradas if e.get("tecnica") == tecnica and _cuenta(e)]
    propios.sort(key=lambda e: e.get("ts", ""))
    aciertos = sum(1 for e in propios if e.get("nota", 0) >= 3)
    if aciertos >= SIN_EJEMPLO:
        return None
    if aciertos == 0 or propios[-1].get("nota", 0) <= 1:
        return 0
    return min(aciertos, MAX_HUECOS)


def recortar(pasos, huecos):
    """(pasos con los ultimos `huecos` sustituidos por HUECO, pasos ocultos). Siempre queda
    visible al menos el primer paso."""
    n = max(0, min(huecos, len(pasos) - 1))
    if n == 0:
        return list(pasos), []
    return list(pasos[:-n]) + [HUECO] * n, list(pasos[-n:])
