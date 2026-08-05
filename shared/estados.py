"""Qué estados PLACSP dejan viva una licitación.

Que un expediente siga siendo una oportunidad depende de su código de estado,
y esa decisión la consumen varias capas: el listado que alimenta el Radar
(``db/repositories/licitaciones.py``) y el dataset de scoring
(``services/ml/features.py``). Vive en ``shared`` para que ninguna vuelva a
enumerar su propia lista y se desincronicen.

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

__all__ = ["ESTADOS_CERRADOS"]
