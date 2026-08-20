"""Fragmentos SQL constantes que necesita el propio ``db/``.

Gemelo de ``services/sql_fragments.py`` en el lado correcto de la frontera.
Existe por la colisión de dos reglas del proyecto:

- **ADR-022**: todo el SQL vive en ``db/``. La migración del ratchet TID251 va
  moviendo queries de ``services/`` a ``db/``, y esas queries se llevan consigo
  los fragmentos que interpolan.
- **ADR-024**: ``db/`` no puede depender de ``services/`` (capa superior). Un
  ``from services.dedupe import ...`` dentro de ``db/`` invierte las capas.

Hasta ahora la salida era duplicar el fragmento en ``db/`` con un comentario
apuntando al original (``db/repositories/ml_dataset.py::_NO_DUPLICADOS``,
``db/repositories/pricing.py`` con ``EFFECTIVE_BUDGET_SQL``). Eso funciona para
una línea, pero :data:`FECHA_FIN_SQL` son doce con aritmética de intervalos: una
tercera copia es una divergencia esperando a ocurrir.

Así que la definición canónica de estos tres fragmentos baja aquí y
``services/sql_fragments.py`` y ``services/dedupe.py`` los **reexportan**. Los
call-sites de ``services/`` siguen importando de donde siempre; lo que cambia es
la dirección de la dependencia, que ahora es ``services/ → db/``, la permitida.

No se movieron los demás fragmentos de ``services/sql_fragments.py``: solo
bajan los que ``db/`` consume hoy. Bajar el resto es trabajo de la misma ola del
ratchet, cuando alguna query de ``db/`` los necesite.
"""

from __future__ import annotations

# Universo por defecto de los agregados del radar. Las filas anteriores al
# linaje se consideran legado del radar porque el único pipeline histórico
# filtraba tecnología; las nuevas fuentes deben declarar su universo y quedan
# fuera salvo que una métrica las solicite expresamente.
TECHNOLOGY_OBSERVED_SQL = (
    "COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'"
)

# Fecha de fin efectiva del contrato, con prioridad:
# 1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
# 2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
# 3. ``fecha_adjudicacion + duracion`` como último recurso.
# substr(x, 1, 10) normaliza timestamps ISO a fecha pura; CAST a INT porque
# duracion_valor es REAL y el CAST a INTEGER es necesario para la aritmética
# de INTERVAL. Asume alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
#
# Devuelve TEXT 'YYYY-MM-DD' (via to_char) y no un date, para que las
# comparaciones lexicográficas contra las columnas de fecha —que son TEXT en
# este esquema— sean equivalentes.
FECHA_FIN_SQL = """
COALESCE(
    substr(l.fecha_fin, 1, 10),
    CASE l.duracion_unidad
        WHEN 'ANN' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 year'), 'YYYY-MM-DD')
        WHEN 'MON' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 month'), 'YYYY-MM-DD')
        WHEN 'DAY' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 day'), 'YYYY-MM-DD')
    END
)
"""


def fecha_fin_sql() -> str:
    """Fragmento SQL de fecha de fin efectiva.

    Envoltorio de :data:`FECHA_FIN_SQL`. Existía para elegir dialecto entre los
    dos motores; desde ADR-021 hay uno solo, pero se conserva porque es el
    accessor que usan los call-sites y mantiene el punto único de cambio.
    """
    return FECHA_FIN_SQL


def exclude_duplicados_sql(col: str = "l.id_externo") -> str:
    """Cláusula SQL para excluir filas no-canónicas en consultas analíticas.

    ``col`` es la columna que referencia a ``licitaciones.id_externo`` en la
    query llamadora (``l.id_externo``, ``a.licitacion_id``…). Centralizada
    para no repetir la subquery en cada servicio. Solo excluye duplicados
    ``confirmed``; los ``pending`` cuentan hasta que un humano los confirme.

    La lógica de dominio del dedupe (matching, marcado, cursor) sigue en
    ``services/dedupe.py``; aquí vive solo el fragmento SQL, que es lo que
    ADR-022 pide tener en ``db/`` y lo que ``db/`` necesita poder interpolar
    sin importar hacia arriba.
    """
    # S608: `col` es una referencia de columna fija escrita por los servicios
    # llamadores, nunca input de usuario; los valores siempre van con ?.
    subquery = "(SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')"
    return f"{col} NOT IN {subquery}"
