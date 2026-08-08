"""Qué estados PLACSP dejan viva una licitación.

Que un expediente siga siendo una oportunidad depende de su código de estado,
y esa decisión la consumen varias capas: el listado que alimenta el Radar
(``db/repositories/licitaciones.py``), el ranking (``scoring_candidates``), el
resumen de hoy (``overview_para_hoy``) y el dataset de scoring
(``services/ml/features.py``). Vive en ``shared`` para que ninguna vuelva a
enumerar su propia lista y se desincronicen.

Para SQL, usar :func:`abierta_sql` en vez de rehacer el fragmento: exportar
sólo la constante dejaba a cada llamante escribir su propia condición, que es
como el resumen terminó afirmando lo contrario que el Radar.

Las etiquetas legibles son otra cosa y viven en :mod:`services.classification`
(``ESTADO_LABELS``); aquí sólo está el juicio "cerrado o abierto".
"""

from __future__ import annotations

# Estados terminales: el expediente se resolvió (RES), se adjudicó (ADJ) o se
# anuló (ANUL). Ya no hay nada que licitar.
#
# Se enumera el cierre y nunca la apertura: PUB, EV, PRE, CREA —y cualquier
# código que la fuente incorpore mañana sin avisar— cuentan como abiertos. Al
# revés, un estado nuevo desaparecería del Radar en silencio, que es el fallo
# más caro de los dos.
ESTADOS_CERRADOS: tuple[str, ...] = ("RES", "ADJ", "ANUL")


def abierta_sql(col: str = "estado") -> str:
    """Predicado SQL ``sigue abierta``, listo para incrustar en un WHERE/FILTER.

    Exportar la constante no bastó: cada llamante seguía armando su propio
    fragmento, y ahí es donde ``overview_para_hoy`` acabó con una lista blanca
    (``estado IN ('PUB','EV')``) que decía justo lo contrario que el resto. El
    resumen contaba 0 activas mientras el Radar listaba 12.

    Los estados van como literales, no como placeholders: son constantes de
    este módulo —nunca entrada de usuario— y así el llamante no tiene que
    intercalarlos en un orden de parámetros posicionales que ya está ocupado.

    ``estado IS NULL`` cuenta como abierta: sin código no hay evidencia de
    cierre, y un ``NOT IN`` a secas descartaría esas filas en silencio.
    """
    cerrados = ", ".join(f"'{estado}'" for estado in ESTADOS_CERRADOS)
    return f"({col} IS NULL OR {col} NOT IN ({cerrados}))"


__all__ = ["ESTADOS_CERRADOS", "abierta_sql"]
