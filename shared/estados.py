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
(``ESTADO_LABELS``); aquí sólo está el juicio "cerrado o abierto" y, desde
2026-08-27, el vocabulario canónico completo (:data:`ESTADOS_CANONICOS`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Estados terminales: el expediente se resolvió (RES), se adjudicó (ADJ) o se
# anuló (ANUL). Ya no hay nada que licitar.
#
# Se enumera el cierre y nunca la apertura: PUB, EV, PRE, CREA —y cualquier
# código que la fuente incorpore mañana sin avisar— cuentan como abiertos. Al
# revés, un estado nuevo desaparecería del Radar en silencio, que es el fallo
# más caro de los dos.
#
# AGREG y EJEC son de la PSCP catalana y se añaden aquí con evidencia medida
# contra el dataset ybgg-dgi6 (ver la tabla de `scraper/connectors/pscp.py`):
#
# - AGREG ("Publicació agregada de contractes"): publicación trimestral en
#   bloque de contratos menores ya adjudicados. Cero filas con plazo de
#   presentación, 99,6% con adjudicatario. Es el 93% del corpus, así que
#   dejarlo fuera de esta tupla es exactamente lo que hacía que "Total activas"
#   diera 657.158.
# - EJEC ("Execució"): contrato en ejecución, posterior a la formalización.
#   93,6% con adjudicatario. El contrato está vivo; la licitación no.
#
# Ambos tienen código propio en vez de reutilizar ADJ/RES para no fundir 1,7M
# de contratos menores con los 58.528 anuncios de adjudicación reales: cerrado
# sí, pero no es lo mismo y los KPIs competitivos lo distinguen.
ESTADOS_CERRADOS: tuple[str, ...] = ("RES", "ADJ", "ANUL", "AGREG", "EJEC")

# Vocabulario canónico completo. Existe porque el campo ``estado`` llegó a
# contener texto crudo de la fuente truncado a 20 caracteres ("EXPEDIENT EN
# AVALUAC", "PUBLICACIÓ AGREGADA "), y ese ruido salía por ``GET
# /meta/filters`` como si fueran opciones legítimas de filtro.
#
# Enumerar la apertura aquí NO contradice el razonamiento de ESTADOS_CERRADOS:
# son dos preguntas distintas. Esta lista responde "¿es un código que este
# sistema reconoce?" (para no ofrecer basura en la UI); aquélla responde "¿está
# cerrada?" (donde lo desconocido debe contar como abierto, no desaparecer).
# Por eso un estado no canónico se oculta del selector pero sigue en el corpus
# y sigue contando como abierto hasta que alguien lo mapee.
ESTADOS_CANONICOS: frozenset[str] = frozenset(
    {
        "CREA",  # creada, aún sin publicar
        "PRE",  # anuncio previo / consulta preliminar / alerta futura
        "PUB",  # anuncio de licitación con plazo abierto
        "EV",  # ofertas en evaluación
        "ADJ",  # adjudicada
        "RES",  # resuelta / formalizada
        "ANUL",  # anulada o desistida
        "AGREG",  # publicación agregada de contratos menores (PSCP)
        "EJEC",  # contrato en ejecución (PSCP)
    }
)


def normalizar_estado(valor: str | None) -> str | None:
    """Devuelve el código canónico de ``valor``, o ``None`` si no lo es.

    Normaliza lo que la fuente podría haber dejado con espacios o en minúsculas
    ("publicació agregada " venía con espacio final), pero no adivina: si tras
    limpiar no está en :data:`ESTADOS_CANONICOS`, devuelve ``None``. Quien
    quiera mapear una fase nueva lo hace en el conector, no aquí.
    """
    if valor is None:
        return None
    limpio = valor.strip().upper()
    return limpio if limpio in ESTADOS_CANONICOS else None


def filtrar_estados_canonicos(valores: Iterable[str | None]) -> list[str]:
    """Deja sólo códigos canónicos, sin duplicados y ordenados.

    Pensado para los selectores de la UI: el corpus histórico sigue teniendo
    filas sucias y no se puede esperar a repararlas para dejar de ofrecerlas
    como filtro. Ordena alfabéticamente porque es lo que ya devolvía el
    ``loose_distinct_strings`` del repositorio y así el selector no baila.
    """
    return sorted({canon for valor in valores if (canon := normalizar_estado(valor))})


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


__all__ = [
    "ESTADOS_CANONICOS",
    "ESTADOS_CERRADOS",
    "abierta_sql",
    "filtrar_estados_canonicos",
    "normalizar_estado",
]
