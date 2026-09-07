"""F4.4 — cuándo se adjudicará esto, con el margen de error delante.

El lead-time del órgano —la mediana de días entre publicar y adjudicar— se
calcula desde hace meses y se pinta en Mercado → Órganos y en la tira de
contexto del Resumen. Nadie lo usaba para lo único que un comercial pregunta
delante de una oportunidad abierta: *¿cuándo sabré si la gano?* Sin esa fecha
no se puede planificar un equipo, y el hueco se rellenaba a ojo.

Lo que este módulo **no** hace
------------------------------
No predice. Suma a la fecha límite la mediana histórica del órgano y publica
el intervalo p25-p75 junto con la ``n`` que lo sostiene, porque una fecha sola
se lee como un compromiso y esto es una estimación con dispersión conocida. Si
el órgano no llega al mínimo de expedientes, **no hay estimación**: la UI dice
«sin estimación» y no una fecha con un asterisco. Es la misma regla que el
resto del producto — ADR-014, y el mismo criterio que ``n`` mínimo aplica en
los cortes de competencia.

Cuando F2.1 traiga los hitos publicados del procedimiento, la fecha real
sustituye a la estimada y ``metodo`` pasa de ``estimacion`` a ``hito``. El
campo existe desde ahora para que ese cambio no obligue a tocar el contrato ni
a que la UI adivine cuál de las dos está mirando.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from shared.dates import a_fecha
from shared.dto import ExpectedAward

# `ExpectedAward` vive en `shared/dto.py` porque es contrato API↔web
# (invariante 5) y `shared` no puede importar de `services`. Aquí sólo
# está la regla que decide si se publica y con qué números.
__all__ = ["estimar_adjudicacion"]


def estimar_adjudicacion(
    fecha_limite: Any,
    stats: dict[str, Any] | None,
) -> ExpectedAward | None:
    """Fecha prevista de adjudicación, o ``None`` si no hay base para darla.

    ``stats`` es la entrada de :func:`db.repositories.adjudicaciones.
    lead_time_por_organo` para el órgano de la oportunidad, que ya filtra por
    la ``n`` mínima — de ahí que aquí baste con comprobar que existe.

    Devuelve ``None`` sin fecha límite: el lead-time se cuenta desde la
    publicación, pero lo que el usuario tiene delante es el cierre, y sumar la
    mediana a la fecha de publicación de algo cuyo plazo aún no ha vencido
    daría fechas ya pasadas. Sumarla al cierre sobreestima un poco —el
    lead-time incluye el plazo de presentación— y ese sesgo es conocido,
    conservador y va en la dirección segura: dice «más tarde», nunca «antes».
    """
    limite = a_fecha(fecha_limite)
    if limite is None or not stats:
        return None
    try:
        n = int(stats["n"])
        p25, p50, p75 = float(stats["p25"]), float(stats["p50"]), float(stats["p75"])
    except (KeyError, TypeError, ValueError):
        return None
    if n <= 0:
        return None

    return ExpectedAward(
        fecha=limite + timedelta(days=round(p50)),
        p25=limite + timedelta(days=round(p25)),
        p75=limite + timedelta(days=round(p75)),
        n=n,
        metodo="estimacion",
    )
