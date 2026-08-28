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

# Estados terminales: el expediente se resolvió (RES), se adjudicó (ADJ), se
# anuló (ANUL), se publicó de forma agregada (AGR) o ya está en ejecución
# (EJEC). Ya no hay nada que licitar.
#
# Se enumera el cierre y nunca la apertura: PUB, EV, PRE, CREA, CPM —y
# cualquier código que la fuente incorpore mañana sin avisar— cuentan como
# abiertos. Al revés, un estado nuevo desaparecería del Radar en silencio, que
# es el fallo más caro de los dos.
#
# ``AGR`` y ``EJEC`` se añadieron el 2026-08-26 y no son códigos PLACSP: son
# las dos fases de la PSCP catalana que el conector guardaba como etiqueta
# cruda (ver ``services.classification.normalizar_estado``). Contarlas como
# abiertas no era una decisión, era el efecto de no reconocerlas:
#
# - ``AGR`` (*publicació agregada*) son avisos que agrupan contratos ya
#   celebrados, sin plazo propio; nunca fueron una oportunidad individual a la
#   que presentarse. Son 645.664 de las 691.974 filas del corpus —el 93%—, así
#   que mientras contaron como abiertas el "Total activas" del Resumen decía
#   657.156 sobre 691.974: el KPI más grande de la pantalla de entrada medía
#   el tamaño del corpus, no el de la oportunidad.
# - ``EJEC`` (*execució*) es un contrato ya adjudicado y en marcha.
#
# El Radar no cambia con esto: ``scoring_candidates`` ya las descartaba por no
# tener ``fecha_limite`` viva. Lo que cambia son las superficies que cuentan
# por estado —``count_total_activas``, ``overview_para_hoy``, el filtro "sólo
# abiertas" y ``licitaciones_abiertas`` del dataset de ML—, que hasta ahora
# contradecían al Radar.
ESTADOS_CERRADOS: tuple[str, ...] = ("RES", "ADJ", "ANUL", "AGR", "EJEC")


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
